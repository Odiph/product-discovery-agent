"""The after-meeting evidence pass of an in-person session.

The transcriber and the voiceprint model are injected, so this runs with no
network and no model. The room recording is synthetic and SPEAKER-CODED: each
voice is a constant sample value, and the fake embedder reads that value back,
so "the voiceprint disagrees with the diarization label" can be staged exactly.
"""

from __future__ import annotations

import json
import wave

import numpy as np
import pytest

from app.session import evidence as ev
from app.stt import evidence_pass as ep

RATE = 16000
VOICE_A = 1000  # the interviewer's samples in the synthetic room
VOICE_B = 3000


class CodedEmbedder:
    """Maps a span of the synthetic room to the voice that is in it."""

    def embed(self, pcm16, sample_rate):
        level = float(np.abs(np.frombuffer(pcm16, dtype="<i2")).mean())
        return np.array([1.0, 0.0]) if level < 2000 else np.array([0.0, 1.0])


def _room(path, spans, seconds):
    samples = np.zeros(int(seconds * RATE), dtype="<i2")
    for start, end, value in spans:
        samples[int(start * RATE):int(end * RATE)] = value
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(samples.tobytes())


def _token(text, start, end, speaker):
    return {"text": text, "start_ms": int(start * 1000), "end_ms": int(end * 1000), "speaker": speaker, "language": "en"}


# Who really spoke when (VOICE_A = interviewer): opens with the consent line,
# both voices heard inside the 4 s enrolment window, then three later turns.
SPANS = [(0.0, 2.0, VOICE_A), (2.5, 4.0, VOICE_B), (5.0, 7.0, VOICE_A), (8.0, 10.0, VOICE_B), (11.0, 13.0, VOICE_B)]
TOKENS = [
    _token("Do I have your consent?", 0.0, 2.0, "1"),
    _token(" Yes.", 2.5, 4.0, "2"),
    _token(" What do you use today?", 5.0, 7.0, "1"),
    _token(" Spreadsheets.", 8.0, 10.0, "2"),
    # The diarization got this one wrong: it is VOICE_B, labelled "1".
    _token(" And email.", 11.0, 13.0, "1"),
]


@pytest.fixture
def session(tmp_path):
    (tmp_path / "session.json").write_text(json.dumps({
        "capture": "in-person", "speaker_source": "diarization-live",
        ev.EVIDENCE_KEY: ev.EVIDENCE_PENDING, "closed_at": "2026-10-20T10:00:00+00:00",
    }), encoding="utf-8")
    _room(tmp_path / ev.ROOM_AUDIO_FILENAME, SPANS, 14)
    return tmp_path


def _run(session, tokens=TOKENS, embedder=None, **kw):
    return ep.run_evidence_pass(
        session, transcribe=lambda path: list(tokens), embedder=embedder or CodedEmbedder(),
        engine="fake-async", enrol_s=4.0, **kw,
    )


def _evidence(session):
    return [json.loads(l) for l in (session / ev.EVIDENCE_TRANSCRIPT_FILENAME).read_text(encoding="utf-8").splitlines()]


def _meta(session):
    return json.loads((session / "session.json").read_text(encoding="utf-8"))


def test_turns_get_roles_from_the_after_meeting_labels_first_voice_interviewer(session):
    _run(session)
    turns = _evidence(session)
    assert [t["text"] for t in turns] == [
        "Do I have your consent?", "Yes.", "What do you use today?", "Spreadsheets.", "And email.",
    ]
    assert [t["speaker"] for t in turns] == ["interviewer", "interviewee", "interviewer", "interviewee", "interviewer"]
    assert [t["seq"] for t in turns] == [1, 2, 3, 4, 5]
    assert all(t["kind"] == "segment" and t["engine"] == "fake-async" for t in turns)
    assert turns[0]["audio_end_s"] == 2.0 and turns[0]["speaker_label"] == "1"


