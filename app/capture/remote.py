"""The phone's microphone as a capture stream, for in-person meetings.

Audio arrives over a websocket as 16 kHz mono PCM16, in bursts at the
network's pace. Everything downstream assumes the `CaptureStream` contract: a
frame every `frame_ms`, real or zero-filled, so that cumulative audio sent
tracks wall time 1:1 (the engine's clock is audio SENT). So this buffers what the
phone sends and paces it out on the same schedule, and emits synthesized
silence when the phone goes quiet -- which is what lets the existing
supervisor raise `idle` when a screen locks, instead of the transcript just
stopping.

A backlog (say, after the network stalls and then floods) is capped at
`max_backlog_s`; the oldest audio is dropped and counted rather than letting
every later turn arrive later and later.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

from app.capture.devices import DeviceInfo
from app.capture.levels import RecentLevel
from app.capture.stream import CaptureFrame, CaptureHealth

logger = logging.getLogger(__name__)

BYTES_PER_SAMPLE = 2
REMOTE_DEVICE_IDENTITY = "remote:phone-microphone"


class RemoteAudioSource:
    def __init__(
        self,
        *,
        sample_rate: int,
        frame_ms: int,
        queue_max_seconds: float,
        max_backlog_s: float = 2.0,
        label: str = "room",
    ) -> None:
        self._rate = sample_rate
        self._frame_ms = frame_ms
        self._frame_bytes = sample_rate * frame_ms // 1000 * BYTES_PER_SAMPLE
        self._max_backlog_bytes = int(max_backlog_s * sample_rate) * BYTES_PER_SAMPLE
        self._label = label
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._seq = 0
        self._recent_level = RecentLevel()
        self._stop_event = threading.Event()
        self._dead_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.queue: "queue.Queue[CaptureFrame]" = queue.Queue(
            maxsize=max(1, int(queue_max_seconds * 1000 / frame_ms))
        )
        self.health = CaptureHealth()
        self._device = DeviceInfo(
            index=-1,
            name="Phone microphone (in-person)",
            native_sample_rate=sample_rate,
            channels=1,
            is_loopback=False,
            identity=REMOTE_DEVICE_IDENTITY,
        )

    # --- the surface the supervisor, status poller and session metadata read ---

    @property
    def device(self) -> DeviceInfo:
        return self._device

    @property
    def is_dead(self) -> bool:
        return self._dead_event.is_set()

    def mark_dead(self) -> None:
        self._dead_event.set()

    def reopen(self, new_device: Optional[DeviceInfo] = None) -> None:
        """Nothing to reopen: the phone reconnects on its own."""

    def recent_peak_dbfs(self, *, at_s: "Optional[float]" = None) -> "Optional[float]":
        return self._recent_level.peak_dbfs(at_s=time.monotonic() if at_s is None else at_s)

    # --- input: called from the websocket handler ---

    def push(self, pcm16: bytes) -> None:
        with self._lock:
            self._buffer.extend(pcm16)
            excess = len(self._buffer) - self._max_backlog_bytes
            if excess > 0:
                frames = -(-excess // self._frame_bytes)
                cut = min(frames * self._frame_bytes, len(self._buffer))
                del self._buffer[:cut]
                self.health.dropped_frame_count += frames
                logger.warning(
                    "phone audio backlog over cap, dropped %d frame(s) total_dropped=%d",
                    frames, self.health.dropped_frame_count,
                )

    def buffered_seconds(self) -> float:
        with self._lock:
            return len(self._buffer) / BYTES_PER_SAMPLE / self._rate

    # --- the pacer ---

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name=f"remote-{self._label}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run(self) -> None:
        period_s = self._frame_ms / 1000.0
        next_deadline = time.monotonic() + period_s
        while not self._stop_event.is_set() and not self._dead_event.is_set():
            sleep_s = next_deadline - time.monotonic()
            if sleep_s > 0:
                time.sleep(sleep_s)
            else:
                next_deadline = time.monotonic()
            self._emit_one_frame()
            next_deadline += period_s

    def _emit_one_frame(self) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._buffer) >= self._frame_bytes:
                pcm16 = bytes(self._buffer[: self._frame_bytes])
                del self._buffer[: self._frame_bytes]
            else:
                pcm16 = None
        if pcm16 is not None:
            kind = "real"
            self.health.last_real_audio_monotonic = now
            self.health.consecutive_synthesized_frames = 0
            self._recent_level.push(pcm16, at_s=now)
        else:
            pcm16 = b"\x00" * self._frame_bytes
            kind = "synthesized"
            self.health.consecutive_synthesized_frames += 1
        frame = CaptureFrame(seq=self._seq, pcm16=pcm16, kind=kind, captured_monotonic=now)
        self._seq += 1
        try:
            self.queue.put_nowait(frame)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            self.health.dropped_frame_count += 1
            self.queue.put_nowait(frame)
        self.health.queue_depth = self.queue.qsize()
