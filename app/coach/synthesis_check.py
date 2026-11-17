"""The synthesis answer's SHAPE, checked in code (`synthesis.py`'s docstring).

A wrong shape (no tool block, a required field missing or of the wrong
type, an answer cut short) makes the whole answer untrusted:
`SynthesisFailure`. A well-shaped answer is returned as plain dicts with its
values still as the model wrote them; `synthesis_validate.py` then applies
the tree's rules and records each drop.

The same parser reads the cache (`synthesis_store.py`), whose file holds the
same shape with fact ids where the model wrote claim aliases: `CLAIM_KEYS`
for the model, `FACT_KEYS` for the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.coach.synthesis import TOOL_NAME, SynthesisFailure

# Same set `extract` and `topics` refuse: an answer cut short may have lost whole branches.
_UNTRUSTED_STOP_REASONS = frozenset({"refusal", "max_tokens", "pause_turn", "model_context_window_exceeded"})


@dataclass(frozen=True)
class Keys:
    one: str
    many: str
    opinions: str


CLAIM_KEYS = Keys(one="claim_id", many="claim_ids", opinions="opinion_claim_ids")
FACT_KEYS = Keys(one="fact_id", many="fact_ids", opinions="opinion_fact_ids")


def raw_answer(response: Any) -> dict:
    """The answer, shape-checked, values still as the model wrote them."""
    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason in _UNTRUSTED_STOP_REASONS:
        raise SynthesisFailure(reason="untrusted-stop-reason", stop_reason=stop_reason)
    for block in getattr(response, "content", None) or ():
        if getattr(block, "type", None) != "tool_use" or getattr(block, "name", None) != TOOL_NAME:
            continue
        try:
            return parse(block.input, CLAIM_KEYS)
        except (KeyError, TypeError, ValueError) as exc:
            raise SynthesisFailure(reason="parse-error", stop_reason=stop_reason) from exc
    raise SynthesisFailure(reason="no-tool-use-block", stop_reason=stop_reason)


def _list(entry: Mapping, name: str, *, required: bool) -> list:
    if name not in entry or entry[name] is None:
        if required:
            raise ValueError(f"{name} is missing")
        return []
    value = entry[name]
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _strings(entry: Mapping, name: str, *, required: bool) -> "list[str]":
    value = _list(entry, name, required=required)
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be an array of strings")
    return value


def _string(entry: Mapping, name: str, *, required: bool = False) -> str:
    if name not in entry or entry[name] is None:
        if required:
            raise ValueError(f"{name} is missing")
        return ""
    value = entry[name]
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _object(value: Any, what: str) -> Mapping:
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be an object")
    return value


def _parent(entry: Mapping) -> "str | list[str] | None":
    """A string, empty or null for none; an array is kept as written, so
    the validator can drop a node given more than one parent."""
    value = entry.get("parent_id")
    if value is None or isinstance(value, str):
        return value or None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ValueError("parent_id must be a string")


def _evidence(entry: Mapping, keys: Keys) -> "list[tuple[str, str]]":
    rows = []
    for row in _list(entry, "evidence", required=True):
        row = _object(row, "an evidence row")
        rows.append((_string(row, keys.one, required=True), _string(row, "bearing", required=True)))
    return rows


def _node(entry: Any, keys: Keys) -> dict:
    entry = _object(entry, "a node")
    return {"id": _string(entry, "id", required=True), "statement": _string(entry, "statement", required=True),
            "evidence": _evidence(entry, keys), "hypothesis_id": _string(entry, "hypothesis_id"),
            "reframed_from": _string(entry, "reframed_from"), "next_story": _string(entry, "next_story")}


def _assumption(entry: Any, keys: Keys) -> dict:
    entry = _object(entry, "an assumption")
    return {"text": _string(entry, "text", required=True), "type": _string(entry, "type"),
            "importance": _string(entry, "importance"), "refs": _strings(entry, keys.many, required=False)}


def parse(payload: Any, keys: Keys) -> dict:
    payload = _object(payload, "the answer")
    outcome = payload.get("outcome") or {}
    outcome = _object(outcome, "outcome")
    proposed = outcome.get("proposed", False)
    if not isinstance(proposed, bool):
        raise ValueError("outcome.proposed must be a boolean")
    opportunities = [{**_node(entry, keys), "parent_id": _parent(entry)}
                     for entry in _list(payload, "opportunities", required=True)]
    solutions = []
    for entry in _list(payload, "solutions", required=True):
        node = _node(entry, keys)
        entry = _object(entry, "a solution")
        solutions.append({**node, "opportunity_id": _string(entry, "opportunity_id", required=True),
                          "origin": _string(entry, "origin"),
                          "assumptions": [_assumption(a, keys) for a in _list(entry, "assumptions", required=False)]})
    return {"outcome": {"text": _string(outcome, "text"), "proposed": proposed},
            "opportunities": opportunities, "solutions": solutions,
            "opinions": _strings(payload, keys.opinions, required=True)}
