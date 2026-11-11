"""Whether the interviewer had already asked about a topic when the
interviewee raised it, judged by the model in one call.

`missed._prompted` decided this by word overlap, and on the mock interviews
(Hebrew guide, English claims) that was measured to fail: guide questions
were recognised in 52 of 91 cases, a pitch ("wouldn't voice be amazing
mid-fight?") was never caught, and an off-script "what about themes?" was
read as no question at all. This asks the extraction model, once per run,
for each (question, topic) pair: did this question ask about this topic?

**What is sent: the interviewer's own words, never the interviewee's.** Each
item is the interviewer's last turn before the offer (whatever its length:
"Anything else?" is the question that was really answered), up to
`EARLIER_TURNS` of the interviewer's substantive turns before it as context
(so a bare "Anything else?" can be read as continuing "What features would
you like?"), and the topic's label from the model grouping. No interviewee
speech, no claim text, no quote: `PromptItem` has no field for any of it.
Interviewer turns already reach the same vendor through coaching, `extract`
and `critique-questions`, so no new class of data leaves the machine.

**One-way.** The answer only ever marks an occurrence prompted; an item the
model left out counts as NOT asked, so a dropped answer can never hide an
aside.

**Validation is strict, and every drop is reported.** A response with the
wrong SHAPE is untrusted whole (`JudgeFailure`). Inside a well-shaped one: an
id the request never sent is dropped and named; an id answered twice keeps
its first answer and is named; an id left out is named and counts as not
asked.

Pure apart from the one injected client call: no file I/O (the cache is
`prompt_judge_store.py`).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from app.coach import reasoning_client

logger = logging.getLogger(__name__)

TOOL_NAME = "judge_questions_against_topics"
# A dozen interviews with ~25 recurring topics come back as a few hundred ids.
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT_S = 120.0
CHARS_PER_TOKEN = 4.0
EARLIER_TURNS = 2
_UNTRUSTED_STOP_REASONS = frozenset({"refusal", "max_tokens", "pause_turn", "model_context_window_exceeded"})


class JudgeFailure(Exception):
    def __init__(self, *, reason: str, stop_reason: "str | None" = None) -> None:
        super().__init__(f"prompted judgment failed: {reason}"
                         + (f" (stop_reason={stop_reason})" if stop_reason else ""))
        self.reason = reason
        self.stop_reason = stop_reason


def _clean(text: Any) -> str:
    return " ".join(text.split()) if isinstance(text, str) else ""


@dataclass(frozen=True)
class PromptItem:
    """One question asked of the model. Interviewer words and a topic label
    only; built with `item`, which normalises whitespace."""

    question: str
    earlier: "tuple[str, ...]"
    topic: str


def item(question: str, earlier: Iterable[str], topic: str) -> PromptItem:
    return PromptItem(question=_clean(question), earlier=tuple(t for t in (_clean(e) for e in earlier) if t),
                      topic=_clean(topic))


def unique_items(items: Iterable[PromptItem]) -> "tuple[PromptItem, ...]":
    """Normalised, blanks left out, each (question, context, topic) once, in
    first-seen order: the same scripted turn asked about the same topic in
    two interviews with the same lead-in is one item."""
    cleaned = (item(i.question, i.earlier, i.topic) for i in items)
    return tuple(dict.fromkeys(i for i in cleaned if i.question and i.topic))


@dataclass(frozen=True)
class Dropped:
    unknown_ids: "tuple[str, ...]" = ()
    repeated_ids: "tuple[str, ...]" = ()
    unanswered_ids: "tuple[str, ...]" = ()

    @property
    def any(self) -> bool:
        return bool(self.unknown_ids or self.repeated_ids or self.unanswered_ids)


@dataclass(frozen=True)
class Judgment:
    model: str
    key: str
    answers: "tuple[tuple[PromptItem, bool], ...]"
    """Only the items the model answered."""
    dropped: Dropped = field(default_factory=Dropped)

    def asked(self, prompt: PromptItem) -> Optional[bool]:
        """`None` when the model gave no answer for it (or it was never sent)."""
        wanted = item(prompt.question, prompt.earlier, prompt.topic)
        return dict(self.answers).get(wanted)


def judgment_key(items: "Sequence[PromptItem]", model: str) -> str:
    """Every item sent (order-free), the model, the instructions and the tool
    schema: a changed turn, topic, model or prompt each make the cache stale."""
    rows = sorted([i.question, list(i.earlier), i.topic] for i in unique_items(items))
    blob = json.dumps({"model": model, "items": rows, "system": _SYSTEM, "tool": _tool_schema()},
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _aliases(items: "Sequence[PromptItem]") -> "dict[str, PromptItem]":
    return {f"p{number}": entry for number, entry in enumerate(items, start=1)}


_SYSTEM = """You read questions an interviewer asked in customer-discovery interviews, and say, for each one, whether it asked about a given topic.

Each item is one JSON line with an id, the interviewer's "question" (what they said right before the interviewee spoke), up to two of the interviewer's "earlier" questions for context, and a "topic": a short label for something the interviewee then talked about. The interviewer may speak any language; the topic may be in another. Judge by meaning, not by shared words.

