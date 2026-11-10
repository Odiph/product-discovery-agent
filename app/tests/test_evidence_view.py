"""`app.session.evidence_view`: what a READER of a confirmed in-person session
sees -- the confirmed after-meeting turns, with the live events (suggestions,
coverage) re-anchored onto them.

Why it matters beyond display: `extract` cites the CONFIRMED turns' seqs, and
mirror/offer highlights do too. A view that shows the live transcript points
every such citation at the wrong words. The two transcripts share one clock --
`room.wav` is written from the very frames the live engine was fed -- so a
live turn maps to the confirmed turn covering the moment it ended.
"""

from __future__ import annotations

import json

import pytest

from app.session import evidence as ev
from app.session import evidence_view
from app.session import render as render_mod
from app.session.reader import read_session
from app.session.render import render_session


def _segment(seq, speaker, text, start, end):
    return {
        "kind": "segment", "seq": seq, "speaker": speaker, "text": text,
        "audio_start_s": start, "audio_end_s": end, "ready_wall_s": end, "latency_s": 0.4,
        "detected_language": "en", "engine": "soniox-in-person", "written_at": "2026-11-09T10:00:00+00:00",
    }


def _suggestion(seq, trigger_seq, text):
    return {
        "kind": "suggestion", "seq": seq, "trigger_seq": trigger_seq, "text": text, "move": "dig",
        "band": "good", "is_leading": False, "is_hypothetical_or_future_tense": False, "is_pitch": False,
        "is_opinion_seeking": False, "is_confirmation_only": False, "is_generic": False,
        "is_off_topic": False, "rationale": "r", "shown": True, "written_at": "2026-11-09T10:00:00+00:00",
    }


def _coverage(seq, matched_seq, at_s):
    return {
        "kind": "event", "seq": seq, "speaker": "interviewer", "event": "coverage-asked",
        "detail": {"question_id": "q1", "matched_seq": matched_seq}, "at_s": at_s,
        "written_at": "2026-11-09T10:00:00+00:00",
    }


# Live: the engine mislabelled the second turn (it is the interviewee) and cut
# the answer in two. Seqs come from ONE counter shared with the events, and are
# numbered from 10 so that no live seq coincides with a confirmed one: a
# mapping that did nothing could not pass by accident.
LIVE = [
    _segment(10, "interviewer", "how do you plan the week", 0.0, 3.0),
    _segment(11, "interviewer", "we use a whiteboard", 3.2, 6.0),        # wrong role, live
    _segment(12, "interviewee", "and then a spreadsheet", 6.1, 9.0),
    _suggestion(13, 12, "ask what broke last time"),
    _coverage(14, 10, 3.0),
]
# Confirmed: two turns, right roles, its own numbering (what facts cite).
EVIDENCE = [
    {**_segment(1, "interviewer", "how do you plan the week", 0.0, 3.0), "pass_speaker": "interviewer"},
    {**_segment(2, "interviewee", "we use a whiteboard and then a spreadsheet", 3.2, 9.1),
     "pass_speaker": "interviewee", "disputed": False},
]
CONFIRMED = {"capture": "in-person", ev.EVIDENCE_KEY: ev.EVIDENCE_CONFIRMED, "closed_at": "2026-11-09T10:30:00+00:00"}


def _write(session_dir, meta, live=LIVE, evidence=EVIDENCE):
    session_dir.mkdir()
    (session_dir / "session.json").write_text(json.dumps({"coach_enabled": True, **meta}), encoding="utf-8")
    (session_dir / "transcript.jsonl").write_text("".join(json.dumps(r) + "\n" for r in live), encoding="utf-8")
    if evidence is not None:
        (session_dir / ev.EVIDENCE_TRANSCRIPT_FILENAME).write_text(
            "".join(json.dumps(r) + "\n" for r in evidence), encoding="utf-8"
        )
    return session_dir


@pytest.fixture
def confirmed(tmp_path):
    return _write(tmp_path / "20261109T100000", CONFIRMED)


def _one(view, kind, **match):
    (record,) = [r for r in view.records_of_kind(kind) if all(r.get(k) == v for k, v in match.items())]
    return record


def test_a_confirmed_session_shows_the_confirmed_turns_not_the_live_ones(confirmed):
    view = evidence_view.read_view(confirmed)
    segments = view.records_of_kind("segment")
    assert [(s["seq"], s["speaker"]) for s in segments] == [(1, "interviewer"), (2, "interviewee")]
    assert "pass_speaker" not in segments[0]  # loads as a plain SegmentRecord


def test_a_suggestion_is_re_anchored_to_the_confirmed_turn_covering_its_trigger(confirmed):
    suggestion = _one(evidence_view.read_view(confirmed), "suggestion")
    assert suggestion["trigger_seq"] == 2 and suggestion["live_trigger_seq"] == 12
    assert suggestion["seq"] == 13  # its own id stays live: the hub stores accepts by it


def test_a_coverage_match_points_at_the_confirmed_turn(confirmed):
    event = _one(evidence_view.read_view(confirmed), "event")
    assert event["detail"]["matched_seq"] == 1 and event["detail"]["live_matched_seq"] == 10


def test_a_coverage_near_miss_points_at_the_confirmed_turn_too(tmp_path):
    near_miss = {
        "kind": "event", "seq": 15, "speaker": "interviewer", "event": "coverage-considered",
        "detail": {"question_id": "q2", "seq": 11}, "at_s": 6.0, "written_at": "2026-11-09T10:00:00+00:00",
    }
    view = evidence_view.read_view(_write(tmp_path / "s", CONFIRMED, live=LIVE + [near_miss]))
    event = _one(view, "event", event="coverage-considered")
    assert event["detail"]["seq"] == 2 and event["detail"]["live_seq"] == 11


