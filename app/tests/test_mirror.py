"""The cross-interview mirror (app/coach/mirror.py, mirror_load.py, mirror_cli.py)."""

from __future__ import annotations

import json

import pytest

from app import main as main_mod
from app.coach import mirror as mirror_mod
from app.coach import mirror_load
from app.coach.asked_store import CRITIQUE_DOC_FILENAME

OFFER = ("Last Tuesday I had to rebuild the whole export by hand in a spreadsheet, it took me about "
         "three hours and honestly it was the most annoying part of my week")
MOVE_ON = "Love it. Question seven, how do you choose a new tool?"
SPOKEN_SENTINEL = "spokensentinelzz"


def _row(session_id, date, judged, clean, **flags):
    return mirror_mod.session_mirror(
        session_id, date=date, offers=0, walked_past=[],
        critique=None if judged is None else {"summary": {"judged": judged, "clean": clean, **flags}},
    )


def test_a_habit_is_a_flag_in_two_interviews_not_two_questions():
    report = mirror_mod.build([
        _row("a", "2026-09-01", 10, 5, leading=4),
        _row("b", "2026-09-02", 10, 9, pitch=1),
        _row("c", "2026-09-03", 10, 8, pitch=2),
    ])
    assert [(h.flag, h.sessions, h.total) for h in report.habits] == [("pitch", 2, 3)]


def test_the_trend_compares_rates_and_gives_the_odd_one_to_the_later_half():
    report = mirror_mod.build([
        _row("c", "2026-09-03", 20, 18, leading=0),
        _row("a", "2026-09-01", 10, 5, leading=5),
        _row("b", "2026-09-02", 40, 36, leading=4),
    ])
    trend = report.trend
    assert (trend.earlier_sessions, trend.later_sessions) == (1, 2)
    assert trend.earlier_clean_rate == pytest.approx(0.5)
    # Rates per interview, then averaged: the 40-question interview does not
    # outweigh the 20-question one.
    assert trend.later_clean_rate == pytest.approx((36 / 40 + 18 / 20) / 2)
    assert trend.earlier_flag_rates["leading"] == pytest.approx(0.5)
    assert trend.later_flag_rates["leading"] == pytest.approx((4 / 40 + 0) / 2)


def test_uncritiqued_interviews_are_listed_and_kept_out_of_the_numbers():
    report = mirror_mod.build([_row("a", "2026-09-01", None, None), _row("b", "2026-09-02", 10, 5)])
    assert report.uncritiqued == ("a",)
    assert report.trend is None


def test_a_critique_without_a_usable_summary_counts_as_not_critiqued():
    row = mirror_mod.session_mirror("x", date=None, critique={"summary": "garbage"}, offers=0, walked_past=[])
    assert not row.critiqued


# --- loading from disk, and the command --------------------------------------------


def _session(root, name, turns, *, critique=None, **meta):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "session.json").write_text(json.dumps({"started_at": f"{name[:4]}-{name[4:6]}-{name[6:8]}T10:00:00",
                                                        **meta}), encoding="utf-8")
    (directory / "transcript.jsonl").write_text("".join(
        json.dumps({"kind": "segment", "seq": i, "speaker": sp, "text": tx, "audio_end_s": 10.0 * (i + 1)}) + "\n"
        for i, (sp, tx) in enumerate(turns)), encoding="utf-8")
    if critique is not None:
        (directory / CRITIQUE_DOC_FILENAME).write_text(json.dumps(critique), encoding="utf-8")
    return directory


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    _session(root, "20260901T100000", [("interviewer", "How did last week go?"), ("interviewee", OFFER),
                                       ("interviewer", MOVE_ON)],
             critique={"summary": {"judged": 4, "clean": 2, "leading": 2}})
    _session(root, "20260902T100000", [("interviewer", "How did last week go?"),
                                       ("interviewee", OFFER + " " + SPOKEN_SENTINEL),
                                       ("interviewer", "Why was it so annoying?")],
             critique={"summary": {"judged": 4, "clean": 4, "leading": 1}})
    (root / "20260903T100000").mkdir()  # a device test: no speech, no critique
    _session(root, "20260904T100000", [("interviewee", OFFER), ("interviewer", MOVE_ON)],
             capture="in-person", evidence="pending")
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(root))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(tmp_path / "context"))
    return root


