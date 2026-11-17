"""Groups a project's claims into topics by MEANING, in one model call.

`themes.clusters` links two claims when they share two distinctive words, and
that is the measured blind spot: extraction wrote the planted "dead time
between matches" claims eight different ways ("the matchmaking queue", "the
loading screen", "spectating after dying") and no two shared two words, so
`missed` never joined them. This asks the extraction model, once, which claims
describe the same underlying need, behaviour or pain. The follow-up judgment
stays where it was (`missed._judge`, deterministic, over the transcript); only
the grouping changes.

**What is sent.** Each claim's abstracted text, its interview id, and a short
alias (`c17`) standing in for its fact id -- the claim text already goes to
the same vendor during `extract`. Never `quoted_text`: the inputs are
projections that have no field for it (`missed.CitedClaim`,
`interview_summary.FactRef`), and gate 20 pins the modules that may read it.
Aliases rather than the corpus's uuids because every id is written back once
per topic: three tokens instead of twenty-five each, and a short id is harder
to mistype into a different real one.

**Validation is strict, and every drop is reported.** A response with the
wrong SHAPE is untrusted whole (`GroupingFailure`), like `extract`'s. Inside a
well-shaped response: an id the request never sent is dropped and named; a
claim in two topics stays in the first; a topic left empty, or with no label,
is dropped and named. Nothing is silently repaired.

Pure apart from the one injected client call: no file I/O (the cache is
`topics_store.py`), no logging of claim text.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.coach import reasoning_client, token_estimate

logger = logging.getLogger(__name__)

TOOL_NAME = "group_claims_into_topics"
# ~400 claims came back as ~25 topics in the measured project; each alias is a
# few tokens. Generous, because a truncated answer is thrown away whole.
DEFAULT_MAX_TOKENS = 8192
DEFAULT_TIMEOUT_S = 180.0
MAX_LABEL_CHARS = 80
NO_LABEL = "(no label)"
# Same set `extract` refuses: an answer cut short may have lost whole topics.
_UNTRUSTED_STOP_REASONS = frozenset({"refusal", "max_tokens", "pause_turn", "model_context_window_exceeded"})


class GroupingFailure(Exception):
    def __init__(self, *, reason: str, stop_reason: "str | None" = None) -> None:
        super().__init__(f"topic grouping failed: {reason}" + (f" (stop_reason={stop_reason})" if stop_reason else ""))
        self.reason = reason
        self.stop_reason = stop_reason


@dataclass(frozen=True)
class ClaimLine:
    """What one claim contributes to the request and to the cache key."""

    fact_id: str
    session_id: str
    claim: str


@dataclass(frozen=True)
class TopicGroup:
    label: str
    fact_ids: "tuple[str, ...]"


@dataclass(frozen=True)
class Dropped:
    unknown_ids: "tuple[str, ...]" = ()
    """Ids the response used that the request never sent, as written."""
    repeated_ids: "tuple[str, ...]" = ()
    """Fact ids also placed in an earlier topic; they stayed there."""
    empty_topics: "tuple[str, ...]" = ()
    """Labels of topics dropped for having no member or no label left."""

    @property
    def any(self) -> bool:
        return bool(self.unknown_ids or self.repeated_ids or self.empty_topics)


@dataclass(frozen=True)
class Grouping:
    model: str
    claims_key: str
    topics: "tuple[TopicGroup, ...]"
    dropped: Dropped = field(default_factory=Dropped)


def claim_lines(claims: Sequence[Any]) -> "tuple[ClaimLine, ...]":
    """Field by field from any projection with `fact_id`/`session_id`/`claim`
    -- never a dump. Blank claims carry nothing to group; a repeated fact id
    keeps its first row, so one id can never map to two texts."""
    lines, seen = [], set()
    for claim in claims:
        text, fact_id = getattr(claim, "claim", None), getattr(claim, "fact_id", None)
        if not isinstance(text, str) or not text.strip() or not isinstance(fact_id, str) or fact_id in seen:
            continue
        seen.add(fact_id)
        lines.append(ClaimLine(fact_id=fact_id, session_id=str(claim.session_id), claim=text.strip()))
    return tuple(lines)


def claims_key(lines: "Sequence[ClaimLine]", model: str) -> str:
    """The cache key: every line sent, in a fixed order, the model, and the
    instructions. A changed claim, a new one, another model or a reworded
    prompt each make the cache stale -- a better prompt must get its chance."""
    rows = sorted((line.fact_id, line.session_id, line.claim) for line in lines)
    blob = json.dumps({"model": model, "claims": rows, "system": _SYSTEM, "tool": _tool_schema()},
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _aliases(lines: "Sequence[ClaimLine]") -> "dict[str, ClaimLine]":
    return {f"c{number}": line for number, line in enumerate(lines, start=1)}


_SYSTEM = """You group claims extracted from customer-discovery interviews into topics.

Each claim is one JSON line: an id, the interview it came from, and the claim, already abstracted into a sentence.

Put claims in the same topic when they describe the SAME underlying need, behaviour or pain, even when they are worded differently. For example "re-types the invoice into a spreadsheet" and "copies totals from the PDF by hand" are one topic: entering billing data by hand. Do not group claims just because they share words, such as the product's name.

Keep topics narrow. One topic is one need, behaviour or pain:
- WHEN or WHERE something happens is a different topic from WHAT it is used for, even when one interviewee says both.
- Two different complaints about the same feature are two topics: "the export is slow" and "the export drops a column" do not belong together.

