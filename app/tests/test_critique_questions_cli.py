"""Tests for `python -m app critique-questions` (`app/main.py`).

The ordering is the contract: everything that can fail for free must fail
BEFORE anything reaches the vendor. A user whose session has no interviewer
speech, or whose path is wrong, should not pay for a call whose result would be
discarded -- the same rule `run_extract` follows, and for the same reason.
"""

from __future__ import annotations

import inspect
import json

import pytest

from app import main as main_mod
from app.coach import critic as critic_mod
from app.coach.context import SurveyItem
from app.coach.critic import BAND_CLEAN, BAND_CLEAR_VIOLATION, Judgment


def _segment(seq, speaker, text, end_s):
    return {"kind": "segment", "seq": seq, "speaker": speaker, "text": text,
            "audio_end_s": end_s, "audio_start_s": end_s, "ready_wall_s": end_s,
            "latency_s": 0.1, "detected_language": "en", "engine": "test",
            "written_at": "2026-08-14T00:00:00Z"}


@pytest.fixture
def session(tmp_path):
    """A closed session with two interviewer turns and one answer."""
    session_dir = tmp_path / "sessions" / "20260813T213559"
    session_dir.mkdir(parents=True)
    records = [
        _segment(0, "interviewer", "Walk me through the last time you sat", 26.64),
        _segment(1, "interviewer", "down to play, from the machine on.", 30.96),
        _segment(2, "interviewee", "I turn it on and then I wait a while", 60.0),
        _segment(3, "interviewer", "How long is that wait, usually?", 71.4),
    ]
    (session_dir / "transcript.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    (session_dir / "session.json").write_text(
        json.dumps({"closed_at": "2026-08-13T22:00:00Z"}), encoding="utf-8"
    )
    return session_dir


def _judgment(index, band=BAND_CLEAN, leading=False):
    return Judgment(index=index, is_leading=leading,
                    is_hypothetical_or_future_tense=False, is_pitch=False,
                    is_opinion_seeking=False, is_confirmation_only=False, is_generic=False, is_off_topic=False,
                    band=band, rationale="because")


@pytest.fixture
def no_vendor(monkeypatch):
    """Fails loudly if anything reaches a client. Every test that should not
    make a call installs this and asserts nothing was built."""
    calls = []

    def _build_client():
        calls.append("built")
        raise AssertionError("a client was built when none should have been")

    monkeypatch.setattr(main_mod.reasoning_client, "build_client", _build_client)
    return calls


@pytest.fixture
def stub_vendor(monkeypatch):
    """A client that is never really used, and a critique that answers clean."""
    monkeypatch.setattr(main_mod.reasoning_client, "build_client", lambda: object())
    monkeypatch.setattr(main_mod.reasoning_client, "resolve_model", lambda: "test-model")

    def _run_critique(client, **kwargs):
        # Bound against the real signature: a stub that accepts what the real
        # critic rejects is how a missing `survey` shipped unnoticed.
        inspect.signature(critic_mod.run_critique).bind(client, **kwargs)
        _run_critique.surveys.append(kwargs["survey"])
        _run_critique.rules.append(kwargs["process"])
        return [_judgment(c.index) for c in kwargs["candidates"]]

    _run_critique.surveys = []
    _run_critique.rules = []

    monkeypatch.setattr(
        main_mod.coach_asked_critique.critic_mod, "run_critique", _run_critique
    )
    return _run_critique


# --- nothing reaches the vendor that does not have to --------------------------


def test_a_missing_session_never_builds_a_client(tmp_path, no_vendor, capsys):
    code = main_mod.main(["critique-questions", str(tmp_path / "nope")])
    assert code == 1
    assert no_vendor == []
    assert "no session directory found" in capsys.readouterr().err


def test_a_session_with_no_interviewer_speech_never_builds_a_client(
    tmp_path, no_vendor, capsys
):
    """An interview where only the interviewee was captured is a real and
    common failure -- five of the real recordings so far were misconfigured
    one way or another. It must cost nothing."""
    session_dir = tmp_path / "sessions" / "s"
    session_dir.mkdir(parents=True)
    (session_dir / "transcript.jsonl").write_text(
        json.dumps(_segment(0, "interviewee", "I turn it on and wait", 10.0)) + "\n",
        encoding="utf-8",
    )
    code = main_mod.main(["critique-questions", str(session_dir)])
    assert code == 1
    assert no_vendor == []
    assert "nothing written, nothing called" in capsys.readouterr().err


# --- the happy path -------------------------------------------------------------


def test_it_writes_the_artifact_next_to_the_transcript(session, stub_vendor, capsys):
    code = main_mod.main(["critique-questions", str(session)])
    assert code == 0
    written = session / main_mod.CRITIQUE_DOC_FILENAME
    assert written.is_file()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["session_id"] == "20260813T213559"
    assert payload["summary"]["turns"] == 2
    assert payload["summary"]["judged"] == 2


