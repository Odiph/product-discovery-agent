"""The prompted judgment (app/coach/prompt_judge.py, app/coach/prompt_judge_store.py):
one model call deciding, from the interviewer's own words only, whether a
question asked about a topic. Offline: a fake client answers from the request."""

from __future__ import annotations

import json

import pytest

from app.coach import prompt_judge as pj
from app.coach import prompt_judge_store as store
from app.coach.stub import ToolUseResponse, tool_use_response

MODEL = "test-model-1"
ITEMS = (
    pj.item("What features would you like us to add?", ["How often do you use it?"], "wants voice input"),
    pj.item("Anything else?", ["How often?", "What features would you like?"], "wants themes"),
    pj.item("What do you usually do with it?", [], "dead time between matches"),
)


def _rows(request):
    return [json.loads(line) for line in request["messages"][0]["content"].splitlines() if line.startswith("{")]


def _answer_yes_for_features(request):
    return {"items": [{"id": row["id"], "asked": "features" in row["question"] + " ".join(row["earlier"])
                       and row["topic"] != "dead time between matches"} for row in _rows(request)]}


class FakeClient:
    def __init__(self, answer=_answer_yes_for_features, stop_reason="tool_use", tool=pj.TOOL_NAME):
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


def _judge(answer=_answer_yes_for_features, items=ITEMS, **kwargs):
    client = FakeClient(answer, **kwargs)
    return pj.judge(client, items, model=MODEL), client


# --- the request -----------------------------------------------------------------------


def test_the_request_carries_only_interviewer_words_and_labels():
    request = pj.assemble_request(ITEMS, model=MODEL)
    assert request["tool_choice"] == {"type": "tool", "name": pj.TOOL_NAME}
    rows = _rows(request)
    assert [set(row) for row in rows] == [{"id", "earlier", "question", "topic"}] * len(ITEMS)
    assert [(r["question"], tuple(r["earlier"]), r["topic"]) for r in rows] == [
        (i.question, i.earlier, i.topic) for i in ITEMS]


def test_identical_pairs_are_sent_once():
    twice = ITEMS + (pj.item("  What features would you  like us to add? ", ["How often do you use it?"],
                             "wants voice input"),)
    assert len(_rows(pj.assemble_request(twice, model=MODEL))) == len(ITEMS)
    # Same turn, another topic: a separate item.
    other = ITEMS + (pj.item(ITEMS[0].question, ITEMS[0].earlier, "the price is too high"),)
    assert len(_rows(pj.assemble_request(other, model=MODEL))) == len(ITEMS) + 1


# --- the answer ------------------------------------------------------------------------


def test_a_clean_answer_maps_back_to_items():
    judgment, client = _judge()
    assert len(client.requests) == 1
    assert [judgment.asked(i) for i in ITEMS] == [True, True, False]
    assert judgment.asked(pj.item("Never asked?", [], "x")) is None
    assert not judgment.dropped.any


def test_unknown_repeated_and_missing_answers_are_dropped_and_reported():
    def answer(request):
        return {"items": [{"id": "p1", "asked": True}, {"id": "p1", "asked": False}, {"id": "p99", "asked": True}]}

    judgment, _ = _judge(answer)
    assert judgment.asked(ITEMS[0]) is True
    assert judgment.asked(ITEMS[1]) is None
    assert judgment.dropped.unknown_ids == ("p99",)
    assert judgment.dropped.repeated_ids == ("p1",)
    assert judgment.dropped.unanswered_ids == ("p2", "p3")


@pytest.mark.parametrize("payload", [{}, {"items": "p1"}, {"items": [{"id": "p1"}]},
                                     {"items": [{"id": "p1", "asked": "yes"}]}, {"items": [{"id": 1, "asked": True}]}])
def test_a_malformed_answer_fails_whole(payload):
    with pytest.raises(pj.JudgeFailure):
        _judge(lambda request: payload)


def test_a_truncated_or_toolless_answer_is_not_trusted():
    with pytest.raises(pj.JudgeFailure):
        _judge(stop_reason="max_tokens")
    with pytest.raises(pj.JudgeFailure):
        _judge(tool="some_other_tool")


