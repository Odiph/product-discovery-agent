"""The synthesized opportunity solution tree as every surface shows it: the
terminal (`synthesis_cli`, `tree`), the hub's panel and MCP `get_synthesis`
and `get_tree` read this one projection, so they cannot count differently.

Every number and status word here is computed by code from the surviving
citations (`synthesis_status.py`), in distinct interviews over the
interviews with any extracted claim (`interview_summary.count_interviews`).
Warnings are recomputed on every view (`synthesis_warnings.py`).

`unplaced_hypotheses` are the operator's hypotheses no node maps: a causal
or pricing belief is neither a need nor a solution, so the tree may not
place it even when interviews bear on it. Each carries its standing over the
whole corpus (`interview_summary.standing`: supporting, contrary and
unclear interviews, and the distinct interviews touching it at all), so
"unplaced" never reads as "no evidence".

`cached` reads the cache for claims and hypotheses its caller loaded (MCP's
loaders, which the hub shares) and calls no model. Claims are the abstracted
`claim` from `FactRef`, never a quote.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from app.coach import interview_summary as summary_mod
from app.coach import ost as ost_mod
from app.coach import reasoning_client
from app.coach import synthesis as syn
from app.coach import synthesis_status as status_mod
from app.coach import synthesis_store as store
from app.coach import synthesis_types as t
from app.coach import synthesis_warnings as warnings_mod

STATUS_NO_CLAIMS = "no-claims"
STATUS_CORPUS_UNREADABLE = "corpus-unreadable"
THRESHOLD_NOTE = ("Single story, recurring and established (1, 2, 3+ interviews), and the solution signal "
                  "thresholds (3+ interviews, 2x the other side), are this tool's heuristic, not Torres's: "
                  "sizing is judgement. Only assumptions are ever tested.")


def command(project: str) -> str:
    where = f" --project {project}" if project else ""
    return f"python -m app synthesize{where} --yes"


def heard(count: int, total: int) -> str:
    return f"heard in {count} of {total} interview{'s' if total != 1 else ''}"


class _Projector:
    def __init__(self, result: t.Synthesis, refs: Sequence[Any], hypotheses: Sequence[Any]) -> None:
        self.result = result
        self.refs = {ref.fact_id: ref for ref in refs}
        self.by_id = {item.fact_id: item for item in syn.claim_items(refs)}
        self.all_refs = tuple(refs)
        self.hypotheses = {h.id: h for h in hypotheses}
        self.total = summary_mod.count_interviews(refs)
        self.statuses = status_mod.opportunity_statuses(result.opportunities, self.by_id)
        self.warnings = warnings_mod.warnings(result)
        self.children = status_mod.children_of(result.opportunities)
        self.solutions: "dict[str, list[t.Solution]]" = {}
        for solution in result.solutions:
            self.solutions.setdefault(solution.opportunity_id, []).append(solution)

    def claims(self, evidence: "Sequence[t.Evidence]") -> "list[dict]":
        groups: "dict[str, list[dict]]" = {}
        for row in evidence:
            ref = self.refs.get(row.fact_id)
            if ref is not None:
                groups.setdefault(ref.session_id, []).append(
                    {"fact_id": row.fact_id, "claim": ref.claim, "bearing": row.bearing})
        return [{"session_id": session, "facts": groups[session]} for session in sorted(groups)]

    def hypothesis(self, hypothesis_id: str) -> Optional[dict]:
        found = self.hypotheses.get(hypothesis_id)
        if found is None:
            return None
        return {"hypothesis_id": found.id, "statement": found.statement, "kind": found.kind}

    def node_warnings(self, node_id: str) -> "list[dict]":
        return [{"rule": w.rule, "message": w.message} for w in warnings_mod.for_node(self.warnings, node_id)]

    def solution(self, node: t.Solution) -> dict:
        signal = status_mod.solution_status(node, self.by_id)
        return {
            "id": node.node_id, "kind": t.KIND_SOLUTION, "statement": node.statement, "origin": node.origin,
            "opportunity_id": node.opportunity_id, "signal": signal.signal,
            "for_interviews": len(signal.for_in), "against_interviews": len(signal.against_in),
            "touching_interviews": signal.touching,
            "sessions": sorted(set(signal.for_in) | set(signal.against_in)),
            "claims_by_interview": self.claims(node.evidence), "hypothesis": self.hypothesis(node.hypothesis_id),
            "next_story": node.next_story, "warnings": self.node_warnings(node.node_id),
            "assumptions": [self.assumption(a) for a in sorted(
                node.assumptions, key=lambda a: not status_mod.is_leap_of_faith(a, self.by_id))],
        }

    def assumption(self, assumption: t.Assumption) -> dict:
        return {"text": assumption.text, "type": assumption.type, "importance": assumption.importance,
                "status": status_mod.UNTESTED,
                "evidence_interviews": len(status_mod.assumption_interviews(assumption, self.by_id)),
                "leap_of_faith": status_mod.is_leap_of_faith(assumption, self.by_id)}

    def opportunity(self, node: t.Opportunity) -> dict:
        status = self.statuses[node.node_id]
        return {
            "id": node.node_id, "kind": t.KIND_OPPORTUNITY, "statement": node.statement,
            "parent_id": node.parent_id, "interviews": len(status.heard_in), "sessions": list(status.heard_in),
            "heard": heard(len(status.heard_in), self.total), "status": status.status,
            "well_met_for_some": status.well_met, "well_met_interviews": len(status.met_in),
            "not_experienced_interviews": len(status.not_experienced_in),
            "claims_by_interview": self.claims(node.evidence), "hypothesis": self.hypothesis(node.hypothesis_id),
            "reframed_from": node.reframed_from, "next_story": node.next_story,
            "warnings": self.node_warnings(node.node_id),
            "children": [self.opportunity(child) for child in self.children.get(node.node_id, ())],
            "solutions": [self.solution(s) for s in self.solutions.get(node.node_id, ())],
        }

    def unplaced(self) -> "list[dict]":
        mapped = {n.hypothesis_id for n in (*self.result.opportunities, *self.result.solutions) if n.hypothesis_id}
        return [self.standing(h) for h in self.hypotheses.values() if h.id not in mapped]

    def standing(self, hypothesis: Any) -> dict:
        found = summary_mod.standing(hypothesis, self.all_refs, project="")
        return {"hypothesis_id": hypothesis.id, "statement": hypothesis.statement, "kind": hypothesis.kind,
                "supporting_interviews": found.supporting_interviews,
                "contrary_interviews": found.contrary_interviews,
                "unclear_interviews": found.unclear_interviews, "total_interviews": found.total_interviews}

    def opinions(self) -> "list[dict]":
        return [{"fact_id": f, "session_id": self.refs[f].session_id, "claim": self.refs[f].claim}
                for f in self.result.opinion_fact_ids if f in self.refs]


def _diff(diff: Optional[t.TreeDiff]) -> Optional[dict]:
    if diff is None:
        return None
    return {part: [{"kind": e.kind, "id": e.node_id, "statement": e.statement, "before": e.before,
                    "after": e.after} for e in getattr(diff, part)]
            for part in ("added", "removed", "moved", "renamed")}


def _drops(drops: "Sequence[t.Drop]") -> "dict[str, Any]":
    counts: "dict[str, int]" = {}
    for drop in drops:
        counts[drop.rule] = counts.get(drop.rule, 0) + 1
    return {"counts": counts, "details": [{"rule": d.rule, "what": d.what} for d in drops],
            "lines": [f"{n} {t.DROP_WORDS.get(rule, rule)}" for rule, n in counts.items()]}


def view(result: t.Synthesis, refs: Sequence[Any], hypotheses: Sequence[Any]) -> "dict[str, Any]":
    shown = _Projector(result, refs, hypotheses)
    tree = [shown.opportunity(n) for n in shown.children.get(None, ())]
    return {
        "model": result.model,
        "total_interviews": shown.total,
        "outcome": {"text": result.outcome.text, "proposed": result.outcome.proposed},
        "tree": tree,
        "unplaced_hypotheses": shown.unplaced(),
        "opinions": shown.opinions(),
        "warnings": shown.node_warnings(""),
        "threshold_note": THRESHOLD_NOTE,
        "diff": _diff(result.diff),
        "drops": _drops(result.drops),
    }


def load_fresh(context_dir: Path, refs: Sequence[Any], hypotheses: Sequence[Any]) -> store.CacheState:
    """The cache state for these claims, hypotheses and the node's outcome. Never calls a model."""
    items = syn.claim_items(refs)
    model = reasoning_client.resolve_judge_model(context_dir)
    outcome = syn.outcome_input(ost_mod.read_outcome(context_dir))
    return store.load(context_dir, items, syn.hypothesis_lines(hypotheses), model, outcome)