@pytest.mark.parametrize("meta", [
    {"capture": "in-person", ev.EVIDENCE_KEY: ev.EVIDENCE_TRANSCRIBED},
    {"capture": "in-person", ev.EVIDENCE_KEY: ev.EVIDENCE_CONFIRMED, ev.EVIDENCE_SOURCE_KEY: ev.EVIDENCE_SOURCE_LIVE},
    {},  # a two-stream call
])
def test_unconfirmed_live_accepted_and_two_stream_sessions_read_the_live_transcript(tmp_path, meta):
    view = evidence_view.read_view(_write(tmp_path / "s", meta))
    assert [s["seq"] for s in view.records_of_kind("segment")] == [10, 11, 12]
    assert _one(view, "suggestion")["trigger_seq"] == 12


def test_a_trigger_after_the_last_confirmed_turn_anchors_to_the_last_one(tmp_path):
    live = LIVE + [_segment(15, "interviewee", "one more thing", 20.0, 22.0), _suggestion(16, 15, "late")]
    view = evidence_view.read_view(_write(tmp_path / "s", CONFIRMED, live=live))
    assert _one(view, "suggestion", text="late")["trigger_seq"] == 2


def test_a_pointer_that_cannot_be_mapped_becomes_none_never_a_confirmed_seq_by_accident(tmp_path):
    # Live seq 2 is not a segment, and 2 IS a confirmed seq: kept raw, it
    # would point at the wrong words. Live seq 16 has no end time.
    endless = _segment(16, "interviewee", "no end", 30.0, 31.0)
    del endless["audio_end_s"]
    live = LIVE + [_suggestion(15, 2, "orphan"), endless, _suggestion(17, 16, "endless")]
    view = evidence_view.read_view(_write(tmp_path / "s", CONFIRMED, live=live))
    for text, live_seq in (("orphan", 2), ("endless", 16)):
        record = _one(view, "suggestion", text=text)
        assert record["trigger_seq"] is None and record["live_trigger_seq"] == live_seq


def test_an_unmapped_coverage_pointer_renders_as_not_found(tmp_path):
    live = LIVE[:4] + [_coverage(14, 2, 3.0)]  # live 2 is not a segment; confirmed 2 exists
    text = render_session(_write(tmp_path / "s", CONFIRMED, live=live), context_dir=None)
    assert "<segment not found>" in text.split("coverage: MATCHED")[1].split("\n")[0]


def test_an_empty_confirmed_transcript_maps_nothing(tmp_path):
    view = evidence_view.read_view(_write(tmp_path / "s", CONFIRMED, evidence=[]))
    assert view.records_of_kind("segment") == ()
    assert _one(view, "suggestion")["trigger_seq"] is None


def test_the_turn_containing_the_moment_wins_over_a_backchannel_that_ended_just_before(tmp_path):
    evidence = [
        {**_segment(1, "interviewee", "so the long answer goes on and on", 0.0, 10.0), "pass_speaker": "interviewee"},
        {**_segment(2, "interviewer", "mm", 8.5, 8.8), "pass_speaker": "interviewer"},
    ]
    live = [_segment(10, "interviewee", "so the long answer", 0.0, 9.0), _suggestion(11, 10, "s")]
    view = evidence_view.read_view(_write(tmp_path / "s", CONFIRMED, live=live, evidence=evidence))
    assert _one(view, "suggestion")["trigger_seq"] == 1


def test_render_of_a_confirmed_session_uses_the_confirmed_words_and_roles(confirmed):
    text = render_session(confirmed, context_dir=None)
    assert "we use a whiteboard and then a spreadsheet" in text
    assert text.index("we use a whiteboard and then a spreadsheet") < text.index("ask what broke last time")
    assert "how do you plan the week" in text.split("coverage: MATCHED")[1].split("\n")[0]


def test_render_puts_a_suggestion_after_its_turn_even_when_its_live_seq_is_lower(tmp_path):
    evidence = [{**_segment(40, "interviewee", "the confirmed answer", 0.0, 9.0), "pass_speaker": "interviewee"}]
    live = [_segment(1, "interviewee", "the live answer", 0.0, 9.0), _suggestion(2, 1, "the suggestion")]
    text = render_session(_write(tmp_path / "s", CONFIRMED, live=live, evidence=evidence), context_dir=None)
    assert text.index("the confirmed answer") < text.index("the suggestion")


def test_render_counts_every_live_coach_cycle_even_when_two_map_to_one_turn(tmp_path):
    session = _write(tmp_path / "s", CONFIRMED, live=LIVE + [_suggestion(15, 11, "from the first half")])
    assert {r["trigger_seq"] for r in evidence_view.read_view(session).records_of_kind("suggestion")} == {2}
    assert "- Cycles completed: 2" in render_session(session, context_dir=None)


def test_the_hub_transcript_of_a_confirmed_session_is_the_confirmed_one(confirmed):
    from app.web import review

    turns = review._transcript(confirmed.parent, confirmed.name)
    assert [t["seq"] for t in turns] == [1, 2]
    assert "spreadsheet" in turns[1]["text"]


def test_render_reports_the_live_runs_latency_not_the_confirmed_passes_zeros(confirmed):
    text = render_session(confirmed, context_dir=None)
    assert "\n".join(render_mod._render_latency_section(read_session(confirmed))) in text
