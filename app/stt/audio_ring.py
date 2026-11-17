"""The last `max_s` seconds of audio sent to the engine, addressable by time.

Indexed by samples SENT since the first frame -- the same origin as the
engine's token timestamps -- so a turn the engine finalizes seconds later can
still be cut out for the voiceprint check. Zero-filled frames count: dropping
them would shift every later turn off its audio.
"""

from __future__ import annotations

import threading

BYTES_PER_SAMPLE = 2  # 16-bit mono PCM


class AudioRing:
    def __init__(self, *, sample_rate: int, max_s: float) -> None:
        self._rate = sample_rate
        self._max_bytes = int(max_s * sample_rate) * BYTES_PER_SAMPLE
        self._buffer = bytearray()
        self._origin_bytes = 0  # absolute byte offset of self._buffer[0]
        self._lock = threading.Lock()

    def append(self, pcm16: bytes) -> None:
        with self._lock:
            self._buffer.extend(pcm16)
            excess = len(self._buffer) - self._max_bytes
            if excess > 0:
                excess -= excess % BYTES_PER_SAMPLE
                del self._buffer[:excess]
                self._origin_bytes += excess

    def slice(self, start_s: float, end_s: float) -> bytes:
        with self._lock:
            lo = int(start_s * self._rate) * BYTES_PER_SAMPLE - self._origin_bytes
            hi = int(end_s * self._rate) * BYTES_PER_SAMPLE - self._origin_bytes
            lo, hi = max(lo, 0), min(hi, len(self._buffer))
            return bytes(self._buffer[lo:hi]) if hi > lo else b""
