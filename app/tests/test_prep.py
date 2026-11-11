"""`prep` (app/coach/prep.py, app/prep_cli.py): every proposed change has a
reason drawn from arithmetic the project already does, and nothing is written."""

from __future__ import annotations

import json
from pathlib import Path
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
        {"id": "q1", "order": 0, "text": "Walk me through your last weekly report export"},
        {"id": "q2", "order": 1, "text": "What happened after the export failed?"},
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
            _segment(0, "interviewer", "Walk me through your last weekly report export"),
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


def test_reconstructed_interviews_count_and_the_reason_says_so():
    survey = [SurveyItem(id="q1", order=0, text="x")]
    guides = {"S1": frozenset({"q1"}), "I1": None, "I2": None}
    (item,) = prep_mod.item_proposals(survey, {"q1": ["S1", "I1", "I2"]}, guides, reconstructed={"I1", "I2"})
    assert item.action == prep_mod.KEEP
    assert item.reason == "asked in at least 3 of the 3 interviews that had it (2 reconstructed from the transcript)"
    # Reconstructed silence is not "never asked": the matcher misses reworded
    # questions, so with one live record behind it the most it says is "check".
    (item,) = prep_mod.item_proposals(survey, {}, guides, reconstructed={"I1", "I2"})
    assert item.action == prep_mod.KEEP and "check by hand" in item.reason
    guides["S2"] = frozenset({"q1"})
    (item,) = prep_mod.item_proposals(survey, {}, guides, reconstructed={"I1", "I2"})
    assert item.action == prep_mod.MOVE_EARLIER
    assert "never asked in the 4 interviews that had it" in item.reason and "2 reconstructed" in item.reason


def _untracked_session(sessions, name, meta, said="Walk me through your last weekly report export"):
    directory = sessions / name
    directory.mkdir()
    (directory / "session.json").write_text(json.dumps(meta), encoding="utf-8")
    (directory / "transcript.jsonl").write_text(
        json.dumps(_segment(0, "interviewer", said)) + "\n", encoding="utf-8")


def test_imported_and_coach_off_interviews_are_reconstructed_from_the_transcript(node, capsys):
    # Neither has a coverage record, but both transcripts hold q1's words: the
    # interviewer DID ask it. Their silence on q2 is reconstructed silence.
    sessions = node.parent / "sessions"
    _untracked_session(sessions, "20260907T100000", {"engine": "import", "coach_enabled": False})
    _untracked_session(sessions, "20260908T100000", {"engine": "soniox", "coach_enabled": False})
    # Coach off, and nothing it said matches the guide: no way to tell
    # "asked none" from "the words do not match" (another language, say).
    _untracked_session(sessions, "20260909T100000", {"engine": "soniox", "coach_enabled": False},
                       said="hello there, can you hear me")
    assert main_mod.main(["prep"]) == 0
    out = capsys.readouterr().out
    assert "from 5 interview(s) so far" in out
    assert ("keep: asked in at least 4 of the 4 interviews that had it "
            "(2 reconstructed from the transcript; 1 untracked interviews left out)") in out
    assert ("move-earlier: never asked in the 4 interviews that had it: move it earlier, or drop it if it "
            "no longer matters (2 reconstructed from the transcript; 1 untracked interviews left out)") in out
    assert "matches each of your turns against the guide's wording" in out


# --- the mock project, imported -------------------------------------------------------

DEMO = Path(__file__).resolve().parents[2] / "demo" / "claudictive-beta"

# Which guide questions each mock interviewer really asked, read by hand
# against context/survey.json and recorded in GROUND-TRUTH.json
# (`guide_questions_asked`). s6 counts only where voice was asked about
# neutrally; a pitch ("wouldn't voice be amazing mid-fight?") is recorded as a
# pitch, not s6. Itay never asked s4 or s7; s6 was asked in three.
ALL = {f"s{n}" for n in range(1, 11)}
TRULY_ASKED = {
    Path(entry["file"]).name: {q["id"] for q in entry["guide_questions_asked"]}
    for entry in json.loads((DEMO / "GROUND-TRUTH.json").read_text(encoding="utf-8"))["interviews"]
}


def test_the_answer_key_records_what_was_asked():
    assert TRULY_ASKED == {
        "01-yoni.txt": ALL - {"s6"}, "02-maya.txt": ALL - {"s6"}, "03-itay.txt": ALL - {"s4", "s6", "s7"},
        "04-shira.txt": ALL - {"s6"}, "05-daniel.txt": ALL - {"s6"}, "06-noa.txt": ALL - {"s6"},
        "07-avi.txt": ALL - {"s6"}, "08-tamar.txt": ALL, "09-omer.txt": ALL, "10-lior.txt": ALL - {"s6"},
        "11-gal.txt": ALL - {"s6"}, "12-roni.txt": ALL,
    }


