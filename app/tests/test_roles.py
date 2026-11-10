"""`RoleResolver`: which of the two people in the room said this turn.

The engine's diarization labels ("1", "2") say nothing about WHO a voice is,
and on a real one-microphone meeting they were right for 86% of words. A
voiceprint check -- enrol both voices from the opening minutes, then give each
later turn to the nearer voiceprint -- raised that to 96%. These tests pin the
rules; the embedding model is a stub, so they say nothing about its accuracy
(that is measured, not asserted, and lives with the measurement).
"""

from __future__ import annotations

import numpy as np

from app.stt.roles import INTERVIEWEE, INTERVIEWER, METHOD_DIARIZATION, METHOD_VOICEPRINT, RoleResolver
from benchmark.engines.base import Segment

VOICE = {"me": np.array([1.0, 0.0]), "them": np.array([0.0, 1.0])}


class StubEmbedder:
    """Embeds a byte string naming its voice: b"me" or b"them"."""

    def __init__(self):
        self.calls = 0

    def embed(self, pcm16: bytes, sample_rate: int):
        self.calls += 1
        return VOICE[pcm16.decode()]


def turn(label, start, end):
    return Segment(text="x", audio_end_s=end, ready_wall_s=end, speaker_label=label, speech_start_s=start)


def test_the_first_voice_heard_is_the_interviewer_and_the_other_is_the_interviewee():
    r = RoleResolver(embedder=None, enrol_s=120.0, min_turn_s=1.0)
    assert r.resolve(turn("2", 0, 3), b"me").role == INTERVIEWER
    assert r.resolve(turn("1", 3, 6), b"them").role == INTERVIEWEE
    assert r.resolve(turn("2", 6, 9), b"me").role == INTERVIEWER


def test_a_third_engine_label_is_treated_as_the_interviewee_not_as_you():
    r = RoleResolver(embedder=None, enrol_s=120.0, min_turn_s=1.0)
    r.resolve(turn("1", 0, 3), b"me")
    assert r.resolve(turn("3", 3, 6), b"them").role == INTERVIEWEE


def test_without_a_voiceprint_model_the_engine_labels_decide():
    r = RoleResolver(embedder=None, enrol_s=10.0, min_turn_s=1.0)
    r.resolve(turn("1", 0, 3), b"me")
    got = r.resolve(turn("1", 200, 203), b"them")
    assert (got.role, got.method) == (INTERVIEWER, METHOD_DIARIZATION)


def enrolled(embedder, enrol_s=10.0):
    r = RoleResolver(embedder=embedder, enrol_s=enrol_s, min_turn_s=1.0)
    r.resolve(turn("1", 0, 3), b"me")
    r.resolve(turn("2", 3, 6), b"them")
    return r


def test_after_enrolment_the_voiceprint_overrules_a_swapped_engine_label():
    r = enrolled(StubEmbedder())
    # The engine swapped its labels: "1" now carries THEIR voice.
    got = r.resolve(turn("1", 20, 24), b"them")
    assert (got.role, got.method, got.overruled) == (INTERVIEWEE, METHOD_VOICEPRINT, True)


def test_after_enrolment_an_agreeing_voiceprint_is_not_an_overrule():
    r = enrolled(StubEmbedder())
    got = r.resolve(turn("1", 20, 24), b"me")
    assert (got.role, got.method, got.overruled) == (INTERVIEWER, METHOD_VOICEPRINT, False)


def test_a_turn_too_short_to_embed_keeps_the_engine_label_and_costs_no_embedding():
    emb = StubEmbedder()
    r = enrolled(emb)
    before = emb.calls
    got = r.resolve(turn("1", 20, 20.5), b"them")
    assert (got.role, got.method) == (INTERVIEWER, METHOD_DIARIZATION)
    assert emb.calls == before


def test_during_enrolment_the_engine_label_decides_even_with_a_model():
    r = RoleResolver(embedder=StubEmbedder(), enrol_s=120.0, min_turn_s=1.0)
    r.resolve(turn("1", 0, 3), b"me")
    got = r.resolve(turn("1", 5, 9), b"them")
    assert (got.role, got.method) == (INTERVIEWER, METHOD_DIARIZATION)


def test_a_voice_never_enrolled_falls_back_to_the_engine_label():
    # Only one person spoke in the opening minutes: there is no second
    # voiceprint to compare against, so nearest-voiceprint would always pick
    # the only one. The engine label must decide instead.
    r = RoleResolver(embedder=StubEmbedder(), enrol_s=10.0, min_turn_s=1.0)
    r.resolve(turn("1", 0, 3), b"me")
    got = r.resolve(turn("2", 20, 24), b"them")
    assert (got.role, got.method) == (INTERVIEWEE, METHOD_DIARIZATION)


def test_an_embedder_that_fails_degrades_to_the_engine_label_instead_of_raising():
    class Broken:
        def embed(self, pcm16, sample_rate):
            raise RuntimeError("model crashed")

    r = enrolled(StubEmbedder())
    r._embedder = Broken()
    got = r.resolve(turn("2", 20, 24), b"me")
    assert (got.role, got.method) == (INTERVIEWEE, METHOD_DIARIZATION)
