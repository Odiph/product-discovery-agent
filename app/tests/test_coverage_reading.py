"""The coverage reading (app/coach/coverage_judge.py, app/coach/coverage_store.py,
app/coverage_cli.py) and how `prep` uses it: which guide questions an
imported interview really asked, read by the model once from the
interviewer's own turns; `prep` reads the cache and never calls a model.

Offline throughout: a fake client answers from GROUND-TRUTH.json's
`guide_questions_asked` for the SYNTHETIC mock interviews."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main as main_mod
from app.coach import coverage_judge as cj
from app.coach import coverage_store as store
from app.coach import prep as prep_mod
from app.coach import prep_load
from app.coach.context import SurveyItem, load_survey
from app.coach.stub import ToolUseResponse, tool_use_response
from app.tests.test_prep import ENGLISH, _import_demo

MODEL = "test-model-1"
DEMO = Path(__file__).resolve().parents[2] / "demo" / "claudictive-beta"
TRUTH = json.loads((DEMO / "GROUND-TRUTH.json").read_text(encoding="utf-8"))
QUESTIONS = (("s1", "How was the onboarding?"), ("s2", "What would you pay for it?"))
TURNS = {"A": ("Thanks for coming.", "So, how did the install go for you?"), "B": ("How much would you pay?",)}


def _content_rows(request):
    return [json.loads(line) for line in request["messages"][0]["content"].splitlines() if line.startswith("{")]


class FakeClient:
    def __init__(self, answer, stop_reason="tool_use", tool=cj.TOOL_NAME):
        self.answer, self.stop_reason, self.tool, self.requests = answer, stop_reason, tool, []

    def with_options(self, *, timeout):
        return self

    @property
    def messages(self):
        return self

    def create(self, **request):
        self.requests.append(request)
        response = tool_use_response(self.tool, self.answer(request))
        return ToolUseResponse(content=response.content, stop_reason=self.stop_reason)


def _small_answer(request):
    return {"asked": [{"turn_id": "i1-t2", "question_ids": ["q1"]}, {"turn_id": "i2-t1", "question_ids": ["q2"]}]}


def _read(answer=_small_answer, **kwargs):
    client = FakeClient(answer, **kwargs)
    return cj.read(client, QUESTIONS, TURNS, model=MODEL), client


# --- the request and the answer ---------------------------------------------------------


def test_the_request_carries_the_guide_and_the_interviewers_turns_only():
    request = cj.assemble_request(QUESTIONS, TURNS, model=MODEL)
    assert request["tool_choice"] == {"type": "tool", "name": cj.TOOL_NAME}
    rows = _content_rows(request)
    assert [set(r) for r in rows] == [{"id", "question"}] * 2 + [{"id", "turn"}] * 3
    assert [r["turn"] for r in rows[2:]] == [*TURNS["A"], *TURNS["B"]]


def test_a_clean_answer_maps_back_to_sessions_and_survey_ids():
    coverage, client = _read()
    assert len(client.requests) == 1
    assert coverage.as_dict() == {"A": ("s1",), "B": ("s2",)}
    assert not coverage.dropped.any


def test_unknown_and_repeated_ids_are_dropped_and_named():
    def answer(request):
        return {"asked": [{"turn_id": "i1-t2", "question_ids": ["q1", "q9"]},
                          {"turn_id": "i1-t2", "question_ids": ["q2"]}, {"turn_id": "i7-t1", "question_ids": []}]}

    coverage, _ = _read(answer)
    assert coverage.as_dict() == {"A": ("s1",), "B": ()}
    assert coverage.dropped.unknown_ids == ("q9", "i7-t1")
    assert coverage.dropped.repeated_turns == ("i1-t2",)


@pytest.mark.parametrize("payload", [{}, {"asked": "x"}, {"asked": [{"turn_id": "i1-t1"}]},
                                     {"asked": [{"turn_id": "i1-t1", "question_ids": [1]}]}])
def test_a_malformed_answer_fails_whole(payload):
    with pytest.raises(cj.CoverageFailure):
        _read(lambda request: payload)


def test_a_truncated_or_toolless_answer_is_not_trusted():
    with pytest.raises(cj.CoverageFailure):
        _read(stop_reason="max_tokens")
    with pytest.raises(cj.CoverageFailure):
        _read(tool="other")


# --- the store --------------------------------------------------------------------------


def _written(tmp_path):
    coverage, _ = _read()
    store.write(tmp_path, coverage, {"s1", "s2"})
    return coverage


def test_a_written_reading_is_fresh_and_reads_back(tmp_path):
    coverage = _written(tmp_path)
    state = store.load(tmp_path, QUESTIONS, TURNS, MODEL)
    assert state.status == store.FRESH and state.coverage.as_dict() == coverage.as_dict()


@pytest.mark.parametrize("questions, turns, model", [
    (QUESTIONS, {**TURNS, "B": ("How much would you pay monthly?",)}, MODEL),
    (QUESTIONS, {**TURNS, "C": ("A new interview?",)}, MODEL),
    ((QUESTIONS[0], ("s2", "Would you pay?")), TURNS, MODEL),
    (QUESTIONS, TURNS, "other-model-2"),
], ids=["changed turn", "new interview", "changed survey", "other model"])
def test_any_change_makes_it_stale(tmp_path, questions, turns, model):
    _written(tmp_path)
    assert store.load(tmp_path, questions, turns, model).status == store.STALE


def test_a_changed_prompt_is_stale(tmp_path, monkeypatch):
    _written(tmp_path)
    monkeypatch.setattr(cj, "_SYSTEM", cj._SYSTEM + " Be brief.")
    assert store.load(tmp_path, QUESTIONS, TURNS, MODEL).status == store.STALE


@pytest.mark.parametrize("text", ["not json", "[]", json.dumps({"version": 9})])
def test_an_unreadable_file_is_reported(tmp_path, text):
    (tmp_path / store.CACHE_FILENAME).write_text(text, encoding="utf-8")
    state = store.load(tmp_path, QUESTIONS, TURNS, MODEL)
    assert state.status == store.UNREADABLE and state.coverage is None and state.reason


def test_a_well_keyed_file_naming_a_question_not_in_the_survey_is_unreadable(tmp_path):
    _written(tmp_path)
    path = tmp_path / store.CACHE_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sessions"][0]["asked"] = ["s99"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.load(tmp_path, QUESTIONS, TURNS, MODEL).status == store.UNREADABLE


@pytest.mark.parametrize("asked", [(("A", ("s1",)), ("A", ())), (("A", ("s1", "s1")),), (("A", ("s9",)),),
                                   ((" ", ()),)])
def test_the_writer_refuses_a_reading_that_breaks_its_own_rules(tmp_path, asked):
    with pytest.raises(ValueError):
        store.write(tmp_path, cj.Coverage(model=MODEL, key="k", asked=asked), {"s1", "s2"})
    assert not (tmp_path / store.CACHE_FILENAME).exists()


# --- the mock interviews, imported --------------------------------------------------------


def _truth_answer(request):
    """Answers as the answer key says: each guide question at the turn it was asked."""
    interviews = sorted(TRUTH["interviews"], key=lambda e: e["file"])
    content = request["messages"][0]["content"]
    q_alias = {row["question"]: row["id"] for row in _content_rows(request) if "question" in row}
    survey = {e["id"]: e["text"] for e in json.loads((DEMO / "context" / "survey.json").read_text(encoding="utf-8"))}
    asked = []
    for n, entry in enumerate(interviews, start=1):
        lines = (DEMO / entry["file"]).read_text(encoding="utf-8").splitlines()
        interviewer = [number for number, line in enumerate(lines, start=1) if line.startswith("Interviewer ")]
        for q in entry["guide_questions_asked"]:
            alias = f"i{n}-t{interviewer.index(q['turn']) + 1}"
            assert f'"id": "{alias}"' in content
            asked.append({"turn_id": alias, "question_ids": [q_alias[" ".join(survey[q["id"]].split())]]})
    return {"asked": asked}


@pytest.fixture
def imported(tmp_path, monkeypatch):
    sessions, context = tmp_path / "sessions", tmp_path / "context"
    context.mkdir()
    (context / "survey.json").write_text((DEMO / "context" / "survey.json").read_text(encoding="utf-8"),
                                         encoding="utf-8")
    names = _import_demo(sessions)
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(sessions))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(context))
    monkeypatch.setenv("EXTRACT_MODEL", MODEL)
    client = FakeClient(_truth_answer)
    monkeypatch.setattr(main_mod.reasoning_client, "build_client", lambda: client)
    return SimpleNamespace(sessions=sessions, context=context, names=names, client=client,
                           survey=load_survey(context))


def test_the_coverage_preview_sends_nothing_and_never_the_interviewee(imported, capsys):
    assert main_mod.main(["coverage"]) == 0
    out = capsys.readouterr().out
    assert ("One call to test-model-1 to read which guide questions you asked: 12 interview(s) with no live "
            "coverage record") in out
    assert "Never anything the interviewee said." in out
    assert "Nothing called (nothing is cached yet). Re-run with --yes to read them." in out
    assert not imported.client.requests
    assert not (imported.context / store.CACHE_FILENAME).exists()


def test_coverage_yes_reads_once_and_prep_then_uses_it_without_a_model(imported, capsys, monkeypatch):
    assert main_mod.main(["coverage", "--yes"]) == 0
    assert len(imported.client.requests) == 1
    sent = imported.client.requests[0]["messages"][0]["content"]
    for entry in TRUTH["interviews"]:
        for line in (DEMO / entry["file"]).read_text(encoding="utf-8").splitlines():
            said = line.split(": ", 1)[1]
            # Long enough not to be a phrase the interviewer also says ("כן.").
            if not line.startswith("Interviewer ") and len(said.split()) >= 4:
                assert said not in sent, "an interviewee turn was sent"
    out = capsys.readouterr().out
    assert "saved to context/coverage.json" in out
    assert main_mod.main(["coverage"]) == 0
    assert "already read by test-model-1" in capsys.readouterr().out
    assert len(imported.client.requests) == 1

    def _no_client():
        raise AssertionError("prep built a model client")

    monkeypatch.setattr(main_mod.reasoning_client, "build_client", _no_client)
    assert main_mod.main(["prep"]) == 0
    out = capsys.readouterr().out
    # s7 was asked in 11 of 12 (never by 03); the word match found it in 9.
    assert ("keep: asked in at least 11 of the 12 interviews that had it (12 from the model's reading of the "
            "transcript)") in out
    assert "from the model's reading of the transcript (context/coverage.json" in out


def test_with_the_answer_keys_reading_every_question_is_counted_as_really_asked(imported):
    reading = prep_load.model_reading(imported.context, imported.sessions, imported.survey)
    assert reading.asked is None, "nothing cached yet"
    questions, turns = cj.questions(imported.survey), prep_load.untracked_turns(imported.sessions)
    answer = _truth_answer(cj.assemble_request(questions, turns, model=MODEL))
    coverage = cj.validate([(a["turn_id"], a["question_ids"]) for a in answer["asked"]], questions, turns,
                           model=MODEL)
    assert not coverage.dropped.any
    store.write(imported.context, coverage)
    reading = prep_load.model_reading(imported.context, imported.sessions, imported.survey)
    guides, asked_in, _, untracked, reconstructed = prep_load.interviews_and_coverage(
        imported.sessions, survey=imported.survey, reading=reading.asked)
    assert untracked == [] and len(reconstructed) == 12, "the English interviews are read too"
    truly = {Path(e["file"]).name: {q["id"] for q in e["guide_questions_asked"]} for e in TRUTH["interviews"]}
    for question, sessions in asked_in.items():
        assert {imported.names[s] for s in sessions} == {n for n, ids in truly.items() if question in ids}
    assert {imported.names[s] for s in reconstructed} >= ENGLISH


def test_the_models_silence_is_still_one_way(imported):
    """A question the reading never found stays "check by hand", never "never
    asked": no measured recall justifies reading the model's silence."""
    survey = imported.survey
    turns = prep_load.untracked_turns(imported.sessions)
    nothing = cj.validate([], cj.questions(survey), turns, model=MODEL)
    store.write(imported.context, nothing)
    reading = prep_load.model_reading(imported.context, imported.sessions, survey)
    assert reading.asked is not None and not any(reading.asked.values())
    guides, asked_in, _, untracked, reconstructed = prep_load.interviews_and_coverage(
        imported.sessions, survey=survey, reading=reading.asked)
    items = prep_mod.item_proposals(survey, asked_in, guides, untracked=untracked, reconstructed=reconstructed,
                                    read_by_model=set(reading.asked))
    assert all(p.action == prep_mod.KEEP and "check by hand" in p.reason for p in items)
    assert "the model's reading of the transcript can miss one too" in items[0].reason


