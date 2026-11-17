"""A diarized stand-in engine for in-person mode: no network, no model.

Emits one turn per `cadence_bytes` of audio received, alternating the engine
speaker ids "1" and "2", each turn carrying its real start on the audio clock.
What `start --in-person --engine fake` runs, so the whole phone -> laptop ->
transcript path can be exercised without a vendor.
"""

from __future__ import annotations

import time

from benchmark.engines.base import Segment

DEFAULT_CADENCE_BYTES = 32000  # one turn per second of 16 kHz mono PCM16


class FakeDiarizedSession:
    def __init__(self, *, cadence_bytes: int, sample_rate: int) -> None:
        self._cadence = cadence_bytes
        self._rate = sample_rate
        self._received = 0
        self._emitted = 0
        self._turn = 0
        self._start = time.monotonic()
        self._pending: "list[Segment]" = []
        self._closed = False

    def send_audio(self, pcm16: bytes) -> None:
        if self._closed or not pcm16:
            return
        self._received += len(pcm16)
        while self._received - self._emitted >= self._cadence:
            start_s = self._emitted / 2 / self._rate
            self._emitted += self._cadence
            label = "1" if self._turn % 2 == 0 else "2"
            self._turn += 1
            self._pending.append(Segment(
                text=f"diarized turn {self._turn}",
                audio_end_s=self._emitted / 2 / self._rate,
                ready_wall_s=time.monotonic() - self._start,
                detected_language="en",
                speaker_label=label,
                speech_start_s=start_s,
            ))

    def poll(self, timeout_s: float = 0.0) -> "tuple[Segment, ...]":
        out, self._pending = tuple(self._pending), []
        return out

    def close(self) -> "tuple[Segment, ...]":
        self._closed = True
        return self.poll()


class FakeDiarizedEngine:
    name = "fake-in-person"

    def __init__(self, *, cadence_bytes: int = DEFAULT_CADENCE_BYTES) -> None:
        self._cadence = cadence_bytes

    def open_session(self, *, sample_rate: int, label: str = "") -> FakeDiarizedSession:
        return FakeDiarizedSession(cadence_bytes=self._cadence, sample_rate=sample_rate)
