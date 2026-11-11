"""The model-backed topic grouping (app/coach/topics.py, app/coach/topics_store.py,
app/grouping_cli.py) and its two users, `missed` and `themes`.

Lexical clustering joins claims that share two words; the planted "dead time
between matches" claims share none ("waiting in the queue", "the loading
screen", "spectating after dying"). Every test here runs offline: a fake
client answers from the request it was sent, so the alias mapping is tested
through the real request rather than restated.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import main as main_mod
from app.coach import missed as missed_mod
from app.coach import missed_load
from app.coach import themes as themes_mod
from app.coach import prompt_judge
from app.coach import topics as topics_mod
from app.coach import topics_store
from app.coach import walked_past as wp
from app.coach.stub import StubAnthropicClient, ToolUseResponse, tool_use_response

MODEL = "test-model-1"
QUOTE_SENTINEL = "verbatimsentinelqq"

# Worded so no two share two distinctive words: lexical clustering cannot join them.
IDLE = [
    ("i1", "S1", "She talks to the assistant while sitting in the matchmaking queue."),
    ("i2", "S2", "He uses the loading screen to ask for a quick fix."),
    ("i3", "S3", "Spectating after dying is when she checks her build."),
    ("i4", "S4", "The warmup before kickoff is his moment to send a prompt."),
]
HUD = [
    ("h1", "S1", "The overlay window hid the minimap once."),
    ("h2", "S2", "The kill feed was covered by the panel."),
    ("h3", "S3", "Part of the HUD disappeared behind the window."),
]
PAIR = [  # two interviews: below missed's floor of three
    ("k1", "S1", "The default shortcut clashes with push-to-talk."),
    ("k2", "S2", "Its hotkey collides with quick-save."),
]
NOISE = [("n1", "S3", "Her cat sleeps on the router.")]
ALL_ROWS = IDLE + HUD + PAIR + NOISE


def _ref(fact_id, session_id, claim, bearings=()):
    return SimpleNamespace(fact_id=fact_id, session_id=session_id, claim=claim, bearings=tuple(bearings))


def _refs(rows=ALL_ROWS):
    return [_ref(*row) for row in rows]


def _aliases(request):
    """alias -> claim text, read back from the request the code really built."""
    content = request["messages"][0]["content"]
    rows = [json.loads(line) for line in content.splitlines() if line.startswith("{")]
    return {row["id"]: row["claim"] for row in rows}


def _ids_for(request, texts):
    by_text = {claim: alias for alias, claim in _aliases(request).items()}
    return [by_text[text] for text in texts]


def _semantic_answer(request):
    texts = lambda rows: [row[2] for row in rows]  # noqa: E731
    return {"topics": [
        {"label": "dead time between matches", "claim_ids": _ids_for(request, texts(IDLE))},
        {"label": "the overlay covers the HUD", "claim_ids": _ids_for(request, texts(HUD))},
        {"label": "hotkey collides with another binding", "claim_ids": _ids_for(request, texts(PAIR))},
    ]}


class _FakeClient:
    """Answers from the request it is sent. Records every request."""

    def __init__(self, answer=_semantic_answer, stop_reason="tool_use"):
        self.answer, self.stop_reason, self.requests = answer, stop_reason, []

    def with_options(self, *, timeout):
        self.timeout = timeout
        return self

    @property
    def messages(self):
        return self

    def create(self, **request):
        if request["tool_choice"]["name"] == prompt_judge.TOOL_NAME:
            # `missed --group model --yes` then asks the prompted judgment
            # (test_missed_prompted.py); here it answers "not asked" to all.
            self.judge_requests = getattr(self, "judge_requests", []) + [request]
            rows = [json.loads(line) for line in request["messages"][0]["content"].splitlines()
                    if line.startswith("{")]
            response = tool_use_response(prompt_judge.TOOL_NAME,
                                         {"items": [{"id": row["id"], "asked": False} for row in rows]})
            return ToolUseResponse(content=response.content, stop_reason="tool_use")
        self.requests.append(request)
        payload = self.answer(request)
        response = tool_use_response(topics_mod.TOOL_NAME, payload)
        return ToolUseResponse(content=response.content, stop_reason=self.stop_reason)


def _group(refs=None, answer=_semantic_answer, **kwargs):
    client = _FakeClient(answer, **kwargs)
    grouping = topics_mod.group_claims(client, refs if refs is not None else _refs(), model=MODEL)
    return grouping, client


# --- the request ----------------------------------------------------------------------


def test_the_request_forces_the_tool_and_carries_each_claim_once():
    request = topics_mod.assemble_request(topics_mod.claim_lines(_refs()), model=MODEL, max_tokens=999)
    assert request["model"] == MODEL and request["max_tokens"] == 999
    assert request["tool_choice"] == {"type": "tool", "name": topics_mod.TOOL_NAME}
    assert sorted(_aliases(request).values()) == sorted(row[2] for row in ALL_ROWS)
    # Short aliases, not the corpus's uuids: each id is written back once per topic.
    assert all(len(alias) <= 5 for alias in _aliases(request))


def test_the_request_never_carries_a_quote(tmp_path):
    context = tmp_path / "context"
    _write_facts(context, ALL_ROWS)
    claims = missed_load.read_claims(context)
    request = topics_mod.assemble_request(topics_mod.claim_lines(claims), model=MODEL, max_tokens=10)
    assert QUOTE_SENTINEL not in json.dumps(request, ensure_ascii=False)
    assert "matchmaking queue" in json.dumps(request, ensure_ascii=False)


# --- validation -----------------------------------------------------------------------


def test_a_clean_answer_maps_aliases_back_to_fact_ids():
    grouping, client = _group()
    assert [(t.label, t.fact_ids) for t in grouping.topics] == [
        ("dead time between matches", ("i1", "i2", "i3", "i4")),
        ("the overlay covers the HUD", ("h1", "h2", "h3")),
        ("hotkey collides with another binding", ("k1", "k2")),
    ]
    assert grouping.dropped == topics_mod.Dropped()
    assert grouping.model == MODEL
    assert client.timeout == topics_mod.DEFAULT_TIMEOUT_S


def test_unknown_ids_are_dropped_and_reported():
    def answer(request):
        good = _semantic_answer(request)
        good["topics"][0]["claim_ids"] += ["c999", "f-made-up"]
        return good

    grouping, _ = _group(answer=answer)
    assert grouping.topics[0].fact_ids == ("i1", "i2", "i3", "i4")
    assert grouping.dropped.unknown_ids == ("c999", "f-made-up")


def test_a_claim_in_two_topics_stays_in_the_first():
    def answer(request):
        good = _semantic_answer(request)
        good["topics"][1]["claim_ids"] += _ids_for(request, [IDLE[0][2]])
        return good

    grouping, _ = _group(answer=answer)
    assert grouping.topics[0].fact_ids[0] == "i1"
    assert "i1" not in grouping.topics[1].fact_ids
    assert grouping.dropped.repeated_ids == ("i1",)


def test_empty_and_unlabelled_topics_are_dropped_and_reported():
    def answer(request):
        good = _semantic_answer(request)
        good["topics"] += [{"label": "only made-up ids", "claim_ids": ["c999"]},
                           {"label": "nothing", "claim_ids": []},
                           {"label": "   ", "claim_ids": _ids_for(request, [NOISE[0][2]])}]
        return good

    grouping, _ = _group(answer=answer)
    assert len(grouping.topics) == 3
    assert grouping.dropped.empty_topics == ("only made-up ids", "nothing", "(no label)")


def test_a_repeat_inside_one_topic_is_one_member():
    def answer(request):
        good = _semantic_answer(request)
        good["topics"][0]["claim_ids"] *= 2
        return good

    grouping, _ = _group(answer=answer)
    assert grouping.topics[0].fact_ids == ("i1", "i2", "i3", "i4")
    assert grouping.dropped == topics_mod.Dropped()


@pytest.mark.parametrize("payload", [
    {"topics": "not a list"},
    {"topics": [["not", "an", "object"]]},
    {"topics": [{"label": 3, "claim_ids": []}]},
    {"topics": [{"label": "x", "claim_ids": "c1"}]},
    {"topics": [{"label": "x", "claim_ids": [1, 2]}]},
    {"topics": [{"label": "x"}]},
    {},
])
def test_a_malformed_answer_fails_whole(payload):
    with pytest.raises(topics_mod.GroupingFailure) as caught:
        _group(answer=lambda request: payload)
    assert caught.value.reason == "parse-error"


def test_a_truncated_answer_is_not_trusted():
    with pytest.raises(topics_mod.GroupingFailure) as caught:
        _group(stop_reason="max_tokens")
    assert caught.value.reason == "untrusted-stop-reason"


def test_an_answer_without_the_tool_fails():
    client = StubAnthropicClient(responses=[ToolUseResponse(content=())])
    with pytest.raises(topics_mod.GroupingFailure) as caught:
        topics_mod.group_claims(client, _refs(), model=MODEL)
    assert caught.value.reason == "no-tool-use-block"


def test_a_vendor_error_is_a_grouping_failure():
    client = StubAnthropicClient(raises=TimeoutError("slow"))
    with pytest.raises(topics_mod.GroupingFailure) as caught:
        topics_mod.group_claims(client, _refs(), model=MODEL)
    assert caught.value.reason == "exception"


# --- the cache key ----------------------------------------------------------------------


def test_the_key_follows_ids_text_and_model_and_not_order():
    lines = topics_mod.claim_lines(_refs())
    key = topics_mod.claims_key(lines, MODEL)
    assert key == topics_mod.claims_key(topics_mod.claim_lines(list(reversed(_refs()))), MODEL)
    assert key != topics_mod.claims_key(lines, "other-model")
    edited = _refs()
    edited[0] = _ref("i1", "S1", "She talks to the assistant in the queue.")
    assert key != topics_mod.claims_key(topics_mod.claim_lines(edited), MODEL)
    assert key != topics_mod.claims_key(topics_mod.claim_lines(_refs() + [_ref("x1", "S9", "new")]), MODEL)


def test_a_changed_prompt_changes_the_key(monkeypatch):
    # Otherwise a better prompt would never be tried: the old cache stays "fresh".
    lines = topics_mod.claim_lines(_refs())
    key = topics_mod.claims_key(lines, MODEL)
    monkeypatch.setattr(topics_mod, "_SYSTEM", topics_mod._SYSTEM + " Be brief.")
    assert topics_mod.claims_key(lines, MODEL) != key


# --- the cache file ---------------------------------------------------------------------


def test_a_written_cache_reads_back_fresh(tmp_path):
    grouping, _ = _group()
    path = topics_store.write(tmp_path, grouping)
    assert path == tmp_path / topics_store.CACHE_FILENAME
    assert not list(tmp_path.glob("*.tmp"))
    state = topics_store.load(tmp_path, topics_mod.claim_lines(_refs()), MODEL)
    assert state.status == topics_store.FRESH
    assert state.grouping.topics == grouping.topics


def test_no_cache_is_absent(tmp_path):
    state = topics_store.load(tmp_path, topics_mod.claim_lines(_refs()), MODEL)
    assert (state.status, state.grouping) == (topics_store.ABSENT, None)


def test_a_cache_over_other_claims_is_stale_and_not_used(tmp_path):
    grouping, _ = _group()
    topics_store.write(tmp_path, grouping)
    state = topics_store.load(tmp_path, topics_mod.claim_lines(_refs() + [_ref("x1", "S9", "new")]), MODEL)
    assert (state.status, state.grouping) == (topics_store.STALE, None)
    assert "claims changed" in state.reason


def test_a_cache_from_another_model_is_stale_and_says_which(tmp_path):
    grouping, _ = _group()
    topics_store.write(tmp_path, grouping)
    state = topics_store.load(tmp_path, topics_mod.claim_lines(_refs()), "other-model")
    assert (state.status, state.grouping) == (topics_store.STALE, None)
    assert MODEL in state.reason and "other-model" in state.reason


@pytest.mark.parametrize("text", [
    "{not json",
    "[]",
    json.dumps({"version": 99}),
    None,  # filled below: a fresh key, but a topic naming a claim that is not in the corpus
])
def test_an_unreadable_cache_is_reported_and_not_used(tmp_path, text):
    lines = topics_mod.claim_lines(_refs())
    if text is None:
        text = json.dumps({"version": topics_store.FORMAT_VERSION, "model": MODEL,
                           "claims_key": topics_mod.claims_key(lines, MODEL),
                           "topics": [{"label": "x", "fact_ids": ["i1", "ghost"]}]})
    (tmp_path / topics_store.CACHE_FILENAME).write_text(text, encoding="utf-8")
    state = topics_store.load(tmp_path, lines, MODEL)
    assert (state.status, state.grouping) == (topics_store.UNREADABLE, None)
    assert state.reason


def test_the_writer_refuses_a_grouping_that_breaks_its_own_rules(tmp_path):
    good, _ = _group()
    twice = topics_mod.Grouping(model=MODEL, claims_key=good.claims_key, topics=(
        topics_mod.TopicGroup("a", ("i1", "i2")), topics_mod.TopicGroup("b", ("i2", "i3"))))
    empty = topics_mod.Grouping(model=MODEL, claims_key=good.claims_key, topics=(topics_mod.TopicGroup("a", ()),))
    blank = topics_mod.Grouping(model=MODEL, claims_key=good.claims_key, topics=(topics_mod.TopicGroup(" ", ("i1",)),))
    for bad in (twice, empty, blank):
        with pytest.raises(ValueError):
            topics_store.write(tmp_path, bad)
    assert not (tmp_path / topics_store.CACHE_FILENAME).exists()


# --- themes and missed take the groups --------------------------------------------------


def test_lexical_clustering_cannot_join_the_planted_topic():
    # The reason this module exists, pinned so the fixture stays honest.
    assert not any({"i1", "i2"} <= set(t.fact_ids) for t in themes_mod.clusters(_refs(), min_interviews=3))


def test_groups_become_themes_with_the_models_label_and_the_floor_applied():
    grouping, _ = _group()
    found = themes_mod.from_groups(_refs(), grouping.topics, min_interviews=3)
    assert [(t.label, t.fact_ids, len(t.sessions)) for t in found] == [
        (("dead time between matches",), ("i1", "i2", "i3", "i4"), 4),
        (("the overlay covers the HUD",), ("h1", "h2", "h3"), 3),
    ]


def test_groups_respect_the_include_filter_and_unknown_ids():
    refs = _refs()
    refs[0] = _ref(*IDLE[0], bearings=(("h1", "undermines"),))
    groups = (topics_mod.TopicGroup("idle", ("i1", "i2", "i3", "ghost")),)
    (theme,) = themes_mod.from_groups(refs, groups, include=lambda ref: not ref.bearings, min_interviews=2)
    assert theme.fact_ids == ("i2", "i3")


def test_a_groups_terms_are_what_two_members_share():
    groups = (topics_mod.TopicGroup("hud", ("h1", "h3")),)
    (theme,) = themes_mod.from_groups(_refs(), groups, min_interviews=2)
    assert "window" in theme.terms and "minimap" not in theme.terms


def _turns_where_every_offer_is_walked_past():
    turns = [("interviewer", "Tell me about your evenings."), ("interviewee", "I play ranked most nights."),
             ("interviewer", "Which headset brand do you prefer for evening sessions?"),
             ("interviewee", "A cheap wired one."),
             ("interviewer", "How many friends join your squad on weekends?")]
    records = [{"kind": "segment", "seq": i, "speaker": s, "text": t, "audio_end_s": float(i)}
               for i, (s, t) in enumerate(turns)]
    return wp.turns(records)


def test_missed_judges_a_model_topic_with_the_same_judge():
    claims = [missed_mod.CitedClaim(fact_id=f, session_id=s, claim=c, bearings=(), seqs=(1,)) for f, s, c in ALL_ROWS]
    turns = {sid: _turns_where_every_offer_is_walked_past() for sid in ("S1", "S2", "S3", "S4")}
    grouping, _ = _group()
    report = missed_mod.find(claims, turns, groups=grouping.topics)
    assert [(t.label, t.tally.raised_interviews, t.tally.followed_interviews) for t in report.topics] == [
        (("dead time between matches",), 4, 0), (("the overlay covers the HUD",), 3, 0)]


# --- the commands -----------------------------------------------------------------------


def _write_facts(context, rows, bearings=None):
    context.mkdir(parents=True, exist_ok=True)
    (context / "hypotheses.json").write_text(json.dumps([{"id": "h1", "statement": "x", "falsifier": "y"}]),
                                             encoding="utf-8")
    (context / "facts.json").write_text(json.dumps([
        {"id": f, "session_id": s, "seqs": [1], "claim": c, "provenance": "evidence",
         "quoted_text": QUOTE_SENTINEL, "bearings": (bearings or {}).get(f, [])}
        for f, s, c in rows]), encoding="utf-8")


def _write_session(root, name):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "session.json").write_text(json.dumps({"started_at": "2026-09-01T10:00:00"}), encoding="utf-8")
    turns = [("interviewer", "Tell me about your evenings."), ("interviewee", "I play ranked most nights."),
             ("interviewer", "Which headset brand do you prefer for evening sessions?"),
             ("interviewee", "A cheap wired one."),
             ("interviewer", "How many friends join your squad on weekends?")]
    (directory / "transcript.jsonl").write_text("".join(
        json.dumps({"kind": "segment", "seq": i, "speaker": s, "text": t, "audio_end_s": float(i)}) + "\n"
        for i, (s, t) in enumerate(turns)), encoding="utf-8")


@pytest.fixture
def node(tmp_path, monkeypatch):
    sessions, context = tmp_path / "sessions", tmp_path / "context"
    for sid in ("S1", "S2", "S3", "S4"):
        _write_session(sessions, sid)
    _write_facts(context, ALL_ROWS)
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(sessions))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(context))
    monkeypatch.setenv("EXTRACT_MODEL", MODEL)
    client = _FakeClient()
    built = []

    def _build():
        built.append(client)
        return client

    monkeypatch.setattr(main_mod.reasoning_client, "build_client", _build)
    return SimpleNamespace(sessions=sessions, context=context, client=client, built=built)


def test_missed_without_a_cache_says_it_grouped_by_words(node, capsys):
    assert main_mod.main(["missed"]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("Grouping: by shared words")
    assert not node.built


def test_group_model_without_yes_shows_what_would_be_sent_and_does_nothing(node, capsys):
    assert main_mod.main(["missed", "--group", "model"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("Grouping: by model")
    assert f"{len(ALL_ROWS)} claims" in out and "input tokens" in out and MODEL in out
    assert "Nothing called" in out
    assert not node.built
    assert not (node.context / topics_store.CACHE_FILENAME).exists()
    assert "interviewees raised" not in out


def test_group_model_yes_spends_once_then_the_default_uses_the_cache(node, capsys):
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].startswith("Grouping: by model") and MODEL in lines[0]
    assert "In 4 of 4 interviews, interviewees raised dead time between matches without being asked. You followed up in 0." in out
    assert "hotkey" not in out
    assert QUOTE_SENTINEL not in out
    assert len(node.client.requests) == 1
    assert QUOTE_SENTINEL not in json.dumps(node.client.requests[0], ensure_ascii=False)
    assert (node.context / topics_store.CACHE_FILENAME).is_file()

    assert main_mod.main(["missed"]) == 0
    again = capsys.readouterr().out
    assert again.splitlines()[0].startswith("Grouping: by model") and "topics.json" in again.splitlines()[0]
    assert "dead time between matches" in again
    assert len(node.client.requests) == 1

    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    assert len(node.client.requests) == 1, "a fresh cache is the same answer: no second call"


def test_a_stale_cache_is_reported_and_the_words_are_used(node, capsys):
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    capsys.readouterr()
    _write_facts(node.context, ALL_ROWS + [("x1", "S4", "A brand new claim about ferries.")])
    assert main_mod.main(["missed"]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("Grouping: by shared words") and "stale" in first and "claims changed" in first


def test_group_lexical_ignores_a_fresh_cache(node, capsys):
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    capsys.readouterr()
    assert main_mod.main(["missed", "--group", "lexical"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("Grouping: by shared words")
    assert "dead time between matches" not in out


def test_a_failed_call_writes_nothing_and_exits_nonzero(node, capsys):
    node.client.stop_reason = "max_tokens"
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 1
    assert "ERROR" in capsys.readouterr().err
    assert not (node.context / topics_store.CACHE_FILENAME).exists()


def test_dropped_ids_are_reported_by_the_command(node, capsys):
    def answer(request):
        good = _semantic_answer(request)
        good["topics"][0]["claim_ids"].append("c999")
        return good

    node.client.answer = answer
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("Grouping: by model")
    assert "1 unknown claim id" in out and "c999" in out


def test_without_a_key_the_command_says_so(node, capsys, monkeypatch):
    def _no_key():
        raise main_mod.reasoning_client.CoachConfigError("ANTHROPIC_API_KEY is not set.")

    monkeypatch.setattr(main_mod.reasoning_client, "build_client", _no_key)
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_the_mirror_uses_a_fresh_cache_too(node, capsys):
    assert main_mod.main(["missed", "--group", "model", "--yes"]) == 0
    capsys.readouterr()
    assert main_mod.main(["mirror"]) == 0
    out = capsys.readouterr().out
    assert "dead time between matches" in out and "  Grouping: by model" in out
    assert len(node.client.requests) == 1


def test_themes_group_model_uses_the_same_cache(node, capsys):
    _write_facts(node.context, ALL_ROWS, bearings={"i1": [{"hypothesis_id": "h1", "stance": "undermines"}]})
    assert main_mod.main(["themes", "--group", "model", "--yes"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("Grouping: by model")
    # i1 bears on a hypothesis, so `themes` leaves it to `standing`; the other three remain.
    assert "dead time between matches -- in 3 interviews, 3 claims" in out
    assert "hotkey collides with another binding -- in 2 interviews, 2 claims" in out
    assert QUOTE_SENTINEL not in out
    assert main_mod.main(["missed"]) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("Grouping: by model")
    assert len(node.client.requests) == 1


def test_a_label_loses_its_full_stop_and_extra_space():
    def answer(request):
        good = _semantic_answer(request)
        good["topics"][0]["label"] = "  dead   time between matches. "
        return good

    grouping, _ = _group(answer=answer)
    assert grouping.topics[0].label == "dead time between matches"
