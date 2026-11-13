"""`missed --group model` decides "followed up" by the model's judgment of the
interviewer's own next turns (app/coach/follow_judge.py, app/followed_cli.py).

The dataset tests read the SYNTHETIC mock interviews in demo/claudictive-beta/
through test_missed_prompted's loader, with a hand-written follow-up judge
that answers exactly as GROUND-TRUTH.json's `followed_up` says. Offline
throughout: the command tests use a fake client.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import main as main_mod
from app.coach import follow_judge as fj
from app.coach import follow_judge_store as store
from app.coach import missed as missed_mod
from app.coach import prompt_judge as pj
from app.coach import topics as topics_mod
from app.coach import walked_past as wp
from app.coach.stub import ToolUseResponse, tool_use_response
from app.tests import test_missed_prompted as base
from app.tests.test_missed_prompted import DEAD, HUD, PLANTED, demo, node  # noqa: F401 -- fixtures


def _follow_key(demo):
    """FollowItem -> the answer key's `followed_up`, for the planted topics."""
    scripted = missed_mod.script_keys(demo.survey)
    answers = {}
    for entry in demo.truth["interviews"]:
        sid = Path(entry["file"]).name[:2]
        for label, key in PLANTED.items():
            if not entry[key]["present"]:
                continue
            position = next(p for p, t in enumerate(demo.turns[sid]) if entry[key]["turn"] in t.seqs)
            turns = missed_mod.follow_turns(demo.turns[sid], position, scripted)
            if turns:
                answers[fj.item(label, turns)] = entry[key]["followed_up"]
    return answers


def _find(demo, follow_judge, **extra):
    judge, _ = base._answer_key(demo)
    return missed_mod.find(demo.claims, demo.turns, judge=judge, follow_judge=follow_judge,
                           **{**base._kwargs(demo), **extra})


# --- the real mock interviews, judged as the answer key says --------------------------


def test_every_item_is_a_label_and_the_interviewers_own_turns(demo):
    items = missed_mod.follow_items(demo.claims, demo.turns, **base._kwargs(demo))
    # Control B is below the floor, never a topic: nothing about it is sent.
    assert {i for i in _follow_key(demo) if i.topic != base.HOTKEY} <= set(items)
    assert base.HOTKEY not in {i.topic for i in items}
    said = {" ".join(t.text.split()) for turns in demo.turns.values() for t in turns if t.speaker == wp.INTERVIEWER}
    interviewee = {" ".join(t.text.split()) for turns in demo.turns.values() for t in turns
                   if t.speaker == wp.INTERVIEWEE}
    assert items
    for entry in items:
        texts = {text for _, text in entry.turns}
        assert texts <= said and not texts & interviewee
        assert entry.topic in {group.label for group in demo.groups}


def test_the_pitch_in_05_is_in_what_the_model_is_shown(demo):
    """The fixture can exhibit the property: the pitch the word rule counts
    as a follow-up is one of the turns sent for 05's dead-time occurrence."""
    lexical = base._labels(base._find(demo, base._answer_key(demo)[0]).topics)[DEAD]
    assert [o.session_id for o in lexical.occurrences if o.followed] == ["05"]
    sent = [i for i in _follow_key(demo) if i.topic == DEAD and any("Claude" in text for _, text in i.turns)]
    assert sent, "no dead-time item carries the pitch"


def test_judged_by_the_answer_key_the_dead_time_is_followed_up_in_none(demo):
    key = _follow_key(demo)
    report = _find(demo, key.get)
    headlined = base._labels(report.topics)
    dead, hud = headlined[DEAD].tally, headlined[HUD].tally
    assert (dead.raised_interviews, dead.followed_interviews) == (8, 0)
    assert (hud.raised_interviews, hud.followed_interviews) == (5, 5)
    assert not any(o.follow_unanswered for label in (DEAD, HUD) for o in headlined[label].occurrences)


def test_a_judge_that_says_no_to_everything_takes_control_a_to_zero(demo):
    """The judge decides both ways: it is not only a filter over the word rule."""
    hud = base._labels(_find(demo, lambda item: False).topics)[HUD].tally
    assert (hud.raised_interviews, hud.followed_interviews) == (5, 0)


def test_a_judge_that_says_yes_to_everything_follows_the_dead_time_everywhere(demo):
    dead = base._labels(_find(demo, lambda item: True).topics)[DEAD].tally
    assert dead.followed_interviews == dead.judged_interviews > 1