def test_loading_skips_empty_sessions_and_trusts_no_unconfirmed_roles(sessions):
    report = mirror_load.load(sessions)
    assert [s.session_id for s in report.sessions] == ["20260901T100000", "20260902T100000", "20260904T100000"]
    by_id = {s.session_id: s for s in report.sessions}
    assert len(by_id["20260901T100000"].walked_past) == 1
    assert by_id["20260901T100000"].walked_past[0].acknowledged
    assert by_id["20260902T100000"].walked_past == ()
    assert by_id["20260904T100000"].walked_past == () and by_id["20260904T100000"].offers == 0
    assert [(h.flag, h.sessions) for h in report.habits] == [("leading", 2)]


def test_the_command_reports_without_words_unless_asked(sessions, capsys, monkeypatch):
    def _no_client():
        raise AssertionError("mirror built a model client")

    monkeypatch.setattr(main_mod.reasoning_client, "build_client", _no_client)
    assert main_mod.main(["mirror"]) == 0
    out = capsys.readouterr().out
    assert "leading: in 2 of 2 interviews, 3 questions" in out
    assert "Walked past: 1 of 2 offers" in out  # the unconfirmed in-person offer is not counted
    assert "20260901T100000 at 00:20" in out and "acknowledged, then moved on" in out
    assert "1 interview(s) have no question critique" in out
    assert OFFER[:30] not in out

    assert main_mod.main(["mirror", "--show"]) == 0
    shown = capsys.readouterr().out
    assert "they said: Last Tuesday" in shown and "you asked: Love it." in shown


def test_an_empty_project_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(tmp_path / "none"))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(tmp_path / "context"))
    assert main_mod.main(["mirror"]) == 0
    assert "No interviews" in capsys.readouterr().out


# --- regressions from the 2026-10-21 review ------------------------------------------


@pytest.mark.parametrize("meta, transcript", [
    ("[]", None),                                                   # session.json not an object
    ('{"started_at": 20260901}', None),                             # a number where a date belongs
    (None, '{"kind": "segment", "seq": "a", "speaker": "interviewee", "text": "x"}\n'
           '{"kind": "segment", "seq": 2, "speaker": "interviewer", "text": "y"}\n'),  # mixed seq types
    (None, '{"kind": "segment", "seq": 1, "speaker": "interviewee", "text": 5}\n'),    # text not a string
])
def test_one_malformed_session_never_takes_the_mirror_down(sessions, capsys, meta, transcript):
    bad = sessions / "20260905T100000"
    bad.mkdir()
    if meta is not None:
        (bad / "session.json").write_text(meta, encoding="utf-8")
    (bad / "transcript.jsonl").write_text(transcript or "", encoding="utf-8")
    report = mirror_load.load(sessions)
    assert "20260901T100000" in [s.session_id for s in report.sessions]
    assert main_mod.main(["mirror", "--show"]) == 0


def test_a_session_with_no_metadata_still_shows_its_words(sessions, capsys):
    (sessions / "20260901T100000" / "session.json").unlink()
    assert main_mod.main(["mirror", "--show"]) == 0
    assert "they said: Last Tuesday" in capsys.readouterr().out


def test_a_session_that_cannot_be_read_is_named_not_hidden(sessions, capsys, monkeypatch):
    def _boom(session_dir):
        if session_dir.name == "20260902T100000":
            raise RuntimeError("disk on fire")
        return original(session_dir)

    original = mirror_load._session
    monkeypatch.setattr(mirror_load, "_session", _boom)
    assert main_mod.main(["mirror"]) == 0
    out = capsys.readouterr().out
    assert "could not be read and are left out: 20260902T100000" in out
    assert "disk on fire" not in out


@pytest.mark.parametrize("summary", [
    {"judged": 4, "clean": 10},
    {"judged": -1, "clean": 0},
    {"judged": True, "clean": 0},
    {"judged": 4, "clean": "2"},
])
def test_impossible_critique_numbers_count_as_no_critique(summary):
    row = mirror_mod.session_mirror("x", date=None, critique={"summary": summary}, offers=0, walked_past=[])
    assert not row.critiqued and row.clean_rate is None