def test_the_split_question_is_judged_as_one_turn(session, stub_vendor):
    """End to end: two fragments in, one turn judged."""
    main_mod.main(["critique-questions", str(session)])
    payload = json.loads(
        (session / main_mod.CRITIQUE_DOC_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["turns"][0]["seqs"] == [0, 1]
    assert payload["turns"][0]["text"].startswith("Walk me through the last time you sat down")


def test_the_calibration_caveat_is_printed_on_every_run(session, stub_vendor, capsys):
    """A percentage is exactly the kind of number that gets quoted without its
    caveat, so the caveat rides with it rather than living in a docstring."""
    main_mod.main(["critique-questions", str(session)])
    out = capsys.readouterr().out
    assert "calibrated on PROPOSED questions" in out


def test_an_unjudged_turn_makes_the_command_exit_nonzero(session, monkeypatch, capsys):
    """Partial results are written, but the exit code says they are partial --
    a script that treats this as success would file an unreachable critic
    under 'the interviewer did fine'."""
    monkeypatch.setattr(main_mod.reasoning_client, "build_client", lambda: object())
    monkeypatch.setattr(main_mod.reasoning_client, "resolve_model", lambda: "test-model")

    def _failing(client, **kwargs):
        inspect.signature(critic_mod.run_critique).bind(client, **kwargs)
        raise main_mod.coach_asked_critique.CritiqueFailure(reason="timeout")

    monkeypatch.setattr(
        main_mod.coach_asked_critique.critic_mod, "run_critique", _failing
    )
    code = main_mod.main(["critique-questions", str(session)])
    assert code == 1
    payload = json.loads(
        (session / main_mod.CRITIQUE_DOC_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["summary"]["unjudged"] == 2
    assert payload["summary"]["clean_rate"] is None
    assert "clean_rate=n/a" in capsys.readouterr().out


def test_min_words_is_actually_plumbed_through(session, stub_vendor):
    main_mod.main(["critique-questions", str(session), "--min-words", "99"])
    payload = json.loads(
        (session / main_mod.CRITIQUE_DOC_FILENAME).read_text(encoding="utf-8")
    )
    # Both real turns end in '.' or '?'; only the one with '?' survives a
    # floor nothing else can clear.
    assert payload["summary"]["turns"] == 1
    assert payload["turns"][0]["text"] == "How long is that wait, usually?"


# --- `--all`: every interview without a critique, through the same path ------------


def _sessions_env(monkeypatch, session):
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(session.parent))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(session.parent.parent / "context"))


def test_all_judges_only_the_interviews_without_a_critique(session, stub_vendor, monkeypatch, capsys):
    _sessions_env(monkeypatch, session)
    done = session.parent / "20260814T100000"
    done.mkdir()
    (done / "transcript.jsonl").write_text((session / "transcript.jsonl").read_text(encoding="utf-8"),
                                           encoding="utf-8")
    (done / main_mod.CRITIQUE_DOC_FILENAME).write_text('{"kept": true}', encoding="utf-8")
    empty = session.parent / "20260815T100000"
    empty.mkdir()
    (empty / "transcript.jsonl").write_text("", encoding="utf-8")

    assert main_mod.main(["critique-questions", "--all"]) == 0
    out = capsys.readouterr().out
    assert "1 interview(s) to judge" in out
    assert (session / main_mod.CRITIQUE_DOC_FILENAME).is_file()
    assert (done / main_mod.CRITIQUE_DOC_FILENAME).read_text(encoding="utf-8") == '{"kept": true}'
    assert not (empty / main_mod.CRITIQUE_DOC_FILENAME).exists()


def test_all_with_nothing_pending_never_builds_a_client(session, no_vendor, monkeypatch, capsys):
    _sessions_env(monkeypatch, session)
    (session / main_mod.CRITIQUE_DOC_FILENAME).write_text("{}", encoding="utf-8")
    assert main_mod.main(["critique-questions", "--all"]) == 0
    assert "Nothing called" in capsys.readouterr().out
    assert no_vendor == []


def test_force_judges_again(session, stub_vendor, monkeypatch):
    _sessions_env(monkeypatch, session)
    (session / main_mod.CRITIQUE_DOC_FILENAME).write_text("{}", encoding="utf-8")
    assert main_mod.main(["critique-questions", "--all", "--force"]) == 0
    assert json.loads((session / main_mod.CRITIQUE_DOC_FILENAME).read_text(encoding="utf-8"))["summary"]


def test_neither_a_session_nor_all_is_an_error(no_vendor, capsys):
    assert main_mod.main(["critique-questions"]) == 2
    assert "--all" in capsys.readouterr().err


def test_all_survives_a_corrupt_session_and_skips_unconfirmed_in_person(session, stub_vendor, monkeypatch, capsys):
    _sessions_env(monkeypatch, session)
    broken = session.parent / "20260814T100000"
    broken.mkdir()
    (broken / "transcript.jsonl").write_text('{"kind": "segment"\n{"seq": 1}\n', encoding="utf-8")
    in_person = session.parent / "20260815T100000"
    in_person.mkdir()
    (in_person / "transcript.jsonl").write_text((session / "transcript.jsonl").read_text(encoding="utf-8"),
                                                encoding="utf-8")
    (in_person / "session.json").write_text(json.dumps({"capture": "in-person", "evidence": "pending"}),
                                            encoding="utf-8")
    assert main_mod.main(["critique-questions", "--all"]) == 0
    captured = capsys.readouterr()
    assert "skipped 20260814T100000" in captured.err and "skipped 20260815T100000" in captured.err
    assert (session / main_mod.CRITIQUE_DOC_FILENAME).is_file()
    assert not (in_person / main_mod.CRITIQUE_DOC_FILENAME).exists()


def test_all_keeps_going_after_one_failed_call(session, monkeypatch, capsys):
    _sessions_env(monkeypatch, session)
    second = session.parent / "20260814T100000"
    second.mkdir()
    (second / "transcript.jsonl").write_text((session / "transcript.jsonl").read_text(encoding="utf-8"),
                                             encoding="utf-8")
    calls = []

    def _flaky(args, cfg, session_dir):
        calls.append(session_dir.name)
        if len(calls) == 1:
            raise RuntimeError("vendor down")
        return 0

    monkeypatch.setattr(main_mod, "_critique_session", _flaky)
    assert main_mod.main(["critique-questions", "--all"]) == 1
    assert len(calls) == 2
    assert "continuing with the rest" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["--force", "S1"], ["--all", "S1"]])
