"""The synthesis cache: `context/synthesis.json`. Its only job is that file.

One tree per node, keyed by `synthesis.input_key`: every claim and
hypothesis sent, the outcome, the model, the prompt version, the
instructions and the tool schema. So a re-run with no new facts finds it
FRESH and calls nothing; a cache over other claims, another model, another
outcome or another prompt is STALE; a file that does not parse, or whose
tree breaks a rule the validator enforces (a cited fact not in the corpus, a
cycle, a solution without an opportunity, a node from no interview), is
UNREADABLE. Neither of the last two is ever shown.

The load re-runs `synthesis_validate.from_store` and refuses any drop it
would make: a cache is never repaired. Statuses and warnings are not stored:
they are recomputed from the citations on every view.

`previous` reads the last tree's labels and structure even when it is
stale, so the next call can be asked to keep them (`synthesis_diff.py`).
Holds model-written statements and fact ids, never claim text or a quote,
and lives under `context/`, which is git-ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional, Sequence

from app.coach import json_cache, synthesis_check, synthesis_validate
from app.coach import synthesis as syn
from app.coach import synthesis_types as t
from app.coach.json_cache import ABSENT, FRESH, STALE, UNREADABLE  # noqa: F401 -- re-exported

CACHE_FILENAME = "synthesis.json"
FORMAT_VERSION = 2
"""2: the opportunity solution tree (1 held themes and contradictions)."""
_DIFF_PARTS = ("added", "removed", "moved", "renamed")


@dataclass(frozen=True)
class CacheState:
    status: str
    synthesis: Optional[t.Synthesis] = None
    """Set only when `status == FRESH`."""
    reason: str = ""


def _evidence(rows: "Sequence[t.Evidence]") -> list:
    return [{"fact_id": e.fact_id, "bearing": e.bearing} for e in rows]


def _diff(diff: Optional[t.TreeDiff]) -> Optional[dict]:
    if diff is None:
        return None
    return {part: [{"kind": e.kind, "node_id": e.node_id, "statement": e.statement, "before": e.before,
                    "after": e.after} for e in getattr(diff, part)] for part in _DIFF_PARTS}


def write(context_dir: Path, result: t.Synthesis, *, sessions: "Sequence[str]" = ()) -> Path:
    return json_cache.write(Path(context_dir) / CACHE_FILENAME, {
        "version": FORMAT_VERSION,
        "model": result.model,
        "key": result.key,
        "sessions": sorted(set(sessions)),
        "outcome": {"text": result.outcome.text, "proposed": result.outcome.proposed},
        "opportunities": [{"id": n.node_id, "statement": n.statement, "parent_id": n.parent_id,
                           "evidence": _evidence(n.evidence), "hypothesis_id": n.hypothesis_id,
                           "reframed_from": n.reframed_from, "next_story": n.next_story}
                          for n in result.opportunities],
        "solutions": [{"id": n.node_id, "opportunity_id": n.opportunity_id, "statement": n.statement,
                       "origin": n.origin, "evidence": _evidence(n.evidence), "hypothesis_id": n.hypothesis_id,
                       "next_story": n.next_story,
                       "assumptions": [{"text": a.text, "type": a.type, "importance": a.importance,
                                        "fact_ids": list(a.fact_ids)} for a in n.assumptions]}
                      for n in result.solutions],
        "opinion_fact_ids": list(result.opinion_fact_ids),
        "drops": [{"rule": d.rule, "what": d.what} for d in result.drops],
        "diff": _diff(result.diff),
    })


def _string(value, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{what} is not a string")
    return value


def _drops(raw) -> "tuple[t.Drop, ...]":
    if not isinstance(raw, list):
        raise ValueError("drops is not a list")
    drops = []
    for entry in raw:
        rule = _string(entry.get("rule") if isinstance(entry, dict) else None, "a drop's rule")
        if rule not in t.DROP_RULES:
            raise ValueError(f"the drop rule {rule!r} is not one of the validator's")
        drops.append(t.Drop(rule=rule, what=_string(entry.get("what"), "a drop's subject")))
    return tuple(drops)


def _read_diff(raw) -> Optional[t.TreeDiff]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("diff is not an object")
    parts = {}
    for part in _DIFF_PARTS:
        entries = raw.get(part, [])
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            raise ValueError(f"diff {part} is not a list of objects")
        parts[part] = tuple(t.DiffEntry(**{name: _string(e.get(name, ""), f"a diff {name}")
                                           for name in ("kind", "node_id", "statement", "before", "after")})
                            for e in entries)
    return t.TreeDiff(**parts)


def load(context_dir: Path, items: "Sequence[t.ClaimItem]", hypotheses: "Sequence[t.HypothesisLine]",
         model: str, outcome: t.OutcomeInput = t.OutcomeInput()) -> CacheState:
    payload, status, reason = json_cache.read(Path(context_dir) / CACHE_FILENAME, FORMAT_VERSION, "synthesis")
    if payload is None:
        return CacheState(status, reason=reason)
    made_with = payload.get("model")
    if made_with != model:
        return CacheState(STALE, reason=f"it was made by {made_with!r}, and the judge model is now {model!r}")
    if payload.get("key") != syn.input_key(items, hypotheses, model, outcome):
        return CacheState(STALE, reason="the claims, the hypotheses, the outcome or the instructions changed "
                                        "since it was made")
    try:
        raw = synthesis_check.parse(payload, synthesis_check.FACT_KEYS)
        result = synthesis_validate.from_store(raw, items, hypotheses, outcome=outcome, model=model,
                                               key=str(payload["key"]))
        result = replace(result, drops=_drops(payload.get("drops", [])), diff=_read_diff(payload.get("diff")))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return CacheState(UNREADABLE, reason=f"{CACHE_FILENAME} is malformed ({exc})")
    return CacheState(FRESH, synthesis=result)


def load_last(context_dir: Path, items: "Sequence[t.ClaimItem]", hypotheses: "Sequence[t.HypothesisLine]",
              model: str, outcome: t.OutcomeInput = t.OutcomeInput()
              ) -> "Optional[tuple[t.Synthesis, tuple[t.Drop, ...], Optional[tuple[str, ...]]]]":
    """The stored tree, fresh or stale, with every citation to a claim that
    is gone dropped (and counted) rather than refused; plus the interviews it
    was built from (None for a cache written before they were recorded).
    None when there is no readable tree. Never raises."""
    payload, _status, _reason = json_cache.read(Path(context_dir) / CACHE_FILENAME, FORMAT_VERSION, "synthesis")
    if payload is None:
        return None
    known = {item.fact_id for item in items}
    try:
        raw = synthesis_check.parse(payload, synthesis_check.FACT_KEYS)
        result, drops = synthesis_validate.build(raw, lambda ref: ref if ref in known else None, items,
                                                 hypotheses, outcome=outcome,
                                                 model=str(payload.get("model") or model),
                                                 key=str(payload["key"]))
        stored = payload.get("sessions")
        sessions = (tuple(sorted({s for s in stored if isinstance(s, str)}))
                    if isinstance(stored, list) else None)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return result, drops, sessions


def previous(context_dir: Path) -> Optional[t.PriorTree]:
    """The last tree's labels and structure, fresh or stale; None when there
    is no version-2 tree to read. Never raises."""
    payload, _status, _reason = json_cache.read(Path(context_dir) / CACHE_FILENAME, FORMAT_VERSION, "synthesis")
    if payload is None:
        return None
    try:
        raw = synthesis_check.parse(payload, synthesis_check.FACT_KEYS)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    # Not validated against the corpus (it may be stale), so what goes back
    # into the prompt is cleaned and capped, and a repeated or blank id skipped.
    cap, nodes, seen = synthesis_validate.clean, [], set()
    rows = [(t.KIND_OPPORTUNITY, n, n["parent_id"] if isinstance(n["parent_id"], str) else None)
            for n in raw["opportunities"]] + [(t.KIND_SOLUTION, n, n["opportunity_id"]) for n in raw["solutions"]]
    for kind, n, parent in rows:
        node_id, statement = cap(n["id"], syn.MAX_STATEMENT_CHARS), cap(n["statement"], syn.MAX_STATEMENT_CHARS)
        if not node_id or not statement or node_id in seen:
            continue
        seen.add(node_id)
        nodes.append(t.PriorNode(kind=kind, node_id=node_id, statement=statement,
                                 parent_id=cap(parent, syn.MAX_STATEMENT_CHARS) or None if parent else None,
                                 hypothesis_id=cap(n["hypothesis_id"], syn.MAX_STATEMENT_CHARS)))
    return t.PriorTree(outcome=cap(raw["outcome"]["text"], syn.MAX_STATEMENT_CHARS), nodes=tuple(nodes))
