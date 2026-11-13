"""The follow-up judgment (app/coach/follow_judge.py, app/coach/follow_judge_store.py):
one model call deciding, from the interviewer's own next turns only, whether
a raised topic was followed up. Offline: a fake client answers from the request."""

from __future__ import annotations

import json

import pytest

from app.coach import follow_judge as fj
from app.coach import follow_judge_store as store
from app.coach.stub import ToolUseResponse, tool_use_response

MODEL = "test-model-1"
ITEMS = (
    fj.item("dead time between matches", [(1, "Great. Which features would you like?"),
                                          (2, "Wouldn't voice be amazing mid-match?")]),
    fj.item("the overlay covers the HUD", [(1, "Wait, what do you mean covered? When did it happen?")]),
    fj.item("wants themes", [(2, "Mm."), (3, "Would you pay for it monthly?")]),
)


def _rows(request):
    return [json.loads(line) for line in request["messages"][0]["content"].splitlines() if line.startswith("{")]


def _yes_when_asked_what_they_mean(request):
    return {"items": [{"id": row["id"], "followed": any("what do you mean" in t["text"] for t in row["turns"])}
                      for row in _rows(request)]}


class FakeClient:
    def __init__(self, answer=_yes_when_asked_what_they_mean, stop_reason="tool_use", tool=fj.TOOL_NAME):
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


def _judge(answer=_yes_when_asked_what_they_mean, items=ITEMS, **kwargs):
    client = FakeClient(answer, **kwargs)
    return fj.judge(client, items, model=MODEL), client


# --- the request -----------------------------------------------------------------------


def test_the_request_carries_only_topic_labels_and_numbered_turns():
    request = fj.assemble_request(ITEMS, model=MODEL)
    assert request["tool_choice"] == {"type": "tool", "name": fj.TOOL_NAME}
    rows = _rows(request)
    assert [set(row) for row in rows] == [{"id", "topic", "turns"}] * len(ITEMS)
    assert [(r["topic"], tuple((t["n"], t["text"]) for t in r["turns"])) for r in rows] == [
        (i.topic, i.turns) for i in ITEMS]


def test_identical_items_are_sent_once_and_the_turn_number_tells_items_apart():
    twice = ITEMS + (fj.item(" the overlay  covers the HUD", [(1, "Wait, what do you mean covered?  When did it happen?")]),)
    assert len(_rows(fj.assemble_request(twice, model=MODEL))) == len(ITEMS)
    later = ITEMS + (fj.item(ITEMS[1].topic, [(2, ITEMS[1].turns[0][1])]),)
    assert len(_rows(fj.assemble_request(later, model=MODEL))) == len(ITEMS) + 1


def test_an_item_with_no_turn_is_never_sent():
    assert fj.unique_items([fj.item("a topic", []), fj.item("a topic", [(1, "  ")])]) == ()


# --- the answer ------------------------------------------------------------------------


def test_a_clean_answer_maps_back_to_items():
    judgment, client = _judge()
    assert len(client.requests) == 1
    assert [judgment.followed(i) for i in ITEMS] == [False, True, False]
    assert judgment.followed(fj.item("never sent", [(1, "Why?")])) is None
    assert not judgment.dropped.any


def test_unknown_repeated_and_missing_answers_are_dropped_and_reported():
    def answer(request):
        return {"items": [{"id": "f1", "followed": True}, {"id": "f1", "followed": False},
                          {"id": "f99", "followed": True}]}

    judgment, _ = _judge(answer)
    assert judgment.followed(ITEMS[0]) is True
    assert judgment.followed(ITEMS[1]) is None
    assert judgment.dropped.unknown_ids == ("f99",)
    assert judgment.dropped.repeated_ids == ("f1",)
    assert judgment.dropped.unanswered_ids == ("f2", "f3")


@pytest.mark.parametrize("payload", [{}, {"items": "f1"}, {"items": [{"id": "f1"}]},
                                     {"items": [{"id": "f1", "asked": True}]},
                                     {"items": [{"id": "f1", "followed": "yes"}]},
                                     {"items": [{"id": 1, "followed": True}]}])
def test_a_malformed_answer_fails_whole_and_names_the_judgment(payload):
    with pytest.raises(fj.JudgeFailure, match="follow-up judgment failed"):
        _judge(lambda request: payload)


