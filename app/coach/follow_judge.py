"""Whether the interviewer followed up on a topic the interviewee had just
raised, judged by the model in one call.

`missed._judge` decides this by word overlap, and it flatters: on the mock
interviews it counted a pitch two turns after the dead-time aside ("wouldn't
it be crazy to talk to Claude in the middle of a teamfight?") as a follow-up,
because the pitch shares "match" with the topic. That one turn was the whole
gap between the report (followed up in 1) and the answer key (in 0). A word
match also cannot see a follow-up asked in other words or another language.

**What is sent: the interviewer's own words, never the interviewee's.** Each
item is a topic's label (from the model grouping) and the interviewer's next
turns after the interviewee raised it (`missed.follow_turns`: through the
second substantive one), each numbered by its place among the interviewer's
turns after the offer, so a bare "What do you mean?" can be read as pointing
back only when it came first. No interviewee speech, no claim text, no quote:
`FollowItem` has no field for any of it. The same class of data the prompted
judgment (`prompt_judge.py`) already sends.

**Every judged occurrence is sent, prompted or not.** An occurrence right
after the interviewer asked about its topic is not counted in the headline,
so its answer goes unused; it is sent anyway so that this cache depends only
on the grouping and the transcripts, never on the prompted judgment's
answers (a re-judged `prompted.json` must not make `followed.json` stale).

**No answer changes nothing.** An item the model left out keeps the word
detector's outcome, and the report says so: a dropped answer can neither
invent a follow-up nor a miss.

Validation is `prompt_judge`'s: a wrong SHAPE is untrusted whole
(`JudgeFailure`); an unknown, repeated or missing id is dropped and named.

Pure apart from the one injected client call: no file I/O (the cache is
`follow_judge_store.py`).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from app.coach import prompt_judge
from app.coach import reasoning_client
from app.coach.prompt_judge import Dropped, JudgeFailure  # noqa: F401 -- re-exported

logger = logging.getLogger(__name__)

TOOL_NAME = "judge_follow_ups_on_topics"
WHAT = "follow-up judgment"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT_S = 120.0


def _clean(text: Any) -> str:
    return " ".join(text.split()) if isinstance(text, str) else ""


@dataclass(frozen=True)
class FollowItem:
    """One question asked of the model. A topic label and interviewer words
    only; built with `item`, which normalises whitespace."""

    topic: str
    turns: "tuple[tuple[int, str], ...]"
    """(n, text): n is the turn's place among the interviewer's turns after
    the offer, 1 being the very next one."""


def item(topic: str, turns: "Iterable[tuple[int, str]]") -> FollowItem:
    cleaned = ((n, _clean(text)) for n, text in turns)
    return FollowItem(topic=_clean(topic), turns=tuple((n, text) for n, text in cleaned if text))


def unique_items(items: Iterable[FollowItem]) -> "tuple[FollowItem, ...]":
    """Normalised, blanks left out, each (topic, turns) once, first seen first."""
    cleaned = (item(i.topic, i.turns) for i in items)
    return tuple(dict.fromkeys(i for i in cleaned if i.topic and i.turns))


@dataclass(frozen=True)
class Judgment:
    model: str
    key: str
    answers: "tuple[tuple[FollowItem, bool], ...]"
    """Only the items the model answered."""
    dropped: Dropped = field(default_factory=Dropped)

    def followed(self, asked: FollowItem) -> Optional[bool]:
        """`None` when the model gave no answer for it (or it was never sent)."""
        return dict(self.answers).get(item(asked.topic, asked.turns))


def judgment_key(items: "Sequence[FollowItem]", model: str) -> str:
    """Every item sent (order-free), the model, the instructions and the tool
    schema: a changed turn, topic, model or prompt each make the cache stale."""
    rows = sorted([i.topic, [list(turn) for turn in i.turns]] for i in unique_items(items))
    blob = json.dumps({"model": model, "items": rows, "system": _SYSTEM, "tool": _tool_schema()},
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _aliases(items: "Sequence[FollowItem]") -> "dict[str, FollowItem]":
    return {f"f{number}": entry for number, entry in enumerate(items, start=1)}


_SYSTEM = """You read what an interviewer said right after an interviewee brought up a topic in a customer-discovery interview, and say whether the interviewer followed up on it.