def cached(context_dir: Path, *, project: str, refs: Sequence[Any], hypotheses: Sequence[Any],
           unreadable: bool = False) -> "dict[str, Any]":
    """The cached synthesis for one node, or why there is none. Never calls a
    model. `refs`: `FactRef`s; `unreadable`: the claims or hypotheses failed to load."""
    context_dir = Path(context_dir)
    how = command(project)
    if unreadable:
        return {"status": STATUS_CORPUS_UNREADABLE, "reason": "the claims or hypotheses could not be read",
                "how_to": how}
    if not syn.claim_items(refs):
        return {"status": STATUS_NO_CLAIMS, "reason": "no extracted claims yet",
                "how_to": "python -m app extract --all" + (f" --project {project}" if project else "")}
    state = load_fresh(context_dir, refs, hypotheses)
    if state.status == store.STALE:
        return {"status": state.status, "reason": state.reason, "how_to": how,
                **_stale(context_dir, project, refs, hypotheses)}
    if state.status != store.FRESH:
        return {"status": state.status, "reason": state.reason, "how_to": how}
    built_from = sorted({i.session_id for i in syn.claim_items(refs)})
    return {"status": store.FRESH, "reason": "", "how_to": how, "key": state.synthesis.key,
            "built_from": built_from, **view(state.synthesis, refs, hypotheses)}