Rules:
- A topic needs claims from at least two different interviews. Leave out claims that fit no recurring topic.
- A claim belongs to at most one topic: the one it most directly describes.
- A claim joins a topic only if it states that need, behaviour or pain itself. Being from the same part of the interview, or about the same product, is not enough: when in doubt, leave the claim out.
- Claims that only answer the interviewer's scripted questions (which features they want, what they would pay, whether they would recommend it) are not a topic, unless they show a recurring need of the interviewee's own.
- Label each topic with a short phrase of two to six words, the way an interviewee would say it, without the product's name and without a full stop: for example "typing invoices in by hand".
- Use only ids from the list."""


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Report the recurring topics and which claims belong to each.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string",
                                      "description": "Short plain English, as the interviewee would put it."},
                            "claim_ids": {"type": "array", "items": {"type": "string"},
                                          "description": "Ids from the list, from at least two interviews."},
                        },
                        "required": ["label", "claim_ids"],
                    },
                },
            },
            "required": ["topics"],
        },
    }


def assemble_request(lines: "Sequence[ClaimLine]", *, model: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> dict:
    """The exact kwargs for `client.messages.create`. Pure."""
    body = "\n".join(
        json.dumps({"id": alias, "interview": line.session_id, "claim": line.claim}, ensure_ascii=False)
        for alias, line in _aliases(lines).items()
    )
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": f"{len(lines)} claims:\n{body}\n\nCall {TOOL_NAME}."}],
        "tools": [_tool_schema()],
        "tool_choice": reasoning_client.tool_choice(model, TOOL_NAME),
    }


def estimate_input_tokens(request: dict) -> int:
    return token_estimate.estimate(request)


def _raw_topics(response: Any) -> "list[tuple[str, list[str]]]":
    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason in _UNTRUSTED_STOP_REASONS:
        raise GroupingFailure(reason="untrusted-stop-reason", stop_reason=stop_reason)
    for block in getattr(response, "content", None) or ():
        if getattr(block, "type", None) != "tool_use" or getattr(block, "name", None) != TOOL_NAME:
            continue
        try:
            raw = block.input["topics"]
            if not isinstance(raw, list):
                raise ValueError("topics must be an array")
            parsed = []
            for entry in raw:
                label, ids = entry["label"], entry["claim_ids"]
                if not isinstance(label, str) or not isinstance(ids, list):
                    raise ValueError("a topic needs a string label and an array of ids")
                if not all(isinstance(item, str) for item in ids):
                    raise ValueError("claim ids must be strings")
                parsed.append((label, ids))
            return parsed
        except (KeyError, TypeError, ValueError) as exc:
            raise GroupingFailure(reason="parse-error", stop_reason=stop_reason) from exc
    raise GroupingFailure(reason="no-tool-use-block", stop_reason=stop_reason)


def validate(raw: "Sequence[tuple[str, Sequence[str]]]", lines: "Sequence[ClaimLine]", *,
             model: str) -> Grouping:
    """Aliases back to fact ids, with every drop recorded (module docstring)."""
    aliases = _aliases(lines)
    unknown: "list[str]" = []
    repeated: "list[str]" = []
    empty: "list[str]" = []
    placed: "set[str]" = set()
    topics: "list[TopicGroup]" = []
    for label, ids in raw:
        # The headline ends the sentence itself: "raised dead time.." otherwise.
        shown = " ".join(label.split())[:MAX_LABEL_CHARS].strip().rstrip(".").strip()
        members: "list[str]" = []
        for alias in dict.fromkeys(ids):  # a repeat inside one topic is one member
            line = aliases.get(alias.strip())
            if line is None:
                unknown.append(alias)
            elif line.fact_id in placed:
                repeated.append(line.fact_id)
            else:
                members.append(line.fact_id)
        if not shown or not members:
            # Members of a dropped topic are NOT marked placed: a later topic may still hold them.
            empty.append(shown or NO_LABEL)
            continue
        placed.update(members)
        topics.append(TopicGroup(label=shown, fact_ids=tuple(members)))
    return Grouping(
        model=model,
        claims_key=claims_key(lines, model),
        topics=tuple(topics),
        dropped=Dropped(unknown_ids=tuple(unknown), repeated_ids=tuple(repeated), empty_topics=tuple(empty)),
    )


def group_claims(client: Any, claims: Sequence[Any], *, model: str, max_tokens: int = DEFAULT_MAX_TOKENS,
                 timeout_s: float = DEFAULT_TIMEOUT_S) -> Grouping:
    """ONE call through the shared seam. `claims`: projections (see
    `claim_lines`). Raises `GroupingFailure` for anything that makes the whole
    answer untrusted."""
    lines = claim_lines(claims)
    request = assemble_request(lines, model=model, max_tokens=max_tokens)
    bound = reasoning_client.with_timeout(client, timeout_s)
    try:
        response = bound.messages.create(**request)
    except Exception as exc:  # noqa: BLE001 -- a timeout, a connection error, anything
        raise GroupingFailure(reason="exception") from exc
    grouping = validate(_raw_topics(response), lines, model=model)
    usage = getattr(response, "usage", None)
    logger.info("topic grouping complete claims=%d topics=%d unknown=%d repeated=%d empty=%d "
                "usage_input_tokens=%s usage_output_tokens=%s",
                len(lines), len(grouping.topics), len(grouping.dropped.unknown_ids),
                len(grouping.dropped.repeated_ids), len(grouping.dropped.empty_topics),
                getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))
    return grouping