Each item is one JSON line with an id, a "topic" (a short label for what the interviewee had just talked about) and "turns": the interviewer's next turns, in order, each with "n" (1 is the interviewer's very next turn after the interviewee raised the topic) and "text". You do not see what the interviewee said. The interviewer may speak any language; the topic may be in another. Judge by meaning, not by shared words.

Answer followed=true when at least one of the turns engages the topic: it asks the interviewee to say more about it, to explain it, to give an example of it, or asks a new question about it.

Rules:
- A bare request to go on or explain ("What do you mean?", "Why?", "Tell me more", "When was that?") counts only at n=1, where it points at what was just said. At a later n it points at something else.
- A pitch or a leading question is not a follow-up, even when it names the topic: "Wouldn't it be amazing to talk to it in the middle of a match?" offers the interviewer's own idea instead of asking about the interviewee's.
- A turn that shares a word with the topic but asks about something else is not a follow-up. For the topic "dead time between matches", "How many matches do you play a week?" is not one.
- An acknowledgement ("Okay", "Interesting", "Got it"), thanks, or a move to another subject is not a follow-up.
- Answer every id, using only ids from the list."""


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Report, for every item, whether the interviewer followed up on its topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "An item id from the list."},
                            "followed": {"type": "boolean",
                                         "description": "True when a turn followed up on the topic."},
                        },
                        "required": ["id", "followed"],
                    },
                },
            },
            "required": ["items"],
        },
    }


def assemble_request(items: "Sequence[FollowItem]", *, model: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> dict:
    """The exact kwargs for `client.messages.create`. Pure."""
    items = unique_items(items)
    lines = "\n".join(json.dumps({"id": alias, "topic": entry.topic,
                                  "turns": [{"n": n, "text": text} for n, text in entry.turns]},
                                 ensure_ascii=False)
                      for alias, entry in _aliases(items).items())
    content = f"{len(items)} items:\n{lines}\n\nCall {TOOL_NAME}."
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": content}],
        "tools": [_tool_schema()],
        "tool_choice": reasoning_client.tool_choice(model, TOOL_NAME),
    }


def estimate_input_tokens(request: dict) -> int:
    return prompt_judge.estimate_input_tokens(request)


def validate(raw: "Sequence[tuple[str, bool]]", items: "Sequence[FollowItem]", *, model: str) -> Judgment:
    items = unique_items(items)
    aliases = _aliases(items)
    answered, dropped = prompt_judge.match_ids(raw, tuple(aliases))
    answers = tuple((aliases[alias], followed) for alias, followed in answered.items())
    return Judgment(model=model, key=judgment_key(items, model), answers=answers, dropped=dropped)


def judge(client: Any, items: "Sequence[FollowItem]", *, model: str, max_tokens: int = DEFAULT_MAX_TOKENS,
          timeout_s: float = DEFAULT_TIMEOUT_S) -> Judgment:
    """ONE call through the shared seam. Raises `JudgeFailure` for anything
    that makes the whole answer untrusted."""
    request = assemble_request(items, model=model, max_tokens=max_tokens)
    bound = reasoning_client.with_timeout(client, timeout_s)
    try:
        response = bound.messages.create(**request)
    except Exception as exc:  # noqa: BLE001 -- a timeout, a connection error, anything
        raise JudgeFailure(reason="exception", what=WHAT) from exc
    raw = prompt_judge.raw_answers(response, tool_name=TOOL_NAME, field="followed", what=WHAT)
    judgment = validate(raw, items, model=model)
    usage = getattr(response, "usage", None)
    logger.info("follow-up judgment complete items=%d followed=%d unknown=%d repeated=%d unanswered=%d "
                "usage_input_tokens=%s usage_output_tokens=%s",
                len(unique_items(items)), sum(1 for _, followed in judgment.answers if followed),
                len(judgment.dropped.unknown_ids), len(judgment.dropped.repeated_ids),
                len(judgment.dropped.unanswered_ids),
                getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))
    return judgment
