"""Synthesis across every interview in a project, in one model call:
the answer IS the opportunity solution tree (Teresa Torres's
method): outcome > opportunities (nestable) > solutions > assumptions.

The model proposes the structure; code decides everything else. It drops
what breaks the tree's rules (`synthesis_validate.py`), computes every
status from the cited claims in DISTINCT INTERVIEWS (`synthesis_status.py`)
and flags phrasing and shape smells without dropping (`synthesis_warnings.py`).
Opinions and praise are never nodes: they come back as a footnote list,
heard, not evidence. Operator hypotheses are labels a node may map to, not
the skeleton: the model derives opportunities from the claims first.

**What is sent.** Each claim's abstracted text, its interview id, its
hypothesis bearings and a short alias (`c17`) standing in for its fact id;
each hypothesis's id, statement, kind and parent; the operator's outcome
text, if any; and, when a previous tree exists, its node ids, statements
and structure (model-written labels, no claim text). Never a quote and never
a transcript: the inputs are projections (`ClaimItem`, built field by field
from `interview_summary.FactRef`) that have no field for either.

The previous tree is context for stability, not input: it is NOT part of the
cache key, so the same claims, hypotheses and outcome never call twice.

Pure apart from the one injected client call: no file I/O (the cache is
`synthesis_store.py`), no logging of claim text.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional, Sequence

from app.coach import reasoning_client, token_estimate
from app.coach.synthesis_types import (  # noqa: F401 -- re-exported: callers import the shapes from here
    ALREADY_MET, ASSUMPTION_TYPES, CONTRADICTS, EXPERIENCES, IMPORTANCES, KIND_OPPORTUNITY, NOT_EXPERIENCED, ORIGINS,
    ClaimItem, Drop, HypothesisLine, OutcomeInput, PriorTree, Synthesis, SUPPORTS,
)

logger = logging.getLogger(__name__)

TOOL_NAME = "report_opportunity_solution_tree"
PROMPT_VERSION = 3
"""Raised by hand when the instructions' meaning changes; part of the cache key.
3: the answer became the opportunity solution tree (was: themes and contradictions)."""
# The mock project's ~400 claims: a tree of statements, citations with their
# direction, stories and three assumptions per solution. Its first paid run
# (2026-11-14) stopped at 16,384 output tokens, and a truncated answer is
# thrown away whole, so the cap is twice that.
DEFAULT_MAX_TOKENS = 32768
# Up to 32k output tokens from a slow model: a timeout wastes the paid call.
DEFAULT_TIMEOUT_S = 900.0
MAX_STATEMENT_CHARS = 200
MAX_STORY_CHARS = 240
MAX_ASSUMPTION_CHARS = 200
NO_LABEL = "(no statement)"


class SynthesisFailure(Exception):
    def __init__(self, *, reason: str, stop_reason: "str | None" = None) -> None:
        super().__init__(f"synthesis failed: {reason}" + (f" (stop_reason={stop_reason})" if stop_reason else ""))
        self.reason = reason
        self.stop_reason = stop_reason


def claim_items(refs: Sequence[Any]) -> "tuple[ClaimItem, ...]":
    """Field by field from any projection with `fact_id`/`session_id`/
    `claim`/`bearings`, never a dump. Blank claims are left out; a repeated
    fact id keeps its first row."""
    items, seen = [], set()
    for ref in refs:
        text, fact_id = getattr(ref, "claim", None), getattr(ref, "fact_id", None)
        if not isinstance(text, str) or not text.strip() or not isinstance(fact_id, str) or fact_id in seen:
            continue
        seen.add(fact_id)
        bearings = tuple((str(h), str(s)) for h, s in getattr(ref, "bearings", ()) or ())
        items.append(ClaimItem(fact_id=fact_id, session_id=str(ref.session_id), claim=" ".join(text.split()),
                               bearings=bearings))
    return tuple(items)


def hypothesis_lines(hypotheses: Sequence[Any]) -> "tuple[HypothesisLine, ...]":
    """Id, statement, kind and parent only: never the falsifier or the criterion."""
    lines, seen = [], set()
    for hypothesis in hypotheses:
        hid, statement = getattr(hypothesis, "id", None), getattr(hypothesis, "statement", None)
        if not isinstance(hid, str) or not isinstance(statement, str) or hid in seen:
            continue
        seen.add(hid)
        kind, parent = getattr(hypothesis, "kind", None), getattr(hypothesis, "parent", None)
        lines.append(HypothesisLine(hypothesis_id=hid, statement=" ".join(statement.split()),
                                    kind=kind if isinstance(kind, str) else "",
                                    parent=parent if isinstance(parent, str) else ""))
    return tuple(lines)


def outcome_input(outcome: Any) -> OutcomeInput:
    """From `ost.read_outcome`'s `Outcome`: its text when set, else none."""
    return OutcomeInput(" ".join(outcome.text.split()) if getattr(outcome, "is_set", False) else "")