def test_a_truncated_or_toolless_answer_is_not_trusted():
    with pytest.raises(fj.JudgeFailure):
        _judge(stop_reason="max_tokens")
    with pytest.raises(fj.JudgeFailure):
        _judge(tool="judge_questions_against_topics")


# --- the store -------------------------------------------------------------------------


def _written(tmp_path):
    judgment, _ = _judge()
    store.write(tmp_path, judgment)
    return judgment


def test_a_written_judgment_reads_back_fresh(tmp_path):
    judgment = _written(tmp_path)
    state = store.load(tmp_path, ITEMS, MODEL)
    assert state.status == store.FRESH
    assert [state.judgment.followed(i) for i in ITEMS] == [judgment.followed(i) for i in ITEMS] == [False, True, False]


def test_order_and_spacing_do_not_make_it_stale(tmp_path):
    _written(tmp_path)
    reordered = (fj.item("wants  themes", [(2, "Mm."), (3, " Would you pay for it monthly?")]),) + ITEMS[:2]
    assert store.load(tmp_path, reordered, MODEL).status == store.FRESH


def test_no_file_is_absent(tmp_path):
    assert store.load(tmp_path, ITEMS, MODEL).status == store.ABSENT


@pytest.mark.parametrize("changed", [
    fj.item("the overlay hides the HUD", ITEMS[1].turns),
    fj.item(ITEMS[1].topic, [(1, "Wait, what do you mean covered?")]),
    fj.item(ITEMS[1].topic, [(2, ITEMS[1].turns[0][1])]),
], ids=["topic", "turn text", "turn number"])
def test_a_changed_turn_or_topic_is_stale(tmp_path, changed):
    _written(tmp_path)
    state = store.load(tmp_path, (ITEMS[0], changed, ITEMS[2]), MODEL)
    assert state.status == store.STALE and "changed" in state.reason


def test_another_model_is_stale_and_says_which(tmp_path):
    _written(tmp_path)
    state = store.load(tmp_path, ITEMS, "other-model-2")
    assert state.status == store.STALE and MODEL in state.reason and "other-model-2" in state.reason


def test_a_changed_prompt_is_stale(tmp_path, monkeypatch):
    _written(tmp_path)
    monkeypatch.setattr(fj, "_SYSTEM", fj._SYSTEM + " Be brief.")
    assert store.load(tmp_path, ITEMS, MODEL).status == store.STALE


@pytest.mark.parametrize("text", ["not json", "[]", json.dumps({"version": 99})])
def test_an_unreadable_file_is_reported_and_not_used(tmp_path, text):
    (tmp_path / store.CACHE_FILENAME).write_text(text, encoding="utf-8")
    state = store.load(tmp_path, ITEMS, MODEL)
    assert state.status == store.UNREADABLE and state.judgment is None and state.reason


@pytest.mark.parametrize("field, value", [("followed", "yes"), ("topic", 3), ("turns", "one string"),
                                          ("turns", [{"n": "1", "text": "x"}]),
                                          ("topic", "a topic never sent")])
def test_a_well_keyed_but_malformed_file_is_unreadable(tmp_path, field, value):
    _written(tmp_path)
    path = tmp_path / store.CACHE_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["items"][0][field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    state = store.load(tmp_path, ITEMS, MODEL)
    assert state.status == store.UNREADABLE and state.judgment is None


@pytest.mark.parametrize("answers", [
    ((fj.FollowItem("t", ((1, "Q?"),)), True), (fj.FollowItem("t", ((1, "Q?"),)), False)),
    ((fj.FollowItem(" ", ((1, "Q?"),)), True),),
    ((fj.FollowItem("t", ()), True),),
    ((fj.FollowItem("t", ((1, " "),)), True),),
    ((fj.FollowItem("t", ((1, "Q?"),)), "yes"),),
])
def test_the_writer_refuses_a_judgment_that_breaks_its_own_rules(tmp_path, answers):
    with pytest.raises(ValueError):
        store.write(tmp_path, fj.Judgment(model=MODEL, key="k", answers=answers))
    assert not (tmp_path / store.CACHE_FILENAME).exists()
