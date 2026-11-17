"""Which of the two people in the room said a diarized turn.

In a one-microphone meeting the engine tags each turn with a speaker id ("1",
"2", ...) that says nothing about who the voice is, and it drifts: measured on
a real in-person meeting, the live labels were right for 86% of words, with
occasional swaps. Two rules turn labels into roles:

1. **The first voice heard is the interviewer.** The operator opens with the
   consent line, so this holds by procedure, not by guess.
2. **After the opening `enrol_s` seconds, a voiceprint decides.** Both voices
   are enrolled from the opening turns (labelled by rule 1); each later turn
   of at least `min_turn_s` goes to the nearer voiceprint. On the same meeting
   that raised word-level agreement from 86% to 96%.

Everything degrades to the engine labels rather than failing: no model, a
turn too short to embed, a voice not heard during enrolment, or a model error.
Live roles drive COACHING only; evidence comes from the after-meeting pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import numpy as np

from benchmark.engines.base import Segment

logger = logging.getLogger(__name__)

INTERVIEWER = "interviewer"
INTERVIEWEE = "interviewee"
METHOD_DIARIZATION = "diarization"
METHOD_VOICEPRINT = "voiceprint"
SAMPLE_RATE = 16000


class Embedder(Protocol):
    def embed(self, pcm16: bytes, sample_rate: int) -> "np.ndarray": ...


@dataclass(frozen=True)
class Resolution:
    role: str
    method: str
    # True when the voiceprint picked the opposite role from the engine label:
    # the swaps this module exists to catch. Counted, never shown as content.
    overruled: bool = False


def _unit(vector) -> "np.ndarray":
    v = np.asarray(vector, dtype=np.float64)
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


class RoleResolver:
    def __init__(self, *, embedder: Optional[Embedder], enrol_s: float, min_turn_s: float) -> None:
        self._embedder = embedder
        self._enrol_s = enrol_s
        self._min_turn_s = min_turn_s
        self._first_label: Optional[str] = None
        self._enrolment: "dict[str, list[np.ndarray]]" = {INTERVIEWER: [], INTERVIEWEE: []}

    def label_role(self, label: Optional[str]) -> str:
        if self._first_label is None:
            self._first_label = label
        return INTERVIEWER if label == self._first_label else INTERVIEWEE

    def resolve(self, segment: Segment, pcm16: bytes) -> Resolution:
        by_label = self.label_role(segment.speaker_label)
        start = segment.speech_start_s if segment.speech_start_s is not None else segment.audio_end_s
        long_enough = segment.audio_end_s - start >= self._min_turn_s
        if self._embedder is None or not long_enough:
            return Resolution(by_label, METHOD_DIARIZATION)

        embedding = self._embed(pcm16)
        if embedding is None:
            return Resolution(by_label, METHOD_DIARIZATION)
        if segment.audio_end_s <= self._enrol_s:
            self._enrolment[by_label].append(embedding)
            return Resolution(by_label, METHOD_DIARIZATION)
        if not all(self._enrolment.values()):
            return Resolution(by_label, METHOD_DIARIZATION)

        centroids = {role: _unit(np.mean(v, axis=0)) for role, v in self._enrolment.items()}
        role = max(centroids, key=lambda r: float(embedding @ centroids[r]))
        return Resolution(role, METHOD_VOICEPRINT, overruled=role != by_label)

    def _embed(self, pcm16: bytes) -> "Optional[np.ndarray]":
        try:
            return _unit(self._embedder.embed(pcm16, SAMPLE_RATE))
        except Exception as exc:  # noqa: BLE001 -- a model failure must never stop a meeting
            logger.warning("voiceprint embedding failed (%s); using the engine label", type(exc).__name__)
            return None
