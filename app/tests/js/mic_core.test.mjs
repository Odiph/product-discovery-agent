// app/tests/js/mic_core.test.mjs -- node's built-in runner, no dependencies.
// `mic-core.mjs` is the pure half of the phone's microphone page: resampling
// the browser's native rate (48 kHz on most phones, 44.1 kHz on some) down to
// the 16 kHz the laptop expects, converting to 16-bit PCM, and cutting 100 ms
// frames. The browser glue (mic.js) is thin on purpose so this can be tested.

import test from "node:test";
import assert from "node:assert/strict";

import {
  TARGET_RATE,
  FRAME_SAMPLES,
  Resampler16k,
  floatToPcm16,
  rmsDbfs,
  FrameBatcher,
} from "../../static/mic-core.mjs";

const sine = (rate, seconds, hz, amp = 0.5) =>
  Float32Array.from({ length: Math.round(rate * seconds) }, (_, i) => amp * Math.sin((2 * Math.PI * hz * i) / rate));

test("the laptop's contract: 16 kHz and 100 ms frames", () => {
  assert.equal(TARGET_RATE, 16000);
  assert.equal(FRAME_SAMPLES, 1600);
});

for (const rate of [48000, 44100, 16000]) {
  test(`one second at ${rate} Hz becomes one second at 16 kHz, however it is chunked`, () => {
    const r = new Resampler16k(rate);
    const input = sine(rate, 1, 440);
    let total = 0;
    for (let i = 0; i < input.length; i += 128) total += r.push(input.subarray(i, i + 128)).length;
    assert.ok(Math.abs(total - 16000) <= 1, `got ${total}`);
  });
}

test("chunking does not change the output: no drift, no seam", () => {
  const input = sine(48000, 0.5, 300);
  const whole = new Resampler16k(48000).push(input);
  const r = new Resampler16k(48000);
  const parts = [];
  for (let i = 0; i < input.length; i += 441) parts.push(...r.push(input.subarray(i, i + 441)));
  assert.equal(parts.length, whole.length);
  for (let i = 0; i < whole.length; i++) assert.ok(Math.abs(parts[i] - whole[i]) < 1e-6);
});

test("a 440 Hz tone survives the resample at its own frequency", () => {
  const out = new Resampler16k(48000).push(sine(48000, 1, 440));
  let crossings = 0;
  for (let i = 1; i < out.length; i++) if (out[i - 1] < 0 && out[i] >= 0) crossings++;
  assert.ok(Math.abs(crossings - 440) <= 2, `crossings ${crossings}`);
});

test("float samples become clipped 16-bit integers", () => {
  const pcm = floatToPcm16(Float32Array.from([0, 0.5, -0.5, 1.5, -1.5]));
  assert.deepEqual(Array.from(pcm), [0, 16383, -16384, 32767, -32768]);
});

test("the level meter reads full scale as 0 dBFS and silence as -Infinity", () => {
  assert.ok(Math.abs(rmsDbfs(Float32Array.from([1, -1, 1, -1]))) < 1e-9);
  assert.equal(rmsDbfs(new Float32Array(10)), -Infinity);
});

test("the batcher emits whole 100 ms frames as 16-bit little-endian bytes and keeps the remainder", () => {
  const b = new FrameBatcher(FRAME_SAMPLES);
  assert.equal(b.push(new Int16Array(1000)).length, 0);
  const frames = b.push(Int16Array.from({ length: 2300 }, (_, i) => i));
  assert.equal(frames.length, 2);
  assert.ok(frames.every((f) => f.byteLength === FRAME_SAMPLES * 2));
  const view = new DataView(frames[0]);
  assert.equal(view.getInt16(1000 * 2, true), 0);
  assert.equal(view.getInt16(1001 * 2, true), 1);
  assert.equal(b.pending, 3300 - 3200);
});