def input_key(items: "Sequence[ClaimItem]", hypotheses: "Sequence[HypothesisLine]", model: str,
              outcome: OutcomeInput = OutcomeInput()) -> str:
    """Every claim and hypothesis sent (order-free), the outcome, the model,
    the prompt version, the instructions and the tool schema. Never the
    previous tree: it is context, and keying on it would call again on
    unchanged inputs."""
    claims = sorted([i.fact_id, i.session_id, i.claim, sorted(list(b) for b in i.bearings)] for i in items)
    hyps = sorted([h.hypothesis_id, h.statement, h.kind, h.parent] for h in hypotheses)
    blob = json.dumps({"model": model, "version": PROMPT_VERSION, "claims": claims, "hypotheses": hyps,
                       "outcome": outcome.text, "system": _SYSTEM, "tool": _tool_schema()},
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def aliases(items: "Sequence[ClaimItem]") -> "dict[str, ClaimItem]":
    return {f"c{number}": item for number, item in enumerate(items, start=1)}


_SYSTEM = """You turn the claims extracted from a set of customer-discovery interviews into an opportunity solution tree, in Teresa Torres's sense: an outcome at the root, the opportunity space under it, solutions under opportunities, and the assumptions each solution rests on.

You are given: the outcome (or none), the operator's hypotheses (id, statement, and the operator's own kind and parent, often blank), the claims (an id, the interview it came from, the claim already abstracted into a sentence, and the hypotheses extraction said it bears on), and sometimes the previous tree.

OUTCOME: if one is given, echo it with proposed false. If none is given, propose one product outcome (a change in customer behaviour the team can influence, with a direction, not a business metric and not a deliverable) and set proposed true.

OPPORTUNITIES: unmet needs, pains or desires that, if addressed, would drive the outcome.
- Derive them from the claims first; map them to hypotheses second. A hypothesis is a label to reconcile against, never a reason for a node.
- Write each statement in the customer's first-person voice ("I can't tell when my build finished"). Ask: could a customer say this? Never a business goal or a metric.
- Each must be addressable in more than one way; if only one way, it is a solution, and the need behind it is the opportunity.
- Nest them: a child is one specific case of its parent. Each has at most one parent (parent_id, empty for a top-level node). Siblings are distinct: one can be addressed without the other. Break a broad need into children; do not make a node per claim; merge near-duplicates.
- evidence: the claims behind it, each with a bearing: experiences (the interviewee lived this need), not_experienced (they said they do not have it), already_met (something they use today already solves it). Cite only claims about the need itself.
- Never judge effort or how easy it is.

SOLUTIONS: things that could address an opportunity: a product, feature, service or workflow.
- Each sits under exactly one opportunity (opportunity_id). Keep each small.
- origin: customer (a claim proposed it), operator (a hypothesis states it), or model (you ideated it).
- evidence: the claims bearing on it, each supports or contradicts.
- assumptions: the riskiest things that must be true for it to work, at most three, each typed desirability, usability, feasibility, viability or ethical, with importance high or low and the claim_ids bearing on it (often none).

For every opportunity and solution:
- hypothesis_id: the operator hypothesis this node is, if any, else empty. Kinds must agree: an opportunity maps only to an opportunity-kind or unclassified hypothesis, a solution only to a solution-kind or unclassified one. Map each hypothesis at most once. When the hypothesis was phrased as a solution or a business goal and you reworded it as a need, put its statement in reframed_from.
- next_story: the next story to ask an interviewee for, about past behaviour, starting "Tell me about the last time" or "Walk me through a time". Never "would you" or a question about the future.

OPINION_CLAIM_IDS: praise, ratings, likes, "would recommend", and would or might statements about the future. Heard, not evidence: they are never cited as evidence and never become a node.

IDS: opportunities o1, o2, ...; solutions s1, s2, .... When a previous tree is given, keep its ids, statements and structure for every node the claims still support, and change a node only when the evidence calls for it.

Rules:
- Use only claim and hypothesis ids from the lists.
- Never write a count; counts are computed elsewhere.
- Claims that only answer the interviewer's scripted questions become an opportunity only when they show a need of the interviewee's own."""


def _evidence_schema(bearings: "Sequence[str]") -> dict:
    return {"type": "array", "items": {"type": "object", "properties": {
        "claim_id": {"type": "string"},
        "bearing": {"type": "string", "enum": list(bearings)},
    }, "required": ["claim_id", "bearing"]}}


def _tool_schema() -> dict:
    text = {"type": "string"}
    ids = {"type": "array", "items": {"type": "string"}}
    node = {"statement": text, "hypothesis_id": {"type": "string", "description": "Empty when none."},
            "reframed_from": {"type": "string", "description": "Empty unless a hypothesis was reworded."},
            "next_story": {"type": "string", "description": "A past-behaviour story prompt."}}
    return {
        "name": TOOL_NAME,
        "description": "Report the opportunity solution tree built from the interview claims.",
        "input_schema": {
            "type": "object",
            "properties": {
                "outcome": {"type": "object", "properties": {"text": text, "proposed": {"type": "boolean"}},
                            "required": ["text", "proposed"]},
                "opportunities": {"type": "array", "items": {"type": "object", "properties": {
                    "id": text, **node,
                    "parent_id": {"type": "string", "description": "Empty for a top-level opportunity."},
                    "evidence": _evidence_schema((EXPERIENCES, NOT_EXPERIENCED, ALREADY_MET)),
                }, "required": ["id", "statement", "parent_id", "evidence", "next_story"]}},
                "solutions": {"type": "array", "items": {"type": "object", "properties": {
                    "id": text, **node, "opportunity_id": text,
                    "origin": {"type": "string", "enum": list(ORIGINS)},
                    "evidence": _evidence_schema((SUPPORTS, CONTRADICTS)),
                    "assumptions": {"type": "array", "items": {"type": "object", "properties": {
                        "text": text, "type": {"type": "string", "enum": list(ASSUMPTION_TYPES)},
                        "importance": {"type": "string", "enum": list(IMPORTANCES)}, "claim_ids": ids,
                    }, "required": ["text", "type", "importance"]}},
                }, "required": ["id", "opportunity_id", "statement", "origin", "evidence", "next_story"]}},
                "opinion_claim_ids": {**ids, "description": "Praise and opinions: heard, not evidence."},
            },
            "required": ["outcome", "opportunities", "solutions", "opinion_claim_ids"],
        },
    }


def _prior_lines(prior: Optional[PriorTree]) -> str:
    if prior is None:
        return ""
    rows = [json.dumps({n.kind: n.node_id, "statement": n.statement,
                        ("parent_id" if n.kind == KIND_OPPORTUNITY else "opportunity_id"): n.parent_id or "",
                        "hypothesis_id": n.hypothesis_id}, ensure_ascii=False) for n in prior.nodes]
    return (f"\n\nThe previous tree (outcome: {json.dumps(prior.outcome, ensure_ascii=False)}), keep what the "
            f"claims still support:\n" + "\n".join(rows))


def assemble_request(items: "Sequence[ClaimItem]", hypotheses: "Sequence[HypothesisLine]", *, model: str,
                     outcome: OutcomeInput = OutcomeInput(), prior: Optional[PriorTree] = None,
                     max_tokens: int = DEFAULT_MAX_TOKENS) -> dict:
    """The exact kwargs for `client.messages.create`. Pure."""
    hyp_lines = "\n".join(json.dumps({"hypothesis": h.hypothesis_id, "statement": h.statement, "kind": h.kind,
                                      "parent": h.parent}, ensure_ascii=False) for h in hypotheses)
    claim_lines = "\n".join(
        json.dumps({"id": alias, "interview": item.session_id, "claim": item.claim,
                    "bears_on": [{"hypothesis": h, "stance": s} for h, s in item.bearings]}, ensure_ascii=False)
        for alias, item in aliases(items).items())
    given = json.dumps(outcome.text, ensure_ascii=False) if outcome.given else "none given: propose one"
    content = (f"Outcome: {given}\n\n{len(hypotheses)} hypotheses:\n{hyp_lines or '(none written yet)'}\n\n"
               f"{len(items)} claims:\n{claim_lines}{_prior_lines(prior)}\n\nCall {TOOL_NAME}.")
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


def synthesize(client: Any, items: "Sequence[ClaimItem]", hypotheses: "Sequence[HypothesisLine]", *, model: str,
               outcome: OutcomeInput = OutcomeInput(), prior: Optional[PriorTree] = None,
               max_tokens: int = DEFAULT_MAX_TOKENS, timeout_s: float = DEFAULT_TIMEOUT_S) -> Synthesis:
    """ONE call through the shared seam. Raises `SynthesisFailure` for
    anything that makes the whole answer untrusted. With a `prior` tree the
    result carries the diff against it."""
    from app.coach import synthesis_check, synthesis_diff, synthesis_validate  # they import this module

    request = assemble_request(items, hypotheses, model=model, outcome=outcome, prior=prior, max_tokens=max_tokens)
    bound = reasoning_client.with_timeout(client, timeout_s)
    try:
        response = bound.messages.create(**request)
    except Exception as exc:  # noqa: BLE001 -- a timeout, a connection error, anything
        # The type only, never the message: a vendor error can echo the request.
        raise SynthesisFailure(reason=f"exception ({type(exc).__name__})") from exc
    raw = synthesis_check.raw_answer(response)
    result = synthesis_validate.from_model(raw, items, hypotheses, outcome=outcome, model=model)
    if prior is not None:
        result = synthesis_diff.with_diff(result, prior)
    usage = getattr(response, "usage", None)
    logger.info("synthesis complete claims=%d opportunities=%d solutions=%d opinions=%d drops=%d "
                "usage_input_tokens=%s usage_output_tokens=%s",
                len(items), len(result.opportunities), len(result.solutions), len(result.opinion_fact_ids),
                len(result.drops), getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))
    return result
