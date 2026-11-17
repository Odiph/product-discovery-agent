"""Which guide questions an interview without a live coverage record really
asked, read by the model from the interviewer's own turns, in one call.

`prep_load.reconstructed_question_ids` matches each interviewer turn to a
guide question by shared words. On the mock interviews that found 52 of the
91 questions really asked (s2, the onboarding question, in 2 of 10): a
question asked in other words, another grammatical gender, or another
language is missed. `python -m app coverage` asks the model instead, once,
and caches the answer; `prep` reads the cache and never calls a model.

**What is sent.** The survey's questions (operator-authored) and, for each
interview with no live record, the interviewer's turns in order -- the
operator's own words. Nothing the interviewee said: the inputs have no field
for it. Interviewer turns already reach the same vendor through coaching,
`extract` and `critique-questions`.

**One-way, until measured otherwise.** A question the model finds counts as
asked; one it does not find stays "check by hand" in `prep`, never "never
asked" (`prep.item_proposals`): its recall on real interviews is not
measured yet.

**Validation is strict, and every drop is reported.** A wrong SHAPE fails
whole (`CoverageFailure`); an unknown turn or question id is dropped and
named; a turn answered twice keeps its first answer.

Pure apart from the one injected client call (the cache is `coverage_store.py`).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.coach import reasoning_client, token_estimate

logger = logging.getLogger(__name__)

TOOL_NAME = "report_guide_questions_asked"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT_S = 180.0
_UNTRUSTED_STOP_REASONS = frozenset({"refusal", "max_tokens", "pause_turn", "model_context_window_exceeded"})


class CoverageFailure(Exception):
    def __init__(self, *, reason: str, stop_reason: "str | None" = None) -> None:
        super().__init__(f"coverage reading failed: {reason}"
                         + (f" (stop_reason={stop_reason})" if stop_reason else ""))
        self.reason = reason
        self.stop_reason = stop_reason


def _clean(text: Any) -> str:
    return " ".join(text.split()) if isinstance(text, str) else ""


def questions(survey: Sequence[Any]) -> "tuple[tuple[str, str], ...]":
    """(id, text) of each survey question, blank and repeated ids left out."""
    seen: "dict[str, str]" = {}
    for entry in survey:
        qid, text = _clean(getattr(entry, "id", "")), _clean(getattr(entry, "text", ""))
        if qid and text and qid not in seen:
            seen[qid] = text
    return tuple(seen.items())


def sessions(turns: "Mapping[str, Sequence[str]]") -> "tuple[tuple[str, tuple[str, ...]], ...]":
    """Each session's interviewer turns, whitespace-normalised, blanks out,
    sessions sorted by id; a session with no turn left is dropped."""
    rows = []
    for sid in sorted(turns):
        kept = tuple(t for t in (_clean(text) for text in turns[sid]) if t)
        if kept:
            rows.append((sid, kept))
    return tuple(rows)


@dataclass(frozen=True)
class Dropped:
    unknown_ids: "tuple[str, ...]" = ()
    repeated_turns: "tuple[str, ...]" = ()

    @property
    def any(self) -> bool:
        return bool(self.unknown_ids or self.repeated_turns)


@dataclass(frozen=True)
class Coverage:
    model: str
    key: str
    asked: "tuple[tuple[str, tuple[str, ...]], ...]"
    """(session id, survey ids it asked, in the order first asked), for every
    session sent -- an empty tuple when the model found none."""
    dropped: Dropped = field(default_factory=Dropped)

    def as_dict(self) -> "dict[str, tuple[str, ...]]":
        return dict(self.asked)


def coverage_key(survey_questions: "Sequence[tuple[str, str]]", session_turns: "Mapping[str, Sequence[str]]",
                 model: str) -> str:
    blob = json.dumps({"model": model, "questions": sorted(list(q) for q in survey_questions),
                       "sessions": [[sid, list(turns)] for sid, turns in sessions(session_turns)],
                       "system": _SYSTEM, "tool": _tool_schema()},
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_SYSTEM = """You read an interview guide and the interviewer's side of several customer-discovery interviews, and say which guide questions the interviewer really asked.

The guide questions are JSON lines with an id. Each interview is a list of the interviewer's turns, in order, each with an id. The interviewer may reword a question, ask it in another language or another grammatical form, or split it over two turns; judge by meaning, not by shared words.