# --- the store -------------------------------------------------------------------------


def _written(tmp_path):
    judgment, _ = _judge()
    store.write(tmp_path, judgment)
    return judgment


def test_a_written_judgment_reads_back_fresh(tmp_path):
    judgment = _written(tmp_path)
    state = store.load(tmp_path, ITEMS, MODEL)
    assert state.status == store.FRESH
    assert [state.judgment.asked(i) for i in ITEMS] == [judgment.asked(i) for i in ITEMS]


def test_order_and_spacing_do_not_make_it_stale(tmp_path):
    _written(tmp_path)
    reordered = (pj.item(" What do you  usually do with it?", [], "dead time between matches"),) + ITEMS[:2]
    assert store.load(tmp_path, reordered, MODEL).status == store.FRESH


def test_no_file_is_absent(tmp_path):
    assert store.load(tmp_path, ITEMS, MODEL).status == store.ABSENT


@pytest.mark.parametrize("changed", [
    pj.item("What features would you like us to build?", ["How often do you use it?"], "wants voice input"),
    pj.item("What features would you like us to add?", ["How many times a week?"], "wants voice input"),
    pj.item("What features would you like us to add?", ["How often do you use it?"], "wants voice control"),
], ids=["question", "earlier turn", "topic"])
def test_a_changed_turn_or_topic_is_stale(tmp_path, changed):
    _written(tmp_path)
    state = store.load(tmp_path, (changed,) + ITEMS[1:], MODEL)
    assert state.status == store.STALE and "changed" in state.reason


def test_another_model_is_stale_and_says_which(tmp_path):
    _written(tmp_path)
    state = store.load(tmp_path, ITEMS, "other-model-2")
    assert state.status == store.STALE and MODEL in state.reason and "other-model-2" in state.reason


def test_a_changed_prompt_or_schema_is_stale(tmp_path, monkeypatch):
    _written(tmp_path)
    monkeypatch.setattr(pj, "_SYSTEM", pj._SYSTEM + " Be brief.")
    assert store.load(tmp_path, ITEMS, MODEL).status == store.STALE
    monkeypatch.undo()
    schema = pj._tool_schema()
    schema["description"] = "changed"
    monkeypatch.setattr(pj, "_tool_schema", lambda: schema)
    assert store.load(tmp_path, ITEMS, MODEL).status == store.STALE


@pytest.mark.parametrize("text", ["not json", "[]", json.dumps({"version": 99}), "\udcff"])
def test_an_unreadable_file_is_reported_and_not_used(tmp_path, text):
    path = tmp_path / store.CACHE_FILENAME
    if text == "\udcff":
        path.write_bytes(b"\xff\xfe\x00garbage")
    else:
        path.write_text(text, encoding="utf-8")
    state = store.load(tmp_path, ITEMS, MODEL)
    assert state.status == store.UNREADABLE and state.judgment is None and state.reason


@pytest.mark.parametrize("field, value", [("asked", "yes"), ("topic", 3), ("earlier", "one string"),
                                          ("question", "a question never sent")])
def test_a_well_keyed_but_malformed_file_is_unreadable(tmp_path, field, value):
    _written(tmp_path)
    path = tmp_path / store.CACHE_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["items"][0][field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    state = store.load(tmp_path, ITEMS, MODEL)
    assert state.status == store.UNREADABLE and state.judgment is None


@pytest.mark.parametrize("answers", [
    ((pj.PromptItem("Q?", (), "t"), True), (pj.PromptItem("Q?", (), "t"), False)),
    ((pj.PromptItem("  ", (), "t"), True),),
    ((pj.PromptItem("Q?", (), " "), True),),
    ((pj.PromptItem("Q?", (), "t"), "yes"),),
])
def test_the_writer_refuses_a_judgment_that_breaks_its_own_rules(tmp_path, answers):
    with pytest.raises(ValueError):
        store.write(tmp_path, pj.Judgment(model=MODEL, key="k", answers=answers))
    assert not (tmp_path / store.CACHE_FILENAME).exists()