def agent_prompt(project: str) -> str:
    where, flag = (f" for project {project}", f" --project {project}") if project else ("", "")
    return (f"Rerun the synthesis{where}: run python -m app synthesize{flag} --yes from the Product "
            f"Discovery Agent checkout, then tell me what changed in the tree.")


_NODE_REMOVING = (t.DROP_NO_EVIDENCE, t.DROP_ORPHAN_SOLUTION)
"""The drop rules that take a whole node out of a stale tree (its last claim went)."""


def _stale(context_dir: Path, project: str, refs: Sequence[Any], hypotheses: Sequence[Any]) -> "dict[str, Any]":
    """What a stale cache still offers: its last tree over the claims that
    survive, how many citations that cost, and the interviews new since."""
    items = syn.claim_items(refs)
    model = reasoning_client.resolve_judge_model(context_dir)
    outcome = syn.outcome_input(ost_mod.read_outcome(context_dir))
    last = store.load_last(context_dir, items, syn.hypothesis_lines(hypotheses), model, outcome)
    extra: "dict[str, Any]" = {"last_tree": None, "last_tree_dropped": 0, "last_tree_removed_nodes": 0,
                               "new_sessions": None,
                               "agent_command": f"/discovery:synthesize {project}".rstrip(),
                               "agent_prompt": agent_prompt(project)}
    if last is not None:
        result, drops, stored = last
        extra.update(last_tree={"key": result.key, **view(result, refs, hypotheses)},
                     last_tree_dropped=sum(d.rule == t.DROP_UNKNOWN_CLAIM for d in drops),
                     last_tree_removed_nodes=sum(d.rule in _NODE_REMOVING for d in drops))
        if stored is not None:
            extra["new_sessions"] = sorted({i.session_id for i in items} - set(stored))
    return extra