Answer asked=true when the question asked about the topic, so that the interviewee talking about it was an answer, not something they brought up themselves.

Rules:
- A pitch or a leading question about the topic counts as asking about it: "Wouldn't voice input be amazing mid-match?" asks about voice input.
- A question asks only for what it names. "What features would you like us to add?" asks about every wished-for feature (a dark mode, an export, voice input), but not about a complaint or a habit. "What do you usually do with it?" asks WHAT they do; it does not ask WHEN, WHERE or WHY, so a topic about the moment, the place or the reason is not asked about by it.
- A question asks about every topic that is an answer to it: "Would you pay for it?" asks about paying, the price and not paying; "How often do you use it?" asks about using it often, rarely, or less than before.
- An open question names nothing: "Anything bothering you?", "What is your favourite part?", "Anything else you want to add?" at the end of an interview do not ask about any particular topic.
- A bare "Anything else?" or "What else?" continues the earlier question: right after "What features would you like?", it asks for more features.
- When in doubt, answer false.
- Answer every id, using only ids from the list."""


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Report, for every item, whether its question asked about its topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "An item id from the list."},
                            "asked": {"type": "boolean", "description": "True when the question asked about the topic."},
                        },
                        "required": ["id", "asked"],
                    },
                },
            },
            "required": ["items"],
        },
    }


def assemble_request(items: "Sequence[PromptItem]", *, model: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> dict:
    """The exact kwargs for `client.messages.create`. Pure."""
    items = unique_items(items)
    lines = "\n".join(json.dumps({"id": alias, "earlier": list(entry.earlier), "question": entry.question,
                                  "topic": entry.topic}, ensure_ascii=False)
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
    """Four characters a token, as `topics` estimates: +/-15%, low for Hebrew."""
    return round(len(json.dumps(request, ensure_ascii=False)) / CHARS_PER_TOKEN)


def _raw_answers(response: Any) -> "list[tuple[str, bool]]":
    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason in _UNTRUSTED_STOP_REASONS:
        raise JudgeFailure(reason="untrusted-stop-reason", stop_reason=stop_reason)
    for block in getattr(response, "content", None) or ():
        if getattr(block, "type", None) != "tool_use" or getattr(block, "name", None) != TOOL_NAME:
            continue
        try:
            raw = block.input["items"]
            if not isinstance(raw, list):
                raise ValueError("items must be an array")
            parsed = []
            for entry in raw:
                alias, asked = entry["id"], entry["asked"]
                if not isinstance(alias, str) or not isinstance(asked, bool):
                    raise ValueError("an answer needs a string id and a boolean")
                parsed.append((alias, asked))
            return parsed
        except (KeyError, TypeError, ValueError) as exc:
            raise JudgeFailure(reason="parse-error", stop_reason=stop_reason) from exc
    raise JudgeFailure(reason="no-tool-use-block", stop_reason=stop_reason)


def validate(raw: "Sequence[tuple[str, bool]]", items: "Sequence[PromptItem]", *, model: str) -> Judgment:
    """Aliases back to items, with every drop recorded (module docstring)."""
    items = unique_items(items)
    aliases = _aliases(items)
    unknown: "list[str]" = []
    repeated: "list[str]" = []
    answered: "dict[str, bool]" = {}
    for alias, asked in raw:
        key = alias.strip()
        if key not in aliases:
            unknown.append(alias)
        elif key in answered:
            repeated.append(key)
        else:
            answered[key] = asked
    unanswered = tuple(alias for alias in aliases if alias not in answered)
    answers = tuple((aliases[alias], asked) for alias, asked in answered.items())
    return Judgment(model=model, key=judgment_key(items, model), answers=answers,
                    dropped=Dropped(unknown_ids=tuple(unknown), repeated_ids=tuple(repeated),
                                    unanswered_ids=unanswered))


def judge(client: Any, items: "Sequence[PromptItem]", *, model: str, max_tokens: int = DEFAULT_MAX_TOKENS,
          timeout_s: float = DEFAULT_TIMEOUT_S) -> Judgment:
    """ONE call through the shared seam. Raises `JudgeFailure` for anything
    that makes the whole answer untrusted."""
    request = assemble_request(items, model=model, max_tokens=max_tokens)
    bound = reasoning_client.with_timeout(client, timeout_s)
    try:
        response = bound.messages.create(**request)
    except Exception as exc:  # noqa: BLE001 -- a timeout, a connection error, anything
        raise JudgeFailure(reason="exception") from exc
    judgment = validate(_raw_answers(response), items, model=model)
    usage = getattr(response, "usage", None)
    logger.info("prompted judgment complete items=%d asked=%d unknown=%d repeated=%d unanswered=%d "
                "usage_input_tokens=%s usage_output_tokens=%s",
                len(unique_items(items)), sum(1 for _, asked in judgment.answers if asked),
                len(judgment.dropped.unknown_ids), len(judgment.dropped.repeated_ids),
                len(judgment.dropped.unanswered_ids),
                getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))
    return judgment