def test_a_turn_the_voiceprint_disputes_is_flagged_not_silently_reassigned(session):
    _run(session)
    turns = _evidence(session)
    # Evidence keeps the after-meeting label's role; the operator settles it.
    assert turns[4]["speaker"] == "interviewer" and turns[4]["disputed"] is True
    assert [t["disputed"] for t in turns[:4]] == [False, False, False, False]
    summary = _meta(session)["evidence_summary"]
    assert summary["turns"] == 5 and summary["disputed"] == 1
    assert summary["labels"] == {"1": 3, "2": 2}


def test_the_session_moves_to_transcribed_and_keeps_the_room_audio(session):
    _run(session)
    assert _meta(session)[ev.EVIDENCE_KEY] == ev.EVIDENCE_TRANSCRIBED
    # Deleted only on confirmation: the operator may still need to rerun.
    assert (session / ev.ROOM_AUDIO_FILENAME).exists()


def test_without_a_voiceprint_model_nothing_is_disputed_and_the_summary_says_so(session):
    ep.run_evidence_pass(session, transcribe=lambda p: list(TOKENS), embedder=None, engine="fake-async", enrol_s=4.0)
    assert not any(t["disputed"] for t in _evidence(session))
    assert _meta(session)["evidence_summary"]["voiceprint"] is False


def test_a_failed_transcription_changes_nothing(session):
    def boom(path):
        raise RuntimeError("vendor down")

    with pytest.raises(RuntimeError):
        ep.run_evidence_pass(session, transcribe=boom, embedder=None, engine="x", enrol_s=4.0)
    assert _meta(session)[ev.EVIDENCE_KEY] == ev.EVIDENCE_PENDING
    assert not (session / ev.EVIDENCE_TRANSCRIPT_FILENAME).exists()


def test_a_transcribed_session_can_be_rerun(session):
    _run(session)
    _run(session, tokens=TOKENS[:2])
    assert len(_evidence(session)) == 2


@pytest.mark.parametrize("patch,reason", [
    ({"capture": None}, "not an in-person"),
    ({ev.EVIDENCE_KEY: ev.EVIDENCE_CONFIRMED}, "already confirmed"),
    ({"closed_at": None}, "still recording"),
])
def test_it_refuses_sessions_it_cannot_or_must_not_redo(session, patch, reason):
    meta = {k: v for k, v in {**_meta(session), **patch}.items() if v is not None}
    (session / "session.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ep.EvidencePassError, match=reason):
        _run(session)


def test_it_refuses_when_the_room_audio_is_gone(session):
    (session / ev.ROOM_AUDIO_FILENAME).unlink()
    with pytest.raises(ep.EvidencePassError, match="no room audio"):
        _run(session)


@pytest.mark.parametrize("tokens,reason", [
    ([], "no speech"),
    ([{**t, "speaker": None} for t in TOKENS], "no speaker labels"),
], ids=["empty", "unlabelled"])
def test_a_pass_that_cannot_be_evidence_writes_nothing(session, tokens, reason):
    with pytest.raises(ep.EvidencePassError, match=reason):
        _run(session, tokens=tokens)
    assert _meta(session)[ev.EVIDENCE_KEY] == ev.EVIDENCE_PENDING
    assert not (session / ev.EVIDENCE_TRANSCRIPT_FILENAME).exists()


def test_the_pass_role_is_kept_apart_and_coverage_is_reported(session):
    _run(session)
    assert [t["pass_speaker"] for t in _evidence(session)] == [t["speaker"] for t in _evidence(session)]
    # The last turn ends at 13 s of a 14 s room.
    assert _meta(session)["evidence_summary"]["coverage"] == pytest.approx(13 / 14, abs=0.001)


def test_a_room_file_in_the_wrong_format_fails_before_anything_is_uploaded(session):
    with wave.open(str(session / ev.ROOM_AUDIO_FILENAME), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(b"\x00" * 4000)
    uploads = []
    with pytest.raises(ep.EvidencePassError, match="16 kHz mono"):
        ep.run_evidence_pass(session, transcribe=uploads.append, embedder=None, engine="x", enrol_s=4.0)
    assert uploads == []