# What the word-overlap matcher recovers from them. It never invents a
# question (checked below), but it misses most reworded ones: "ספרי לי על
# עצמך" is s1 in a feminine form, and the two English interviews share no
# word with a Hebrew guide at all.
RECONSTRUCTED = {"s1": 7, "s2": 2, "s3": 4, "s4": 2, "s5": 7, "s6": 1, "s7": 9, "s8": 6, "s9": 9, "s10": 5}
ENGLISH = {"05-daniel.txt", "10-lior.txt"}


def _import_demo(sessions_root, drop=lambda line: False) -> "dict[str, str]":
    """Each mock transcript imported as `python -m app import` would; returns
    session id -> file name. `drop` removes transcript lines first."""
    from datetime import datetime, timedelta

    from app.session import transcript_import as ti

    staging = sessions_root.parent / "staging"
    staging.mkdir()
    names = {}
    for n, source in enumerate(sorted((DEMO / "transcripts").glob("*.txt"))):
        copy = staging / source.name
        copy.write_text("".join(line for line in source.read_text(encoding="utf-8").splitlines(keepends=True)
                                if not drop(line)), encoding="utf-8")
        plan = ti.plan_file(copy, me="Interviewer")
        started = datetime(2026, 6, 15, 9) + timedelta(hours=n)
        meta = ti.session_metadata(plan, started=started, started_at_source="test", participant=None)
        names[ti.write_session(sessions_root, plan, meta, started=started).name] = source.name
    return names


def test_the_mock_interviews_reconstruct_only_questions_really_asked(tmp_path):
    from app.coach import prep_load
    from app.coach.context import load_survey

    survey = load_survey(DEMO / "context")
    names = _import_demo(tmp_path / "sessions")
    guides, asked_in, _, untracked, reconstructed = prep_load.interviews_and_coverage(
        tmp_path / "sessions", survey=survey)
    assert len(guides) == 12
    assert {names[s] for s in untracked} == ENGLISH
    assert len(reconstructed) == 10 and not set(reconstructed) & set(untracked)
    assert {q: len(asked_in.get(q, ())) for q in RECONSTRUCTED} == RECONSTRUCTED
    for question, sessions in asked_in.items():
        for session in sessions:
            assert question in TRULY_ASKED[names[session]], (question, names[session])

    items = {p.item_id: p for p in prep_mod.item_proposals(survey, asked_in, guides,
                                                           untracked=untracked, reconstructed=reconstructed)}
    assert all(p.action == prep_mod.KEEP for p in items.values())
    assert items["s7"].reason == ("asked in at least 9 of the 10 interviews that had it "
                                  "(10 reconstructed from the transcript; 2 untracked interviews left out)")


def test_a_question_cut_from_every_mock_interview_is_flagged_for_a_check_never_moved(tmp_path):
    from app.coach import prep_load
    from app.coach.context import load_survey

    survey = load_survey(DEMO / "context")
    # Every interviewer turn asking s7, the one-to-ten rating, removed.
    _import_demo(tmp_path / "sessions", drop=lambda line: line.startswith("Interviewer") and "עד עשר" in line)
    # The author page is offered nothing to apply: a check is not a change.
    assert prep_load.survey_proposals(survey, tmp_path / "sessions") == ()
    guides, asked_in, _, untracked, reconstructed = prep_load.interviews_and_coverage(
        tmp_path / "sessions", survey=survey)
    proposals = {p.item_id: p for p in prep_mod.item_proposals(survey, asked_in, guides,
                                                               untracked=untracked, reconstructed=reconstructed)}
    # All ten are reconstructed, so "never asked" would rest on the matcher's
    # silence alone (it missed s2 in 8 of 10 where it WAS asked).
    assert proposals["s7"].action == prep_mod.KEEP
    assert proposals["s7"].reason.startswith("not found in the 10 interviews that had it")
    assert "check by hand" in proposals["s7"].reason


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


def _topic(label, raised, judged, followed):
    return SimpleNamespace(label=tuple(label), tally=SimpleNamespace(
        raised_interviews=raised, judged_interviews=judged, followed_interviews=followed))


def test_a_raised_topic_is_proposed_only_when_mostly_walked_past():
    raised = prep_mod.raised_topics([
        _topic(["dead time"], 9, 9, 1),
        _topic(["overlay"], 5, 5, 5),     # followed up every time: already asked about
        _topic(["window"], 6, 6, 5),      # walked past once, followed up five times: in hand
        _topic(["even"], 4, 4, 2),        # as often followed as not: not proposed
        _topic(["voice"], 3, 0, 0),       # nothing could be judged: says nothing about you
        _topic(["price"], 4, 3, 1),
    ], 12)
    assert [t.label for t in raised] == ["dead time", "price"]
    assert raised[0].reason.startswith("raised without being asked in 9 of 12 interviews, followed up in 1:")
    assert "(1 could not be judged)" in raised[1].reason
