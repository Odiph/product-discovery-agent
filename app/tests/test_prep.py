"""`prep` (app/coach/prep.py, app/prep_cli.py): every proposed change has a
reason drawn from arithmetic the project already does, and nothing is written."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import main as main_mod
from app.coach import prep as prep_mod
from app.coach.context import SurveyItem


def _standing(hid, *, scorable=True, sup=0, con=0, unc=0, total=None, falsifier="nobody does it"):
    return SimpleNamespace(
        hypothesis_id=hid, statement=f"statement {hid}", falsifier=falsifier, is_scorable=scorable,
        supporting_interviews=sup, contrary_interviews=con, unclear_interviews=unc,
        total_interviews=total if total is not None else max(sup + con + unc, 0),
    )


def test_gaps_rank_a_missing_criterion_first_and_skip_a_settled_hypothesis():
    gaps = prep_mod.hypothesis_gaps([
        _standing("h1", sup=4, total=4),                 # settled enough: no gap
        _standing("h2", sup=2, con=1, total=3),          # contested
        _standing("h3", total=0),                        # untested
        _standing("h4", scorable=False, sup=5, total=5),  # no criterion, however much evidence
        _standing("h5", unc=2, total=2),                 # only unclear
        _standing("h6", sup=1, total=1),                 # thin
    ])
    assert [(g.hypothesis_id, g.kind) for g in gaps] == [
        ("h4", prep_mod.NO_CRITERION), ("h3", prep_mod.UNTESTED), ("h2", prep_mod.CONTESTED),
        ("h5", prep_mod.ONLY_UNCLEAR), ("h6", prep_mod.THIN),
    ]
    assert "nobody does it" in gaps[1].reason


def test_a_question_is_judged_only_against_interviews_that_had_it():
    survey = [SurveyItem(id="q1", order=0, text="old"), SurveyItem(id="q2", order=1, text="added later")]
    guides = {"S1": frozenset({"q1"}), "S2": frozenset({"q1"}), "S3": frozenset({"q1", "q2"})}
    items = prep_mod.item_proposals(survey, {"q1": ["S1", "S2"]}, guides)
    assert items[0].action == prep_mod.KEEP and "2 of the 3" in items[0].reason
    # One interview had q2 and did not reach it: too few to call it never reached.
    assert items[1].action == prep_mod.KEEP and "0 of the 1" in items[1].reason
    guides["S4"] = frozenset({"q1", "q2"})
    items = prep_mod.item_proposals(survey, {"q1": ["S1", "S2"]}, guides)
    assert items[1].action == prep_mod.MOVE_EARLIER and "2 interviews that had it" in items[1].reason


def test_a_session_without_a_snapshot_counts_for_every_question():
    survey = [SurveyItem(id="q1", order=0, text="x")]
    (item,) = prep_mod.item_proposals(survey, {}, {"S1": None, "S2": None})
    assert item.action == prep_mod.MOVE_EARLIER


def test_a_brand_new_question_is_new_not_never_asked():
    survey = [SurveyItem(id="q9", order=0, text="x")]
    (item,) = prep_mod.item_proposals(survey, {}, {"S1": frozenset({"q1"})})
    assert item.reason == "new since the last interview"


# --- the command ----------------------------------------------------------------------


def _segment(seq, speaker, text):
    return {"kind": "segment", "seq": seq, "speaker": speaker, "text": text, "audio_end_s": seq + 1.0}


@pytest.fixture
def node(tmp_path, monkeypatch):
    context, sessions = tmp_path / "context", tmp_path / "sessions"
    context.mkdir()
    (context / "survey.json").write_text(json.dumps([
        {"id": "q1", "order": 0, "text": "Walk me through the last time"},
        {"id": "q2", "order": 1, "text": "What did you do next?"},
    ]), encoding="utf-8")
    (context / "hypotheses.json").write_text(json.dumps([
        {"id": "h1", "statement": "they export by hand", "falsifier": "nobody exports",
         "criterion": "3 of 5 raise it"},
    ]), encoding="utf-8")
    for name in ("20260901T100000", "20260902T100000"):
        directory = sessions / name
        directory.mkdir(parents=True)
        (directory / "session.json").write_text(json.dumps({"context_survey": [{"id": "q1"}, {"id": "q2"}]}),
                                                encoding="utf-8")
        (directory / "transcript.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
            _segment(0, "interviewer", "Walk me through the last time"),
            {"kind": "event", "seq": 1, "event": "coverage-asked", "detail": {"question_id": "q1"}},
            _segment(2, "interviewee", "sure"),
        ]), encoding="utf-8")
    (sessions / "20260903T100000").mkdir()  # a device test is not an interview
    monkeypatch.setenv("APP_CONTEXT_DIR", str(context))
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(sessions))
    return context


def test_the_command_cites_reasons_and_changes_nothing(node, capsys, monkeypatch):
    def _no_client():
        raise AssertionError("prep built a model client")

    monkeypatch.setattr(main_mod.reasoning_client, "build_client", _no_client)
    before = {p.name: p.read_bytes() for p in node.iterdir()}
    assert main_mod.main(["prep"]) == 0
    out = capsys.readouterr().out
    assert "from 2 interview(s) so far" in out
    assert "2 interview(s) not extracted yet" in out
    assert "[untested] h1" in out and "nobody exports" in out
    assert "keep: asked in 2 of the 2 interviews that had it" in out
    assert "move-earlier: never asked in the 2 interviews that had it" in out
    assert {p.name: p.read_bytes() for p in node.iterdir()} == before


def test_no_survey_and_no_hypotheses_say_what_to_do(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APP_CONTEXT_DIR", str(tmp_path / "context"))
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(tmp_path / "sessions"))
    assert main_mod.main(["prep"]) == 0
    out = capsys.readouterr().out
    assert "No hypotheses yet" in out and "No survey yet" in out


# --- regressions from the 2026-10-21 review ------------------------------------------


def test_malformed_sessions_cost_themselves_never_the_command(node, capsys):
    sessions = node.parent / "sessions"
    bad = sessions / "20260904T100000"
    bad.mkdir()
    (bad / "session.json").write_text(json.dumps({"capture": "in-person", "evidence": "confirmed",
                                                  "context_survey": [{"id": ["unhashable"]}]}), encoding="utf-8")
    (bad / "evidence.jsonl").write_text(json.dumps(_segment(0, "interviewer", "hello")) + "\n", encoding="utf-8")
    (bad / "transcript.jsonl").write_text('{"kind": "segment"\n{"seq": 1}\n', encoding="utf-8")
    odd = sessions / "20260905T100000"
    odd.mkdir()
    (odd / "session.json").write_text(json.dumps({"context_survey": [{"id": ["x"]}, "junk"]}), encoding="utf-8")
    (odd / "transcript.jsonl").write_text(json.dumps(_segment(0, "interviewer", "hi")) + "\n5\n", encoding="utf-8")
    assert main_mod.main(["prep"]) == 0
    assert "from 3 interview(s)" in capsys.readouterr().out


def test_an_unconfirmed_in_person_interview_is_sent_to_confirm_not_to_extract(node, capsys):
    pending = node.parent / "sessions" / "20260906T100000"
    pending.mkdir()
    (pending / "session.json").write_text(json.dumps({"capture": "in-person", "evidence": "pending"}),
                                          encoding="utf-8")
    (pending / "transcript.jsonl").write_text(json.dumps(_segment(0, "interviewer", "hi")) + "\n", encoding="utf-8")
    assert main_mod.main(["prep"]) == 0
    out = capsys.readouterr().out
    unextracted_line = next(line for line in out.splitlines() if "not extracted yet" in line)
    assert "20260906T100000" not in unextracted_line
    assert "wait for confirmed speakers" in out and "20260906T100000" in out



def test_an_untracked_interview_is_left_out_of_the_guide_not_counted_as_never_asking():
    # Only the live coach records which guide questions were asked. An imported
    # interview, or one recorded with the coach off, has no such record: reading
    # its silence as "never asked" told the operator to move every question
    # earlier after 12 imported interviews that asked them all (2026-11-11).
    survey = [SurveyItem(id="q1", order=0, text="x")]
    untracked = {"I1", "I2", "I3"}
    guides = {s: None for s in untracked}
    (item,) = prep_mod.item_proposals(survey, {}, guides, untracked=untracked)
    assert item.action == prep_mod.KEEP
    assert "not tracked" in item.reason and "3 interviews" in item.reason

    guides.update({"S1": frozenset({"q1"}), "S2": frozenset({"q1"})})
    (item,) = prep_mod.item_proposals(survey, {}, guides, untracked=untracked)
    assert item.action == prep_mod.MOVE_EARLIER
    assert "never asked in the 2 interviews that had it" in item.reason and "3 untracked" in item.reason


def _untracked_session(sessions, name, meta):
    directory = sessions / name
    directory.mkdir()
    (directory / "session.json").write_text(json.dumps(meta), encoding="utf-8")
    (directory / "transcript.jsonl").write_text(
        json.dumps(_segment(0, "interviewer", "Walk me through the last time")) + "\n", encoding="utf-8")


def test_imported_and_coach_off_interviews_do_not_make_prep_say_never_asked(node, capsys):
    sessions = node.parent / "sessions"
    _untracked_session(sessions, "20260907T100000", {"engine": "import", "coach_enabled": False})
    _untracked_session(sessions, "20260908T100000", {"engine": "soniox", "coach_enabled": False})
    assert main_mod.main(["prep"]) == 0
    out = capsys.readouterr().out
    assert "from 4 interview(s) so far" in out
    # q2 was never asked in the two TRACKED interviews; the two untracked ones say nothing.
    assert "never asked in the 2 interviews that had it" in out and "2 untracked" in out


def test_a_gap_the_knowledge_base_already_covers_says_where(node, tmp_path, capsys, monkeypatch):
    from app.kb.document import EMAIL, INTERVIEW, Document, Section
    from app.kb.store import KnowledgeStore

    store = KnowledgeStore.for_node(node.parent)
    store.put(Document(source_type=EMAIL, origin="/x/m.eml", title="Re: exports",
                       sections=(Section("Yes, they export by hand every week, it is painful.", "line 1"),)))
    store.put(Document(source_type=EMAIL, origin="/x/n.eml", title="lunch",
                       sections=(Section("Shall we grab lunch by the station?", "line 1"),)))
    store.put(Document(source_type=INTERVIEW, origin="session:S9", title="Interview",
                       sections=(Section("we export by hand", "turn 1", "interviewee"),)))
    assert main_mod.main(["prep"]) == 0
    out = capsys.readouterr().out
    assert "on file: [email] Re: exports -- line 1" in out
    assert "lunch" not in out and "[interview]" not in out