def test_no_answer_keeps_the_word_rule_and_says_so(demo):
    report = _find(demo, lambda item: None)
    dead = base._labels(report.topics)[DEAD]
    assert (dead.tally.raised_interviews, dead.tally.followed_interviews) == (8, 1)
    assert all(o.follow_unanswered for o in dead.occurrences if o.followed is not None)


def test_a_flagged_turn_is_never_sent(demo):
    """05's pitch at seq 19, flagged by the critic, is left out of the item."""
    flagged = {"05": frozenset({19})}
    with_flag = missed_mod.follow_items(demo.claims, demo.turns, flagged=flagged, **base._kwargs(demo))
    without = missed_mod.follow_items(demo.claims, demo.turns, **base._kwargs(demo))
    pitch = next(t.text for t in demo.turns["05"] if 19 in t.seqs)
    carried = lambda items: [i for i in items if any(text == " ".join(pitch.split()) for _, text in i.turns)]  # noqa: E731
    assert carried(without) and not carried(with_flag)


def test_follow_turns_reads_the_same_window_as_the_word_rule():
    def turn(seq, speaker, text):
        return wp.Turn(speaker=speaker, seqs=(seq,), text=text, end_s=None)

    sequence = [turn(1, wp.INTERVIEWEE, "I mostly use it while waiting in the queue."),
                turn(2, wp.INTERVIEWER, "Mm."),
                turn(3, wp.INTERVIEWEE, "Yes."),
                turn(4, wp.INTERVIEWER, "Which features would you like us to add?"),
                turn(5, wp.INTERVIEWER, "And would you pay for this every month?"),
                turn(6, wp.INTERVIEWER, "Tell me more about the queue you mentioned.")]
    assert missed_mod.follow_turns(sequence, 0) == (
        (1, "Mm."), (2, "Which features would you like us to add?"), (3, "And would you pay for this every month?"))


def _turn(seq, speaker, text):
    return wp.Turn(speaker=speaker, seqs=(seq,), text=text, end_s=None)


def test_a_left_out_turn_still_counts_in_the_numbering():
    """A bare "Why?" after a flagged pitch must not look like the very next turn."""
    sequence = [_turn(1, wp.INTERVIEWEE, "I mostly use it while waiting in the queue."),
                _turn(2, wp.INTERVIEWER, "Would you not love to talk to it during a fight?"),
                _turn(3, wp.INTERVIEWER, "Why?"),
                _turn(4, wp.INTERVIEWER, "Which features would you like us to add next?"),
                _turn(5, wp.INTERVIEWER, "And how often do you open it each week?")]
    scripted = missed_mod.script_keys(["Which features would you like us to add next?"])
    # The pitch and the guide question are the window's two full turns, as
    # in the word rule: both are left out, and the last turn is past it.
    assert missed_mod.follow_turns(sequence, 0, scripted, frozenset({2})) == ((2, "Why?"),)
    assert missed_mod.follow_turns(sequence, 0) == (
        (1, sequence[1].text), (2, "Why?"), (3, sequence[3].text))


def _one_topic(sequences):
    claims = [missed_mod.CitedClaim(fact_id=f"c{n}", session_id=sid, claim=f"queue {n}", bearings=(), seqs=(1,))
              for n, sid in enumerate(sequences)]
    groups = [topics_mod.TopicGroup(label="waiting in the queue", fact_ids=tuple(c.fact_id for c in claims))]
    return claims, groups


def test_an_occurrence_the_word_rule_could_not_judge_is_never_sent():
    """No interviewer turn after the offer, and an offer in the interviewer's
    own mouth: neither is the model's to decide."""
    offer = "I mostly use it while waiting in the queue."
    sequences = {
        "a": [_turn(1, wp.INTERVIEWEE, offer)],
        "b": [_turn(1, wp.INTERVIEWER, offer), _turn(2, wp.INTERVIEWER, "Tell me more about that queue please.")],
        "c": [_turn(1, wp.INTERVIEWEE, offer), _turn(2, wp.INTERVIEWER, "How many friends join you on weekends?")],
    }
    claims, groups = _one_topic(sequences)
    asked = []
    report = missed_mod.find(claims, sequences, groups=groups, follow_judge=lambda i: asked.append(i) or True)
    assert [turns for turns in (i.turns for i in asked)] == [((1, "How many friends join you on weekends?"),)]
    outcomes = {o.session_id: o.outcome for t in (*report.topics, *report.asked_topics) for o in t.occurrences}
    assert outcomes == {"a": missed_mod.NO_QUESTION, "b": missed_mod.NOT_INTERVIEWEE, "c": missed_mod.FOLLOWED}


