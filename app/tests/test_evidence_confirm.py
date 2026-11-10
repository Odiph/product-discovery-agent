"""Confirming who is who in an in-person session, and the gate `extract` puts
on it.

Confirmation is the operator's act, so it is explicit: a swap is a flag, and a
session with disputed turns cannot be confirmed until the operator says which
side wins. Confirming deletes the room audio -- the reason it was kept is gone.
"""

from __future__ import annotations

import json

import pytest

from app.session import evidence as ev
from app.session.reader import read_session


def _turn(seq, speaker, label, text, disputed=False):
    return {
        "kind": "segment", "seq": seq, "speaker": speaker, "text": text,
        "audio_start_s": float(seq), "audio_end_s": seq + 0.9, "ready_wall_s": seq + 0.9,
        "latency_s": 0.0, "detected_language": "en", "engine": "fake-async",
        "written_at": "2026-10-20T10:00:00.000+00:00", "speaker_label": label, "disputed": disputed,
    }


TURNS = [
    _turn(1, "interviewer", "1", "Do I have your consent?"),
    _turn(2, "interviewee", "2", "Yes."),
    _turn(3, "interviewer", "1", "And email.", disputed=True),
]


@pytest.fixture
def session(tmp_path):
    meta = {"capture": "in-person", ev.EVIDENCE_KEY: ev.EVIDENCE_TRANSCRIBED, "closed_at": "x",
            "evidence_summary": {"turns": 3, "disputed": 1}}
    (tmp_path / "session.json").write_text(json.dumps(meta), encoding="utf-8")
    (tmp_path / ev.EVIDENCE_TRANSCRIPT_FILENAME).write_text(
        "".join(json.dumps(t) + "\n" for t in TURNS), encoding="utf-8")
    (tmp_path / ev.ROOM_AUDIO_FILENAME).write_bytes(b"RIFF")
    (tmp_path / "transcript.jsonl").write_text(
        json.dumps({**TURNS[0], "speaker": "interviewee"}) + "\n", encoding="utf-8")
    return tmp_path


def _meta(session):
    return json.loads((session / "session.json").read_text(encoding="utf-8"))


def _speakers(session):
    return [json.loads(l)["speaker"] for l in (session / ev.EVIDENCE_TRANSCRIPT_FILENAME).read_text(encoding="utf-8").splitlines()]


# --- the preview -----------------------------------------------------------------

def test_the_preview_shows_each_role_and_every_disputed_turn(session):
    preview = ev.speaker_preview(session, per_role=5)
    assert [t["text"] for t in preview["interviewer"]] == ["Do I have your consent?"]
    assert [t["text"] for t in preview["interviewee"]] == ["Yes."]
    assert [t["seq"] for t in preview["disputed"]] == [3]


# --- confirmation ----------------------------------------------------------------

def test_disputed_turns_block_confirmation_until_the_operator_chooses(session):
    with pytest.raises(ev.EvidenceStateError, match="1 disputed"):
        ev.confirm_speakers(session, swap=False, disputed=None)
    assert _meta(session)[ev.EVIDENCE_KEY] == ev.EVIDENCE_TRANSCRIBED
    assert (session / ev.ROOM_AUDIO_FILENAME).exists()


def test_keeping_the_label_side_confirms_as_transcribed_and_deletes_the_audio(session):
    ev.confirm_speakers(session, swap=False, disputed=ev.DISPUTED_KEEP_LABEL)
    assert _speakers(session) == ["interviewer", "interviewee", "interviewer"]
    meta = _meta(session)
    assert meta[ev.EVIDENCE_KEY] == ev.EVIDENCE_CONFIRMED and meta["speakers_confirmed_at"]
    assert meta["audio_retained"] is False
    assert not (session / ev.ROOM_AUDIO_FILENAME).exists()


def test_siding_with_the_voiceprint_flips_only_the_disputed_turns(session):
    ev.confirm_speakers(session, swap=False, disputed=ev.DISPUTED_VOICEPRINT)
    assert _speakers(session) == ["interviewer", "interviewee", "interviewee"]


def test_a_swap_exchanges_every_role_when_the_first_voice_was_not_the_operator(session):
    ev.confirm_speakers(session, swap=True, disputed=ev.DISPUTED_KEEP_LABEL)
    assert _speakers(session) == ["interviewee", "interviewer", "interviewee"]
    assert _meta(session)["speakers_confirmed"] == {"swapped": True, "disputed": "label", "disputed_turns": 1}