def test_off_topic_is_a_habit_like_any_other_flag():
    report = mirror_mod.build([
        _row("a", "2026-09-01", 10, 5, off_topic=2),
        _row("b", "2026-09-02", 10, 9, off_topic=1),
    ])
    assert [(h.flag, h.sessions, h.total) for h in report.habits] == [("off_topic", 2, 3)]


def test_every_mirror_flag_has_a_label():
    from app import mirror_cli

    assert set(mirror_cli.FLAG_LABELS) == set(mirror_mod.FLAG_KEYS)


def test_a_critique_older_than_a_flag_does_not_fake_a_trend_for_it():
    """Older critiques have no `off_topic` count -- not a count of zero."""
    report = mirror_mod.build([
        _row("a", "2026-09-01", 10, 5, leading=1),
        _row("b", "2026-09-02", 10, 5, leading=1),
        _row("c", "2026-09-03", 10, 5, leading=1, off_topic=1),
        _row("d", "2026-09-04", 10, 5, leading=1, off_topic=1),
    ])
    assert "off_topic" not in report.trend.earlier_flag_rates
    assert "off_topic" not in report.trend.later_flag_rates
    assert report.trend.later_flag_rates["leading"] == 0.1


def test_a_flag_rate_averages_only_the_critiques_that_recorded_it():
    report = mirror_mod.build([
        _row("a", "2026-09-01", 10, 5),
        _row("b", "2026-09-02", 10, 5, off_topic=2),
        _row("c", "2026-09-03", 10, 5, off_topic=0),
        _row("d", "2026-09-04", 10, 5, off_topic=4),
    ])
    assert report.trend.earlier_flag_rates["off_topic"] == 0.2
    assert report.trend.later_flag_rates["off_topic"] == 0.2



# --- a question the critic could not judge is not an unclean one --------------
#
# The critic sees the interviewer's questions without what the interviewee had
# just said, so a good follow-up ("Say more about that") is banded uncertain.
# Counting it as not clean scored the Mom Test's best move as a failure.


def _unsure_critique(judged, clean, uncertain=None, turns=None, **flags):
    summary = {"judged": judged, "clean": clean, **flags}
    if uncertain is not None:
        summary["uncertain"] = uncertain
    body = {"summary": summary}
    if turns is not None:
        body["turns"] = turns
    return body


def _one_row(critique):
    return mirror_mod.session_mirror("s", date="2026-09-01", critique=critique, offers=0, walked_past=[])


def test_the_clean_rate_leaves_out_what_the_critic_could_not_judge():
    row = _one_row(_unsure_critique(judged=10, clean=3, uncertain=6))
    assert row.uncertain == 6
    assert row.clean_rate == 0.75


def test_an_older_critique_counts_uncertain_from_its_turns():
    turns = [{"judgment": {"band": b}} for b in ("clean", "uncertain", "uncertain", "clear_violation")]
    row = _one_row(_unsure_critique(judged=4, clean=1, turns=turns))
    assert row.uncertain == 2
    assert row.clean_rate == 0.5


def test_all_uncertain_has_no_rate_rather_than_zero():
    row = _one_row(_unsure_critique(judged=3, clean=0, uncertain=3))
    assert row.critiqued
    assert row.clean_rate is None


def test_an_impossible_uncertain_count_is_ignored_not_trusted():
    row = _one_row(_unsure_critique(judged=4, clean=3, uncertain=3))
    assert row.uncertain is None
    assert row.clean_rate == 0.75


def test_an_interview_with_no_rate_stays_out_of_the_clean_trend():
    report = mirror_mod.build([
        mirror_mod.session_mirror("a", date="2026-09-01", critique=_unsure_critique(4, 0, uncertain=4), offers=0, walked_past=[]),
        mirror_mod.session_mirror("b", date="2026-09-02", critique=_unsure_critique(4, 2, uncertain=0), offers=0, walked_past=[]),
        mirror_mod.session_mirror("c", date="2026-09-03", critique=_unsure_critique(4, 4, uncertain=0), offers=0, walked_past=[]),
    ])
    assert report.trend.earlier_clean_rate == 0.5
    assert report.trend.later_clean_rate == 1.0