Rules:
- A turn asks a guide question when it asks for what that question asks for. "And what do you do with it?" asks "What do you usually do with it?"; "How was the install?" asks "How was the installation and onboarding?".
- A pitch or a leading question on the same subject ("Wouldn't voice be amazing mid-match?") does not ask the neutral guide question ("What do you think about voice input?").
- A thank-you, an acknowledgement or a statement asks nothing.
- List only the turns that ask a guide question, each with every guide question it asks, using only ids from the lists."""


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Report every interviewer turn that asks a guide question, with the questions it asks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asked": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "turn_id": {"type": "string", "description": "A turn id from the interviews."},
                            "question_ids": {"type": "array", "items": {"type": "string"},
                                             "description": "Guide question ids this turn asks."},
                        },
                        "required": ["turn_id", "question_ids"],
                    },
                },
            },
            "required": ["asked"],
        },
    }


def _aliases(survey_questions, session_turns):
    q_alias = {f"q{n}": qid for n, (qid, _) in enumerate(survey_questions, start=1)}
    turn_alias: "dict[str, str]" = {}
    blocks = []
    for n, (sid, turns) in enumerate(sessions(session_turns), start=1):
        lines = []
        for k, text in enumerate(turns, start=1):
            alias = f"i{n}-t{k}"
            turn_alias[alias] = sid
            lines.append(json.dumps({"id": alias, "turn": text}, ensure_ascii=False))
        blocks.append((f"i{n}", lines))
    return q_alias, turn_alias, blocks


def assemble_request(survey_questions: "Sequence[tuple[str, str]]", session_turns: "Mapping[str, Sequence[str]]",
                     *, model: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> dict:
    """The exact kwargs for `client.messages.create`. Pure."""
    q_alias, _, blocks = _aliases(survey_questions, session_turns)
    question_lines = "\n".join(json.dumps({"id": alias, "question": text}, ensure_ascii=False)
                               for alias, (_, text) in zip(q_alias, survey_questions))
    interviews = "\n\n".join(f"Interview {name}, the interviewer's turns:\n" + "\n".join(lines)
                             for name, lines in blocks)
    content = (f"{len(survey_questions)} guide questions:\n{question_lines}\n\n{interviews}\n\n"
               f"Call {TOOL_NAME}.")
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": content}],
        "tools": [_tool_schema()],
        "tool_choice": reasoning_client.tool_choice(model, TOOL_NAME),
    }


def estimate_input_tokens(request: dict) -> int:
    return token_estimate.estimate(request)


def _raw(response: Any) -> "list[tuple[str, list[str]]]":
    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason in _UNTRUSTED_STOP_REASONS:
        raise CoverageFailure(reason="untrusted-stop-reason", stop_reason=stop_reason)
    for block in getattr(response, "content", None) or ():
        if getattr(block, "type", None) != "tool_use" or getattr(block, "name", None) != TOOL_NAME:
            continue
        try:
            raw = block.input["asked"]
            if not isinstance(raw, list):
                raise ValueError("asked must be an array")
            parsed = []
            for entry in raw:
                turn_id, question_ids = entry["turn_id"], entry["question_ids"]
                if not isinstance(turn_id, str) or not isinstance(question_ids, list) or not all(
                        isinstance(q, str) for q in question_ids):
                    raise ValueError("an answer needs a string turn id and an array of string question ids")
                parsed.append((turn_id, question_ids))
            return parsed
        except (KeyError, TypeError, ValueError) as exc:
            raise CoverageFailure(reason="parse-error", stop_reason=stop_reason) from exc
    raise CoverageFailure(reason="no-tool-use-block", stop_reason=stop_reason)


def validate(raw: "Sequence[tuple[str, Sequence[str]]]", survey_questions: "Sequence[tuple[str, str]]",
             session_turns: "Mapping[str, Sequence[str]]", *, model: str) -> Coverage:
    q_alias, turn_alias, _ = _aliases(survey_questions, session_turns)
    unknown: "list[str]" = []
    repeated: "list[str]" = []
    seen_turns: "set[str]" = set()
    asked: "dict[str, list[str]]" = {sid: [] for sid, _ in sessions(session_turns)}
    for turn_id, question_ids in raw:
        alias = turn_id.strip()
        if alias not in turn_alias:
            unknown.append(turn_id)
            continue
        if alias in seen_turns:
            repeated.append(alias)
            continue
        seen_turns.add(alias)
        found = asked[turn_alias[alias]]
        for question_id in dict.fromkeys(q.strip() for q in question_ids):
            qid = q_alias.get(question_id)
            if qid is None:
                unknown.append(question_id)
            elif qid not in found:
                found.append(qid)
    # Turn ids sort as written, so "first asked" follows the turn order.
    return Coverage(model=model, key=coverage_key(survey_questions, session_turns, model),
                    asked=tuple((sid, tuple(ids)) for sid, ids in asked.items()),
                    dropped=Dropped(unknown_ids=tuple(unknown), repeated_turns=tuple(repeated)))


def read(client: Any, survey_questions: "Sequence[tuple[str, str]]", session_turns: "Mapping[str, Sequence[str]]",
         *, model: str, max_tokens: int = DEFAULT_MAX_TOKENS, timeout_s: float = DEFAULT_TIMEOUT_S) -> Coverage:
    """ONE call through the shared seam."""
    request = assemble_request(survey_questions, session_turns, model=model, max_tokens=max_tokens)
    bound = reasoning_client.with_timeout(client, timeout_s)
    try:
        response = bound.messages.create(**request)
    except Exception as exc:  # noqa: BLE001 -- a timeout, a connection error, anything
        raise CoverageFailure(reason="exception") from exc
    coverage = validate(_raw(response), survey_questions, session_turns, model=model)
    usage = getattr(response, "usage", None)
    logger.info("coverage reading complete sessions=%d asked=%d unknown=%d repeated=%d "
                "usage_input_tokens=%s usage_output_tokens=%s",
                len(coverage.asked), sum(len(ids) for _, ids in coverage.asked), len(coverage.dropped.unknown_ids),
                len(coverage.dropped.repeated_turns),
                getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))
    return coverage