def test_confirmation_needs_a_transcribed_session(session):
    meta = {**_meta(session), ev.EVIDENCE_KEY: ev.EVIDENCE_PENDING}
    (session / "session.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ev.EvidenceStateError, match="diarize-after"):
        ev.confirm_speakers(session, swap=False, disputed=ev.DISPUTED_KEEP_LABEL)


def test_confirming_twice_is_refused(session):
    ev.confirm_speakers(session, swap=False, disputed=ev.DISPUTED_KEEP_LABEL)
    with pytest.raises(ev.EvidenceStateError, match="already confirmed"):
        ev.confirm_speakers(session, swap=True, disputed=ev.DISPUTED_KEEP_LABEL)


# --- the extract gate ------------------------------------------------------------

@pytest.mark.parametrize("state", [ev.EVIDENCE_PENDING, ev.EVIDENCE_TRANSCRIBED, None])
def test_extract_is_refused_for_an_unconfirmed_in_person_session(state):
    meta = {"capture": "in-person", **({ev.EVIDENCE_KEY: state} if state else {})}
    reason = ev.extract_refusal(meta)
    assert reason and "confirm-speakers" in reason


def test_extract_is_allowed_for_a_confirmed_or_a_two_stream_session():
    assert ev.extract_refusal({"capture": "in-person", ev.EVIDENCE_KEY: ev.EVIDENCE_CONFIRMED}) is None
    assert ev.extract_refusal({}) is None


def test_a_confirmed_in_person_session_is_read_from_the_evidence_transcript(session):
    ev.confirm_speakers(session, swap=False, disputed=ev.DISPUTED_KEEP_LABEL)
    name = ev.transcript_filename_for(_meta(session))
    assert name == ev.EVIDENCE_TRANSCRIPT_FILENAME
    segments = ev.segment_fields(read_session(session, transcript_filename=name).records_of_kind("segment"))
    # The live transcript (which said "interviewee" for seq 1) is NOT what is read.
    assert [s["speaker"] for s in segments] == ["interviewer", "interviewee", "interviewer"]
    assert "disputed" not in segments[0] and "speaker_label" not in segments[0]


def test_a_two_stream_session_still_reads_the_live_transcript():
    assert ev.transcript_filename_for({}) == "transcript.jsonl"


# --- crash safety, the escape hatch, and the citation reader (review 2026-10-20) ---

def test_a_rerun_after_a_crash_before_the_state_write_never_swaps_twice(session):
    # Pass roles live in `pass_speaker`; simulate the crash window by keeping
    # the swapped file but rolling the state back to `transcribed`.
    turns = [{**t, "pass_speaker": t["speaker"]} for t in TURNS]
    (session / ev.EVIDENCE_TRANSCRIPT_FILENAME).write_text("".join(json.dumps(t) + "\n" for t in turns), encoding="utf-8")
    ev.confirm_speakers(session, swap=True, disputed=ev.DISPUTED_KEEP_LABEL)
    (session / "session.json").write_text(json.dumps({**_meta(session), ev.EVIDENCE_KEY: ev.EVIDENCE_TRANSCRIBED}), encoding="utf-8")
    ev.confirm_speakers(session, swap=True, disputed=ev.DISPUTED_KEEP_LABEL)
    assert _speakers(session) == ["interviewee", "interviewer", "interviewee"]


def test_a_crash_before_the_delete_is_finished_by_running_confirm_again(session):
    (session / "session.json").write_text(json.dumps({**_meta(session), ev.EVIDENCE_KEY: ev.EVIDENCE_CONFIRMED}), encoding="utf-8")
    decision = ev.confirm_speakers(session, swap=False, disputed=None)
    assert decision["finished_cleanup"] is True
    assert not (session / ev.ROOM_AUDIO_FILENAME).exists() and _meta(session)["audio_retained"] is False


def test_an_empty_after_meeting_transcript_cannot_be_confirmed_and_keeps_the_audio(session):
    (session / ev.EVIDENCE_TRANSCRIPT_FILENAME).write_text("", encoding="utf-8")
    with pytest.raises(ev.EvidenceStateError, match="empty"):
        ev.confirm_speakers(session, swap=False, disputed=ev.DISPUTED_KEEP_LABEL)
    assert (session / ev.ROOM_AUDIO_FILENAME).exists()


def test_accepting_live_roles_unlocks_extract_on_the_live_transcript(tmp_path):
    (tmp_path / "session.json").write_text(json.dumps({"capture": "in-person"}), encoding="utf-8")
    ev.accept_live_roles(tmp_path)
    meta = _meta(tmp_path)
    assert ev.extract_refusal(meta) is None
    assert ev.transcript_filename_for(meta) == "transcript.jsonl"


def test_accepting_live_roles_deletes_any_room_audio(session):
    ev.accept_live_roles(session)
    assert not (session / ev.ROOM_AUDIO_FILENAME).exists()


def test_accepting_live_roles_is_refused_for_a_two_stream_session(tmp_path):
    (tmp_path / "session.json").write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(ev.EvidenceStateError, match="not an in-person"):
        ev.accept_live_roles(tmp_path)


def test_a_corrupt_session_json_is_a_named_error(tmp_path):
    (tmp_path / "session.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ev.EvidenceStateError, match="not valid JSON"):
        ev.read_meta(tmp_path)


def test_fact_citations_are_checked_against_the_evidence_roles_once_confirmed(session):
    from app.coach import corpus

    ev.confirm_speakers(session, swap=False, disputed=ev.DISPUTED_KEEP_LABEL)
    speakers = corpus._real_segment_speakers(session.parent, session.name)
    # The live transcript says seq 1 is the interviewee; the evidence says not.
    assert speakers == {1: "interviewer", 2: "interviewee", 3: "interviewer"}