def test_contradictory_flags_are_refused(no_vendor, argv, capsys):
    assert main_mod.main(["critique-questions", *argv]) == 2


def test_the_survey_the_interview_ran_with_reaches_the_critic(session, stub_vendor):
    """The snapshot in session.json, not today's guide: a question is judged
    against what that interview was for."""
    meta = {"closed_at": "2026-08-13T22:00:00Z",
            "context_survey": [{"id": "s7", "order": 1, "text": "How do you start a session?"}]}
    (session / "session.json").write_text(json.dumps(meta), encoding="utf-8")
    assert main_mod.main(["critique-questions", str(session)]) == 0
    assert stub_vendor.surveys
    assert all([item.id for item in s] == ["s7"] for s in stub_vendor.surveys)


def test_without_a_snapshot_the_projects_current_survey_is_used(session, stub_vendor, monkeypatch):
    current = (SurveyItem(id="s2", order=1, text="What happens before you play?"),)
    monkeypatch.setattr(main_mod.coach_context, "load_survey", lambda _dir: current)
    assert main_mod.main(["critique-questions", str(session)]) == 0
    assert all(tuple(s) == current for s in stub_vendor.surveys)


def test_without_any_survey_the_critique_still_runs(session, stub_vendor, monkeypatch):
    def _missing(_dir):
        raise main_mod.ContextValidationError("survey.json does not exist")

    monkeypatch.setattr(main_mod.coach_context, "load_survey", _missing)
    assert main_mod.main(["critique-questions", str(session)]) == 0
    assert all(tuple(s) == () for s in stub_vendor.surveys)


def test_a_malformed_survey_snapshot_fails_before_any_call(session, stub_vendor, capsys):
    meta = {"closed_at": "2026-08-13T22:00:00Z", "context_survey": [{"id": "s1"}]}
    (session / "session.json").write_text(json.dumps(meta), encoding="utf-8")
    assert main_mod.main(["critique-questions", str(session)]) == 1
    assert stub_vendor.surveys == []
    assert "context_survey is malformed" in capsys.readouterr().err


def test_no_survey_and_no_hypotheses_warns_that_off_topic_is_noise(session, stub_vendor, monkeypatch, capsys):
    monkeypatch.setattr(main_mod.coach_context, "load_survey", lambda _dir: ())
    monkeypatch.setattr(main_mod.coach_corpus, "load_hypotheses", lambda *_a, **_k: ())
    assert main_mod.main(["critique-questions", str(session)]) == 0
    assert "nothing to judge off-topic against" in capsys.readouterr().err


def test_an_unreadable_project_survey_is_a_clean_error(session, stub_vendor, monkeypatch, capsys):
    def _unreadable(_dir):
        raise PermissionError("denied")

    monkeypatch.setattr(main_mod.coach_context, "load_survey", _unreadable)
    assert main_mod.main(["critique-questions", str(session)]) == 1
    assert stub_vendor.surveys == []
    assert "cannot read the project's survey" in capsys.readouterr().err


def test_the_critique_holds_the_interview_to_your_own_rules(session, stub_vendor, monkeypatch):
    """B5: the project's `process.md` reaches every critique batch."""
    rule = "## Price waits\nNever ask about price before the workflow."
    monkeypatch.setattr(main_mod.coach_process, "load_process", lambda _dir: rule)
    assert main_mod.main(["critique-questions", str(session)]) == 0
    assert stub_vendor.rules and set(stub_vendor.rules) == {rule}


def test_unreadable_rules_are_a_clean_error_before_any_call(session, stub_vendor, monkeypatch, capsys):
    def _bad(_dir):
        raise main_mod.ContextValidationError("cannot read process.md: denied")

    monkeypatch.setattr(main_mod.coach_process, "load_process", _bad)
    assert main_mod.main(["critique-questions", str(session)]) == 1
    assert stub_vendor.rules == []
    assert "process.md" in capsys.readouterr().err
