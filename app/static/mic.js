// app/static/mic.js -- the phone's microphone, in-person mode only. Served
// solely by a `start --in-person` server and injected solely into `/s/{t}?mic`
// (app/web/server.py); a two-stream run's page never loads it.
//
// The ONLY file in the repository allowed to touch a browser capture API
// (app/tests/test_phase_gates.py gate 2, which also asserts the secure-context
// check below runs before any capture call). Capture needs a secure context:
// localhost, or the laptop's tailnet name over HTTPS via `tailscale serve`.
//
// Wiring only, like app.js: resampling, PCM conversion, framing and the level
// maths live in the pure, node-tested `mic-core.mjs`; reconnect backoff is the
// one app.js already uses.
//
// Frames that cannot be sent right now are DROPPED, never queued: the laptop
// paces audio against wall time, zero-fills gaps, and caps its own backlog at
// 2 s (app/capture/remote.py), so a phone-side queue could only arrive late.
import {
  FRAME_SAMPLES,
  FrameBatcher,
  Resampler16k,
  floatToPcm16,
  rmsDbfs,
} from "./mic-core.mjs";
import { BackoffCalculator } from "./live-state.mjs";

(function () {
  "use strict";

  var button = document.getElementById("mic-button");
  var statusEl = document.getElementById("mic-status");
  var levelEl = document.getElementById("mic-level");
  if (!button || !statusEl || !levelEl) {
    return;
  }

  // Secure context FIRST: on a plain-HTTP LAN address the capture API is
  // simply absent, and the honest thing is to say why, not to fail later.
  if (!window.isSecureContext) {
    button.disabled = true;
    setStatus("Microphone blocked: this page needs HTTPS. Open it via the laptop's tailnet address, not a plain IP.", "error");
    return;
  }

  var basePath = window.location.pathname.replace(/\/$/, "");
  var wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  var audioUrl = wsProtocol + "//" + window.location.host + basePath + "/audio";

  var BACKOFF_BASE_MS = 500;
  var BACKOFF_CAP_MS = 10000;
  // ~2 s of PCM16 at 16 kHz, matching the laptop's backlog cap: past this the
  // socket is not draining and anything more would only arrive stale.
  var MAX_BUFFERED_BYTES = 64000;
  var LEVEL_FLOOR_DBFS = -60;
  // Close codes the server sends on purpose (app/web/server.py); retrying
  // them cannot succeed, so they end the recording instead.
  var CLOSE_BAD_TOKEN = 4404;
  var CLOSE_MIC_BUSY = 4409;
  var CLOSE_BAD_AUDIO = 1003;
  // After a network drop the laptop can still hold THIS phone's dead socket
  // (until its ping times out) and answer the reconnect with "busy". Within
  // this window of the last good connection, busy means "our own ghost":
  // keep retrying. Outside it, it really is another phone.
  var OWN_GHOST_WINDOW_MS = 60000;
  var RECORDING_MESSAGE = "Recording. The first voice is taken to be you.";

  // The processor runs on the audio thread and only copies channel 0 out;
  // every decision stays on the main thread. Built from a Blob so the page
  // needs no extra route.
  var WORKLET_SOURCE =
    "class MicTap extends AudioWorkletProcessor {" +
    "  process(inputs) {" +
    "    var ch = inputs[0] && inputs[0][0];" +
    "    if (ch && ch.length) this.port.postMessage(ch.slice(0));" +
    "    return true;" +
    "  }" +
    "}" +
    "registerProcessor('mic-tap', MicTap);";

  var recording = false;
  var mediaStream = null;
  var audioCtx = null;
  var tapNode = null;
  var resampler = null;
  var batcher = null;
  var socket = null;
  var backoff = new BackoffCalculator({ baseMs: BACKOFF_BASE_MS, capMs: BACKOFF_CAP_MS });
  var reconnectTimer = null;
  var wakeLock = null;
  var wakeLockPending = false;
  var droppedFrames = 0;
  var lastAliveAt = 0; // when an opened socket last closed; 0 = none this recording

  function setStatus(text, kind) {
    statusEl.textContent = text;
    statusEl.dataset.kind = kind || "info";
  }

  function setLevel(dbfs) {
    var clamped = Math.max(LEVEL_FLOOR_DBFS, Math.min(0, dbfs));
    var fraction = (clamped - LEVEL_FLOOR_DBFS) / -LEVEL_FLOOR_DBFS;
    levelEl.style.setProperty("--mic-level", fraction.toFixed(3));
  }

  function isSocketOpen() {
    return socket !== null && socket.readyState === WebSocket.OPEN;
  }

  // --- the audio socket --------------------------------------------------

  function connect() {
    if (!recording || (socket !== null && socket.readyState <= WebSocket.OPEN)) {
      return;
    }
    var ws = new WebSocket(audioUrl);
    ws.binaryType = "arraybuffer";
    socket = ws;
    var opened = false;
    ws.onopen = function () {
      opened = true;
      backoff.reset();
      setStatus(RECORDING_MESSAGE, "live");
    };
    ws.onclose = function (event) {
      if (socket === ws) {
        socket = null;
      }
      if (opened) {
        lastAliveAt = Date.now();
      }
      if (!recording) {
        return;
      }
      if (event.code === CLOSE_MIC_BUSY && lastAliveAt > 0 && Date.now() - lastAliveAt < OWN_GHOST_WINDOW_MS) {
        setStatus("Reconnecting: the laptop is still closing the old connection.", "warn");
        scheduleReconnect();
      } else if (event.code === CLOSE_MIC_BUSY) {
        stopRecording("Another phone is already recording this session.", "error");
      } else if (event.code === CLOSE_BAD_TOKEN) {
        stopRecording("This link is no longer valid. Rescan the code on the laptop.", "error");
      } else if (event.code === CLOSE_BAD_AUDIO) {
        stopRecording("The laptop refused the audio. Reload the page and start again.", "error");
      } else {
        setStatus("Connection lost. Reconnecting; audio meanwhile is not saved.", "warn");
        scheduleReconnect();
      }
    };
    // An error is always followed by a close, which decides what happens next.
    ws.onerror = function () {};
  }

  function scheduleReconnect() {
    if (reconnectTimer !== null) {
      return;
    }
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      connect();
    }, backoff.nextDelayMs());
  }

  function sendFrame(frame) {
    if (!isSocketOpen() || socket.bufferedAmount > MAX_BUFFERED_BYTES) {
      droppedFrames += 1;
      return;
    }
    socket.send(frame);
  }

  // --- capture -----------------------------------------------------------

  function onAudioBlock(event) {
    if (!recording) {
      return;
    }
    var pcm = floatToPcm16(resampler.push(event.data));
    var frames = batcher.push(pcm);
    for (var i = 0; i < frames.length; i++) {
      sendFrame(frames[i]);
    }
    if (frames.length > 0) {
      setLevel(rmsDbfs(event.data));
    }
  }

  async function openMicrophone() {
    // The context is created BEFORE the first await, while the click's user
    // activation is still live: made after the permission prompt (which can
    // take the user longer than the activation window) it would start
    // suspended, and a resume() without a gesture never settles.
    audioCtx = new AudioContext();
    audioCtx.resume().catch(function () {});
    // Raw-ish room audio: echo cancellation and noise suppression are tuned
    // for a call and can eat the far voice in a room. Gain control stays on;
    // the voiceprint check was measured on phone audio with it on.
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: true },
      video: false,
    });
    var moduleUrl = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: "text/javascript" }));
    try {
      await audioCtx.audioWorklet.addModule(moduleUrl);
    } finally {
      URL.revokeObjectURL(moduleUrl);
    }
    resampler = new Resampler16k(audioCtx.sampleRate);
    batcher = new FrameBatcher(FRAME_SAMPLES);
    var source = audioCtx.createMediaStreamSource(mediaStream);
    tapNode = new AudioWorkletNode(audioCtx, "mic-tap", { numberOfInputs: 1, numberOfOutputs: 0 });
    tapNode.port.onmessage = onAudioBlock;
    source.connect(tapNode);
    watchAudioChain();
  }

  // The socket staying open proves nothing about the microphone: a phone
  // call or Siri suspends the context ("interrupted" on iOS), and another app
  // or a headset unplugging ends the track. Without these the bar would say
  // "Recording" while the laptop zero-fills.
  function watchAudioChain() {
    var ctx = audioCtx;
    ctx.onstatechange = function () {
      if (!recording || ctx !== audioCtx || ctx.state === "closed") {
        return;
      }
      if (ctx.state === "running") {
        if (isSocketOpen()) {
          setStatus(RECORDING_MESSAGE, "live");
        }
        return;
      }
      setStatus("Audio paused by the phone (a call or another app?). Tap the page to resume.", "warn");
      ctx.resume().catch(function () {});
    };
    mediaStream.getAudioTracks().forEach(function (track) {
      track.addEventListener("ended", function () {
        if (recording && ctx === audioCtx) {
          stopRecording("The microphone was taken away (another app, or a headset change). Press Start again.", "error");
        }
      });
    });
  }

  // A tap is a user gesture, which is what an interrupted context needs.
  document.addEventListener("pointerdown", function () {
    if (recording && audioCtx !== null && audioCtx.state !== "running") {
      audioCtx.resume().catch(function () {});
    }
  });

  function closeMicrophone() {
    if (tapNode !== null) {
      tapNode.port.onmessage = null;
      tapNode.disconnect();
      tapNode = null;
    }
    if (mediaStream !== null) {
      mediaStream.getTracks().forEach(function (track) { track.stop(); });
      mediaStream = null;
    }
    if (audioCtx !== null) {
      audioCtx.close().catch(function () {});
      audioCtx = null;
    }
    resampler = null;
    batcher = null;
  }

  // --- keeping the phone awake -------------------------------------------

  async function acquireWakeLock() {
    if (!("wakeLock" in navigator) || wakeLock !== null || wakeLockPending) {
      return;
    }
    wakeLockPending = true;
    try {
      var sentinel = await navigator.wakeLock.request("screen");
      // Stop may have been pressed while the request was in flight: a lock
      // granted now would keep the screen on with nothing recording.
      if (!recording) {
        sentinel.release().catch(function () {});
        return;
      }
      wakeLock = sentinel;
      sentinel.addEventListener("release", function () {
        if (wakeLock === sentinel) {
          wakeLock = null;
        }
      });
    } catch (err) {
      // Refused (battery saver, or no user gesture): recording still works,
      // the screen may just lock. The visibility handler below covers that.
    } finally {
      wakeLockPending = false;
    }
  }

  function releaseWakeLock() {
    if (wakeLock !== null) {
      wakeLock.release().catch(function () {});
      wakeLock = null;
    }
  }

  document.addEventListener("visibilitychange", function () {
    if (!recording) {
      return;
    }
    if (document.visibilityState === "hidden") {
      // Most phones pause capture in a hidden tab; the laptop records the
      // gap as silence and flags the input idle.
      return;
    }
    acquireWakeLock();
    if (audioCtx !== null && audioCtx.state !== "running") {
      audioCtx.resume().catch(function () {});
    }
    if (!isSocketOpen()) {
      setStatus("Back on screen. Reconnecting; keep this page open while recording.", "warn");
      connect();
    }
  });

  // Leaving the page (or iOS putting it in the back-forward cache) ends the
  // recording cleanly; a restored page with dead tracks must not claim to record.
  window.addEventListener("pagehide", function () {
    if (recording) {
      stopRecording();
    }
  });

  // --- start / stop ------------------------------------------------------

  async function startRecording() {
    button.disabled = true;
    setStatus("Asking for the microphone...", "info");
    try {
      await openMicrophone();
    } catch (err) {
      closeMicrophone();
      button.disabled = false;
      var denied = err && (err.name === "NotAllowedError" || err.name === "SecurityError");
      setStatus(denied
        ? "Microphone permission denied. Allow it in the browser's site settings and try again."
        : "Could not start the microphone (" + (err && err.name ? err.name : "unknown error") + ").", "error");
      return;
    }
    recording = true;
    droppedFrames = 0;
    lastAliveAt = 0;
    backoff.reset();
    button.textContent = "Stop recording";
    button.disabled = false;
    setStatus("Connecting to the laptop...", "info");
    acquireWakeLock();
    connect();
  }

  function stopRecording(message, kind) {
    recording = false;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (socket !== null) {
      var ws = socket;
      socket = null;
      ws.close(1000);
    }
    closeMicrophone();
    releaseWakeLock();
    setLevel(LEVEL_FLOOR_DBFS);
    button.textContent = "Start recording";
    button.disabled = false;
    setStatus(message || "Stopped.", kind || "info");
  }

  button.addEventListener("click", function () {
    if (recording) {
      stopRecording(droppedFrames > 0 ? "Stopped. Some audio was lost while the connection was down." : "Stopped.");
    } else {
      startRecording();
    }
  });

  setLevel(LEVEL_FLOOR_DBFS);
})();
