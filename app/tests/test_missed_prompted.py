"""`missed --group model` decides "prompted" by the model's judgment of the
interviewer's own turns (app/coach/prompt_judge.py, app/prompted_cli.py).

The dataset tests read the SYNTHETIC mock interviews in demo/claudictive-beta/
with claims placed where GROUND-TRUTH.json puts each occurrence, and a
hand-written judge that answers exactly as the answer key says. Offline
throughout: the command tests use a fake client.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main as main_mod
from app.coach import missed as missed_mod
from app.coach import prompt_judge as pj
from app.coach import prompt_judge_store as store
from app.coach import topics as topics_mod
from app.coach import topics_store
from app.coach import walked_past as wp
from app.coach.stub import ToolUseResponse, tool_use_response
from app.kb.spoken import speaker_text_turns

MODEL = "test-model-1"
DEMO = Path(__file__).resolve().parents[2] / "demo" / "claudictive-beta"

DEAD = "dead time between matches"
HUD = "the overlay covers the HUD"
HOTKEY = "the hotkey collides with another binding"
VOICE = "wants voice input"
THEMES = "wants themes"
PRICE = "unsure about paying"
PLANTED = {DEAD: "between_rounds_aside", HUD: "control_a_overlay_covers_hud", HOTKEY: "control_b_hotkey_collision"}
ASKED = {VOICE: "voice", THEMES: "themes", PRICE: "price"}


def _demo_turns(path):
    records = [{"kind": "segment", "seq": number, "text": turn.text,
                "speaker": wp.INTERVIEWER if turn.speaker == "Interviewer" else wp.INTERVIEWEE}
               for number, turn in enumerate(speaker_text_turns(path.read_text(encoding="utf-8")), start=1)]
    return wp.turns(records)


@functools.lru_cache(maxsize=1)
def _load_demo():
    truth = json.loads((DEMO / "GROUND-TRUTH.json").read_text(encoding="utf-8"))
    survey = tuple(e["text"] for e in json.loads((DEMO / "context" / "survey.json").read_text(encoding="utf-8")))
    turns, occurrences = {}, {label: [] for label in (*PLANTED, *ASKED)}
    for entry in truth["interviews"]:
        sid = Path(entry["file"]).name[:2]
        turns[sid] = _demo_turns(DEMO / entry["file"])
        for label, key in PLANTED.items():
            if entry[key]["present"]:
                occurrences[label].append((sid, entry[key]["turn"], entry[key]["prompted"]))
        for label, key in ASKED.items():
            occurrences[label] += [(sid, o["turn"], o["prompted"]) for o in entry["asked_topics"][key]]
    claims, groups, answers = [], [], {}
    for number, (label, rows) in enumerate(occurrences.items()):
        ids = []
        for index, (sid, turn, prompted) in enumerate(rows):
            fact_id = f"t{number}-c{index}"
            claims.append(missed_mod.CitedClaim(fact_id=fact_id, session_id=sid, claim=f"{label} ({index})",
                                                bearings=(), seqs=(turn,)))
            ids.append(fact_id)
            position = next(p for p, t in enumerate(turns[sid]) if turn in t.seqs)
            question, earlier = missed_mod.question_turns(turns[sid], position)
            prompt = pj.item(question.text, (t.text for t in earlier), label)
            assert answers.get(prompt, prompted) == prompted, ("the answer key contradicts itself", sid, turn)
            answers[prompt] = prompted
        groups.append(topics_mod.TopicGroup(label=label, fact_ids=tuple(ids)))
    return SimpleNamespace(truth=truth, survey=survey, turns=turns, claims=claims, groups=groups,
                           answers=answers, occurrences=occurrences)


@pytest.fixture
def demo():
    return _load_demo()


def _kwargs(demo):
    return dict(groups=demo.groups, scripts={sid: demo.survey for sid in demo.turns},
                vocabulary=missed_mod.project_vocabulary(demo.turns))


def _find(demo, judge):
    return missed_mod.find(demo.claims, demo.turns, judge=judge, **_kwargs(demo))


def _labels(topics):
    return {topic.label[0]: topic for topic in topics}


def _answer_key(demo):
    asked = []

    def judge(prompt):
        asked.append(prompt)
        return demo.answers.get(prompt)

    return judge, asked


# --- the real mock interviews, judged as the answer key says --------------------------


def test_every_item_comes_from_the_interviewers_turns_only(demo):
    items = missed_mod.prompt_items(demo.claims, demo.turns, **_kwargs(demo))
    # Control B comes up in two interviews: below the floor, never a topic,
    # so nothing about it is sent.
    assert set(items) == {p for p in demo.answers if p.topic != HOTKEY}
    said = {t.text for turns in demo.turns.values() for t in turns if t.speaker == wp.INTERVIEWER}
    interviewee = {t.text for turns in demo.turns.values() for t in turns if t.speaker == wp.INTERVIEWEE}
    for prompt in items:
        assert {prompt.question, *prompt.earlier} <= said
        assert not {prompt.question, *prompt.earlier} & interviewee


def test_judged_by_the_answer_key_the_headline_is_the_dead_time_and_control_a(demo):
    judge, asked = _answer_key(demo)
    report = _find(demo, judge)
    headlined, recurring = _labels(report.topics), _labels(report.asked_topics)
    assert set(headlined) == {DEAD, HUD}
    dead = headlined[DEAD].tally
    # 8 of 12 unprompted, as the answer key says. The follow-up judge (word
    # based, unchanged) counts ONE follow-up the answer key does not: in 05
    # the pitch two turns later, "talk to Claude in the middle of a match?",
    # shares "match" with the topic's terms. Reported, not papered over;
    # the critic's pitch flag removes it (next test).
    assert (dead.raised_interviews, dead.followed_interviews) == (8, 1)
    assert [o.session_id for o in headlined[DEAD].occurrences if o.followed] == ["05"]
    hud = headlined[HUD].tally
    assert (hud.raised_interviews, hud.followed_interviews) == (5, 5)
    assert HOTKEY not in headlined and HOTKEY not in recurring, "below the floor: two interviews"
    for label in (VOICE, PRICE):
        assert recurring[label].tally.raised_interviews == 0, label
    # The answer key's two volunteered theme mentions (09 turn 46, 10 turn 36).
    assert recurring[THEMES].tally.raised_interviews == 2
    assert all(demo.answers.get(p) is not None for p in asked), "every item was answered"


def test_with_the_critics_pitch_flag_the_dead_time_is_followed_up_in_none(demo):
    judge, _ = _answer_key(demo)
    report = missed_mod.find(demo.claims, demo.turns, judge=judge, flagged={"05": frozenset({19})},
                             **_kwargs(demo))
    dead = _labels(report.topics)[DEAD].tally
    assert (dead.raised_interviews, dead.followed_interviews) == (8, 0)


def test_a_judge_that_says_yes_to_everything_empties_the_headline(demo):
    report = _find(demo, lambda prompt: True)
    assert report.topics == ()
    assert report.state == missed_mod.STATE_ONLY_ASKED


def test_a_judge_that_says_no_to_everything_headlines_what_was_asked(demo):
    """The failure the judge exists to fix: every topic raised 'without being asked'."""
    headlined = _labels(_find(demo, lambda prompt: False).topics)
    assert {DEAD, HUD, VOICE, THEMES, PRICE} <= set(headlined)
    assert headlined[VOICE].tally.raised_interviews == 12


def test_no_answer_counts_as_unprompted_and_says_so(demo):
    report = _find(demo, lambda prompt: None)
    voice = _labels(report.topics)[VOICE]
    assert voice.tally.raised_interviews == 12
    assert all(o.unanswered and not o.prompted for o in voice.occurrences)


def test_without_a_judge_the_word_rule_still_decides(demo):
    """Unchanged lexical behaviour: the Hebrew guide shares no word with the
    English topics, so voice and price headline as raised without being asked."""
    report = missed_mod.find(demo.claims, demo.turns, **_kwargs(demo))
    assert {DEAD, VOICE, PRICE} <= set(_labels(report.topics))
    assert not any(o.unanswered for t in report.topics for o in t.occurrences)


# --- the command ---------------------------------------------------------------------

ROWS = [(f"d{n}", f"S{n}", text) for n, text in enumerate(
    ["She talks to it in the matchmaking queue.", "He asks it things on the loading screen.",
     "Spectating after dying is when she checks her build."], start=1)]
SURVEY = [{"id": "s1", "order": 0, "text": "Which features would you like us to add next?"},
          {"id": "s2", "order": 1, "text": "Would you pay for this product monthly?"}]
INTERVIEWEE_SAID = "Honestly I use it while the match is loading."
TURNS = [("interviewer", "Thanks for joining today, this will be short."),
         ("interviewee", "Sure, happy to help."),
         ("interviewer", "What do you usually do with it when you open it?"),
         ("interviewee", INTERVIEWEE_SAID),
         ("interviewer", "How many friends join your squad on weekends?")]


def _rows(request):
    return [json.loads(line) for line in request["messages"][0]["content"].splitlines() if line.startswith("{")]


class _RoutingClient:
    """One client for both calls, answering by the tool each request forces."""

    def __init__(self, asked=False):
        self.asked, self.requests = asked, []

    def with_options(self, *, timeout):
        return self

    @property
    def messages(self):
        return self

    def create(self, **request):
        self.requests.append(request)
        tool = request["tool_choice"]["name"]
        rows = _rows(request)
        payload = ({"topics": [{"label": DEAD, "claim_ids": [row["id"] for row in rows]}]}
                   if tool == topics_mod.TOOL_NAME else
                   {"items": [{"id": row["id"], "asked": self.asked} for row in rows]})
        response = tool_use_response(tool, payload)
        return ToolUseResponse(content=response.content, stop_reason="tool_use")


@pytest.fixture
def node(tmp_path, monkeypatch):
    sessions, context = tmp_path / "sessions", tmp_path / "context"
    context.mkdir()
    (context / "hypotheses.json").write_text(json.dumps([{"id": "h1", "statement": "x", "falsifier": "y"}]),
                                             encoding="utf-8")
    (context / "facts.json").write_text(json.dumps([
        {"id": f, "session_id": s, "seqs": [3], "claim": c, "provenance": "evidence", "quoted_text": "q",
         "bearings": []} for f, s, c in ROWS]), encoding="utf-8")
    (context / "survey.json").write_text(json.dumps(SURVEY), encoding="utf-8")
    for _, sid, _ in ROWS:
        directory = sessions / sid
        directory.mkdir(parents=True)
        (directory / "session.json").write_text(json.dumps({"started_at": "2026-09-01T10:00:00"}), encoding="utf-8")
        (directory / "transcript.jsonl").write_text("".join(
            json.dumps({"kind": "segment", "seq": i, "speaker": s, "text": t, "audio_end_s": float(i)}) + "\n"
            for i, (s, t) in enumerate(TURNS)), encoding="utf-8")
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(sessions))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(context))
    monkeypatch.setenv("EXTRACT_MODEL", MODEL)
    client = _RoutingClient()
    monkeypatch.setattr(main_mod.reasoning_client, "build_client", lambda: client)
    return SimpleNamespace(context=context, client=client)


def _cache_grouping(node):
    grouping = topics_mod.validate([(DEAD, ["c1", "c2", "c3"])], topics_mod.claim_lines(
        [SimpleNamespace(fact_id=f, session_id=s, claim=c) for f, s, c in ROWS]), model=MODEL)
    topics_store.write(node.context, grouping)


def test_without_yes_the_command_previews_the_judgment_and_calls_nothing(node, capsys):
    _cache_grouping(node)
    assert main_mod.main(["missed", "--group", "model"]) == 0
    out = capsys.readouterr().out
    assert ("One call to test-model-1 to judge whether you had already asked about each topic: 1 "
            "question-topic pairs, made of 2 of your own interview turns") in out
    assert "Never anything the interviewee said" in out
    assert f"  topic: {DEAD}" in out
    assert "    your question: What do you usually do with it when you open it?" in out
    assert "    before it: Thanks for joining today, this will be short." in out
    assert "Nothing called. Re-run with --yes to have the model judge them." in out
    assert "Prompted: by word match between your question and the topic -- the model was not asked" in out
    assert INTERVIEWEE_SAID not in out
    for _, _, claim in ROWS:
        assert claim not in out
    assert not node.client.requests
    assert not (node.context / store.CACHE_FILENAME).exists()


def test_with_yes_both_calls_run_once_and_the_judgment_never_carries_the_interviewee(node, capsys):
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    out = capsys.readouterr().out
    assert [r["tool_choice"]["name"] for r in node.client.requests] == [topics_mod.TOOL_NAME, pj.TOOL_NAME]
    sent = json.dumps(node.client.requests[1], ensure_ascii=False)
    assert INTERVIEWEE_SAID not in sent
    for _, _, claim in ROWS:
        assert claim not in sent
    assert ("Prompted: by the model's reading of your own questions (test-model-1, just made, saved to "
            "context/prompted.json: 0 of 1 question-topic pairs asked about the topic).") in out
    assert "In 3 of 3 interviews, interviewees raised" in out
    assert (node.context / store.CACHE_FILENAME).is_file()

    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    again = capsys.readouterr().out
    assert len(node.client.requests) == 2, "both caches are fresh: no further call"
    assert "cached in context/prompted.json" in again


def test_a_yes_from_the_model_moves_the_topic_out_of_the_headline(node, capsys):
    node.client.asked = True
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "No topic comes up unprompted" in out
    assert "1 of 1 question-topic pairs asked about the topic" in out


def test_other_groupings_never_call_the_judge(node, capsys):
    _cache_grouping(node)
    assert main_mod.main(["missed"]) == 0  # --group auto: the cached model grouping, lexical prompted
    out = capsys.readouterr().out
    assert "Prompted: by word match between your question and the topic." in out
    assert not node.client.requests


# --- prep and the mirror read the same caches, and never call -----------------------------


def test_prep_and_the_mirror_show_the_judged_topics_from_the_cache_alone(node, capsys):
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    capsys.readouterr()
    calls = len(node.client.requests)
    assert main_mod.main(["prep"]) == 0
    prep_out = capsys.readouterr().out
    assert main_mod.main(["mirror"]) == 0
    mirror_out = capsys.readouterr().out
    assert len(node.client.requests) == calls, "prep and the mirror read the caches; neither calls"
    for out in (prep_out, mirror_out):
        assert "Prompted: by the model's reading of your own questions (test-model-1, cached in" in out
        assert INTERVIEWEE_SAID not in out
        for _, _, claim in ROWS:
            assert claim not in out
    assert "What they keep raising that you did not ask about:" in prep_out
    assert f"  > {DEAD}" in prep_out
    assert "raised without being asked in 3 of 3 interviews, followed up in 0" in prep_out
    assert "Add a question in `python -m app author`" in prep_out
    assert "In 3 of 3 interviews, interviewees raised" in mirror_out


def test_a_topic_the_model_judged_asked_is_not_proposed_by_prep(node, capsys):
    node.client.asked = True
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    capsys.readouterr()
    assert main_mod.main(["prep"]) == 0
    out = capsys.readouterr().out
    assert f"  > {DEAD}" not in out
    assert "Nothing: no topic came up unprompted" in out


def test_without_a_fresh_judgment_prep_says_the_word_match_decided(node, capsys):
    _cache_grouping(node)
    assert main_mod.main(["prep"]) == 0
    out = capsys.readouterr().out
    assert "Prompted: by word match between your question and the topic -- the model was not asked" in out
    assert not node.client.requests