def test_a_stale_reading_falls_back_to_the_word_match_and_says_why(imported, capsys):
    survey = imported.survey
    turns = prep_load.untracked_turns(imported.sessions)
    store.write(imported.context, cj.validate([], cj.questions(survey), turns, model="older-model"))
    reading = prep_load.model_reading(imported.context, imported.sessions, survey)
    assert reading.asked is None and "stale" in reading.note
    assert main_mod.main(["prep"]) == 0
    out = capsys.readouterr().out
    assert "context/coverage.json is stale" in out and "reconstructed from the transcript" in out


def test_the_recall_measure_scores_the_answer_keys_reading_perfectly(imported):
    from benchmark import coverage_recall

    assert main_mod.main(["coverage", "--yes"]) == 0
    assert coverage_recall.measure(imported.context.parent) == {"really_asked": 109, "found": 109, "correct": 109}


def test_the_label_names_the_model_only_for_sessions_it_read():
    survey = [SurveyItem(id="q1", order=0, text="x")]
    guides = {"M1": None, "W1": None}
    (item,) = prep_mod.item_proposals(survey, {"q1": ["M1", "W1"]}, guides, reconstructed={"M1", "W1"},
                                      read_by_model={"M1"})
    assert item.reason == ("asked in at least 2 of the 2 interviews that had it (1 from the model's reading of "
                           "the transcript; 1 reconstructed from the transcript)")


def test_prep_reads_the_cache_the_judge_model_wrote(imported, capsys, monkeypatch):
    # `coverage` writes with JUDGE_MODEL; prep must check freshness against
    # the same model, or it never uses the reading (2026-11-11: it checked
    # the extract model and fell back to the word match every time).
    monkeypatch.setenv("JUDGE_MODEL", MODEL)
    monkeypatch.setenv("EXTRACT_MODEL", "some-other-extract-model")
    assert main_mod.main(["coverage", "--yes"]) == 0
    capsys.readouterr()
    assert main_mod.main(["prep"]) == 0
    assert "12 from the model's reading of the transcript" in capsys.readouterr().out