# --- the command ---------------------------------------------------------------------


class _Client:
    """One client for all three calls, answering by the tool each request forces."""

    def __init__(self, followed=True, drop=False):
        self.followed, self.drop, self.requests = followed, drop, []

    def with_options(self, *, timeout):
        return self

    @property
    def messages(self):
        return self

    def create(self, **request):
        self.requests.append(request)
        tool = request["tool_choice"]["name"]
        rows = base._rows(request)
        if tool == topics_mod.TOOL_NAME:
            payload = {"topics": [{"label": DEAD, "claim_ids": [row["id"] for row in rows]}]}
        elif tool == pj.TOOL_NAME:
            payload = {"items": [{"id": row["id"], "asked": False} for row in rows]}
        else:
            payload = {"items": [] if self.drop else [{"id": row["id"], "followed": self.followed} for row in rows]}
        response = tool_use_response(tool, payload)
        return ToolUseResponse(content=response.content, stop_reason="tool_use")


@pytest.fixture
def client(node, monkeypatch):  # noqa: F811 -- the imported fixture
    client = _Client()
    monkeypatch.setattr(main_mod.reasoning_client, "build_client", lambda: client)
    return client


def test_without_yes_the_command_previews_the_follow_up_call_and_calls_nothing(node, client, capsys):  # noqa: F811
    base._cache_grouping(node)
    assert main_mod.main(["missed", "--group", "model"]) == 0
    out = capsys.readouterr().out
    assert ("One call to test-model-1 to judge whether you followed up on each topic: 1 topic occurrences, "
            "made of 1 of your own interview turns") in out
    assert "    your turn 1 after it: How many friends join your squad on weekends?" in out
    assert "Followed up: by word match between your next questions and the topic -- the model was not asked" in out
    assert base.INTERVIEWEE_SAID not in out
    assert not client.requests
    assert not (node.context / store.CACHE_FILENAME).exists()


def test_with_yes_the_model_decides_and_never_sees_the_interviewee(node, client, capsys):  # noqa: F811
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    out = capsys.readouterr().out
    assert [r["tool_choice"]["name"] for r in client.requests] == [topics_mod.TOOL_NAME, pj.TOOL_NAME, fj.TOOL_NAME]
    sent = json.dumps(client.requests[2], ensure_ascii=False)
    assert base.INTERVIEWEE_SAID not in sent
    for _, _, claim in base.ROWS:
        assert claim not in sent
    assert ("Followed up: by the model's reading of your own next turns (test-model-1, just made, saved to "
            "context/followed.json: 1 of 1 topic occurrences followed up).") in out
    # The word rule says walked past (no shared word); the model said followed.
    assert "In 3 of 3 interviews, interviewees raised dead time between matches without being asked. " \
           "You followed up in 3." in out

    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    again = capsys.readouterr().out
    assert len(client.requests) == 3, "all three caches are fresh: no further call"
    assert "cached in context/followed.json" in again


def test_an_unanswered_item_falls_back_to_the_word_rule_and_says_so(node, client, capsys):  # noqa: F811
    client.drop = True
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "1 left unanswered, decided by word match" in out
    assert "id(s) left unanswered, decided by word match: f1" in out
    assert "You followed up in 0." in out
    assert "walked past (the model gave no follow-up answer; decided by word match)" in out


def test_prep_and_the_mirror_name_the_follow_up_rule_from_the_cache_alone(node, client, capsys):  # noqa: F811
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    capsys.readouterr()
    for command in ("prep", "mirror"):
        assert main_mod.main([command]) == 0
        out = capsys.readouterr().out
        assert "Followed up: by the model's reading of your own next turns (test-model-1, cached in" in out
    assert len(client.requests) == 3


def test_other_groupings_never_call_the_follow_up_judge(node, client, capsys):  # noqa: F811
    base._cache_grouping(node)
    assert main_mod.main(["missed"]) == 0
    assert "Followed up: by word match between your next questions and the topic." in capsys.readouterr().out
    for command in ("prep", "mirror"):
        assert main_mod.main([command]) == 0
        assert ("Followed up: by word match between your next questions and the topic -- the model was not "
                "asked (no judgment is cached yet).") in capsys.readouterr().out
    assert not client.requests
