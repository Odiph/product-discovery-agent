// The pure half of the phone's microphone page (in-person mode): everything
// that can be tested without a browser. `mic.js` is the thin glue around it.
//
// The laptop expects 16 kHz mono 16-bit little-endian PCM in 100 ms frames
// (app/capture/remote.py). Phones capture at 48 kHz (sometimes 44.1 kHz) and
// hand the page Float32 blocks of whatever size the browser likes.

export const TARGET_RATE = 16000;
export const FRAME_SAMPLES = 1600; // 100 ms at 16 kHz

// Downsamples by averaging each output sample's window of input samples: a
// box filter, which is a crude but adequate anti-alias for speech. The window
// edges come from an ABSOLUTE position in the input stream, so the output is
// identical however the browser happens to chunk the input -- no drift, and no
// seam at a chunk boundary.
export class Resampler16k {
  constructor(inputRate) {
    this.ratio = inputRate / TARGET_RATE;
    this.pos = 0; // absolute input position where the next output window starts
    this.carry = new Float32Array(0);
    this.carryStart = 0; // absolute input index of carry[0]
  }

  push(chunk) {
    const buf = new Float32Array(this.carry.length + chunk.length);
    buf.set(this.carry, 0);
    buf.set(chunk, this.carry.length);
    const base = this.carryStart;
    const out = [];
    while (this.pos + this.ratio <= base + buf.length) {
      const lo = Math.floor(this.pos) - base;
      const hi = Math.max(lo + 1, Math.floor(this.pos + this.ratio) - base);
      let sum = 0;
      for (let i = lo; i < hi; i++) sum += buf[i];
      out.push(sum / (hi - lo));
      this.pos += this.ratio;
    }
    const keepFrom = Math.min(Math.floor(this.pos) - base, buf.length);
    this.carry = buf.slice(keepFrom);
    this.carryStart = base + keepFrom;
    return Float32Array.from(out);
  }
}

export function floatToPcm16(samples) {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    // The usual Web Audio conversion: scale, and let Int16Array truncate.
    out[i] = s < 0 ? s * 32768 : s * 32767;
  }
  return out;
}

export function rmsDbfs(samples) {
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  const rms = Math.sqrt(sum / Math.max(1, samples.length));
  return rms > 0 ? 20 * Math.log10(rms) : -Infinity;
}

// Accumulates 16-bit samples and hands back whole frames as ArrayBuffers of
// little-endian bytes, ready to send as one binary WebSocket message each.
export class FrameBatcher {
  constructor(frameSamples) {
    this.frameSamples = frameSamples;
    this.buffer = new Int16Array(0);
  }

  get pending() {
    return this.buffer.length;
  }

  push(pcm) {
    const joined = new Int16Array(this.buffer.length + pcm.length);
    joined.set(this.buffer, 0);
    joined.set(pcm, this.buffer.length);
    const frames = [];
    let at = 0;
    while (joined.length - at >= this.frameSamples) {
      const bytes = new ArrayBuffer(this.frameSamples * 2);
      const view = new DataView(bytes);
      for (let i = 0; i < this.frameSamples; i++) view.setInt16(i * 2, joined[at + i], true);
      frames.push(bytes);
      at += this.frameSamples;
    }
    this.buffer = joined.slice(at);
    return frames;
  }
}
