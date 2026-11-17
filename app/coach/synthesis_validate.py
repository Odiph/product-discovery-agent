"""The tree's HARD rules, enforced in code. Each drops what breaks it and
records the drop (`synthesis_types.DROP_*`); nothing is dropped silently.

- a cited claim id the request never sent: the citation is dropped;
- a bearing that does not belong to the node's kind: the citation is dropped;
- an opportunity listed twice: the later copy is dropped; listed with more
  than one parent (an array, or copies with different parents): every copy;
- a parent id that is no kept opportunity: the node is lifted to the top
  level (the reference is what is dropped);
- a cycle of parents: every opportunity on it;
- a solution whose opportunity is not kept: dropped;
- a node whose evidence comes from no interview (an opportunity counts its
  own and its descendants' `experiences` claims; a solution its supporting
  and contradicting ones): dropped;
- a hypothesis id not in the project, of the other kind, or mapped by an
  earlier node: the mapping is dropped, the node kept.

`from_model` resolves the model's claim aliases first; `from_store` reads
the cache's fact ids and refuses any NEW drop, so a tampered cache is
unreadable rather than quietly repaired.
"""

from __future__ import annotations

from dataclasses import replace as _replace
from typing import Callable, Mapping, Optional, Sequence

from app.coach import synthesis_types as t
from app.coach.synthesis import (
    MAX_ASSUMPTION_CHARS, MAX_STATEMENT_CHARS, MAX_STORY_CHARS, aliases, input_key,
)

Resolve = Callable[[str], Optional[str]]


def clean(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit].strip() if isinstance(value, str) else ""


class _Run:
    """One validation pass: the resolver and the drops it records."""

    def __init__(self, resolve: Resolve) -> None:
        self.resolve = resolve
        self.drops: "list[t.Drop]" = []

    def drop(self, rule: str, what: str) -> None:
        self.drops.append(t.Drop(rule=rule, what=clean(what, MAX_STATEMENT_CHARS) or t.DROP_UNSTATED))

    def facts(self, refs: Sequence[str]) -> "tuple[str, ...]":
        found = []
        for ref in dict.fromkeys(r.strip() for r in refs):
            fact_id = self.resolve(ref)
            if fact_id is None:
                self.drop(t.DROP_UNKNOWN_CLAIM, ref)
            elif fact_id not in found:
                found.append(fact_id)
        return tuple(found)

    def evidence(self, node_id: str, rows, allowed: "Sequence[str]") -> "tuple[t.Evidence, ...]":
        kept: "list[t.Evidence]" = []
        for ref, bearing in rows:
            bearing = bearing.strip().lower()
            if bearing not in allowed:
                self.drop(t.DROP_BAD_BEARING, f"{node_id}: {bearing or '(none)'}")
                continue
            for fact_id in self.facts([ref]):
                row = t.Evidence(fact_id=fact_id, bearing=bearing)
                if row not in kept:
                    kept.append(row)
        return tuple(kept)


def _parent_of(run: _Run, node_id: str, raw) -> "tuple[bool, Optional[str]]":
    """(kept, parent id). A list of two or more distinct parents drops the node."""
    if isinstance(raw, list):
        distinct = list(dict.fromkeys(p.strip() for p in raw if p.strip()))
        if len(distinct) > 1:
            run.drop(t.DROP_MULTI_PARENT, node_id)
            return False, None
        raw = distinct[0] if distinct else None
    return True, (raw.strip() or None) if isinstance(raw, str) else None


def _parents(raw) -> "tuple[str, ...]":
    """The distinct parent ids written, stripped: `"A"`, `" A"` and `["A"]` are one parent."""
    values = raw if isinstance(raw, list) else [raw]
    return tuple(dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()))


def _opportunities(run: _Run, raw: "Sequence[Mapping]") -> "list[t.Opportunity]":
    parents_by_id: "dict[str, set]" = {}
    for entry in raw:
        parents_by_id.setdefault(entry["id"].strip(), set()).add(_parents(entry["parent_id"]))
    nodes, seen = [], set()
    for entry in raw:
        node_id, statement = entry["id"].strip(), clean(entry["statement"], MAX_STATEMENT_CHARS)
        if not node_id or not statement:
            run.drop(t.DROP_UNSTATED, node_id or statement)
            continue
        if len(parents_by_id[node_id]) > 1:
            if node_id not in seen:
                run.drop(t.DROP_MULTI_PARENT, f"{node_id}: {statement}")
            seen.add(node_id)
            continue
        if node_id in seen:
            run.drop(t.DROP_DUPLICATE_ID, f"{node_id}: {statement}")
            continue
        seen.add(node_id)
        kept, parent = _parent_of(run, f"{node_id}: {statement}", entry["parent_id"])
        if not kept:
            continue
        nodes.append(t.Opportunity(
            node_id=node_id, statement=statement, parent_id=parent,
            evidence=run.evidence(node_id, entry["evidence"], t.OPPORTUNITY_BEARINGS),
            hypothesis_id=entry["hypothesis_id"].strip(), reframed_from=clean(entry["reframed_from"],
                                                                              MAX_STATEMENT_CHARS),
            next_story=clean(entry["next_story"], MAX_STORY_CHARS)))
    return nodes


def _on_cycle(node_id: str, parent_of: "Mapping[str, Optional[str]]") -> bool:
    seen, current = set(), parent_of.get(node_id)
    while current is not None and current in parent_of:
        if current == node_id:
            return True
        if current in seen:
            return False  # a cycle above this node, not through it
        seen.add(current)
        current = parent_of[current]
    return False


def _structure(run: _Run, nodes: "list[t.Opportunity]") -> "list[t.Opportunity]":
    """Cycles dropped, then every parent that is no kept node lifted to the top."""
    parent_of = {n.node_id: n.parent_id for n in nodes}
    cyclic = {n.node_id for n in nodes if _on_cycle(n.node_id, parent_of)}
    for node in nodes:
        if node.node_id in cyclic:
            run.drop(t.DROP_CYCLE, f"{node.node_id}: {node.statement}")
    kept = [n for n in nodes if n.node_id not in cyclic]
    ids = {n.node_id for n in kept}
    lifted = []
    for node in kept:
        if node.parent_id is not None and node.parent_id not in ids:
            run.drop(t.DROP_UNKNOWN_PARENT, f"{node.node_id}: parent {node.parent_id}")
            node = _replace(node, parent_id=None)
        lifted.append(node)
    return lifted


def _experienced(nodes: "Sequence[t.Opportunity]", by_id: "Mapping[str, t.ClaimItem]") -> "dict[str, set]":
    """Each opportunity's interviews with `experiences` evidence, its descendants' included."""
    own = {n.node_id: {by_id[e.fact_id].session_id for e in n.evidence if e.bearing == t.EXPERIENCES}
           for n in nodes}
    children: "dict[Optional[str], list[str]]" = {}
    for n in nodes:
        children.setdefault(n.parent_id, []).append(n.node_id)

    def total(node_id: str) -> set:
        found = set(own[node_id])
        for child in children.get(node_id, ()):
            found |= total(child)
        return found

    return {n.node_id: total(n.node_id) for n in nodes}


def _solutions(run: _Run, raw: "Sequence[Mapping]", kept_opportunities: set, taken: set,
               by_id: "Mapping[str, t.ClaimItem]") -> "list[t.Solution]":
    nodes = []
    for entry in raw:
        node_id, statement = entry["id"].strip(), clean(entry["statement"], MAX_STATEMENT_CHARS)
        label = f"{node_id}: {statement}"
        if not node_id or not statement:
            run.drop(t.DROP_UNSTATED, node_id or statement)
            continue
        if node_id in taken:
            run.drop(t.DROP_DUPLICATE_ID, label)
            continue
        if entry["opportunity_id"].strip() not in kept_opportunities:
            run.drop(t.DROP_ORPHAN_SOLUTION, label)
            continue
        evidence = run.evidence(node_id, entry["evidence"], t.SOLUTION_BEARINGS)
        if not {by_id[e.fact_id].session_id for e in evidence}:
            run.drop(t.DROP_NO_EVIDENCE, label)
            continue
        taken.add(node_id)
        origin = entry["origin"].strip().lower()
        nodes.append(t.Solution(
            node_id=node_id, opportunity_id=entry["opportunity_id"].strip(), statement=statement,
            origin=origin if origin in t.ORIGINS else t.ORIGIN_UNKNOWN, evidence=evidence,
            hypothesis_id=entry["hypothesis_id"].strip(), next_story=clean(entry["next_story"], MAX_STORY_CHARS),
            assumptions=tuple(_assumption(run, a) for a in entry["assumptions"] if clean(a["text"], 1))))
    return nodes


def _assumption(run: _Run, entry: Mapping) -> t.Assumption:
    kind, importance = entry["type"].strip().lower(), entry["importance"].strip().lower()
    return t.Assumption(text=clean(entry["text"], MAX_ASSUMPTION_CHARS),
                        type=kind if kind in t.ASSUMPTION_TYPES else t.TYPE_UNKNOWN,
                        importance=importance if importance in t.IMPORTANCES else t.TYPE_UNKNOWN,
                        fact_ids=run.facts(entry["refs"]))


def _mapped(run: _Run, node, kind: str, hypotheses: "Mapping[str, t.HypothesisLine]", used: set):
    """The node with its hypothesis mapping kept, or cleared and recorded."""
    hid = node.hypothesis_id
    if not hid:
        return _replace(node, reframed_from="") if isinstance(node, t.Opportunity) else node
    label = f"{node.node_id} -> {hid}"
    rule = (t.DROP_UNKNOWN_HYPOTHESIS if hid not in hypotheses
            else t.DROP_HYPOTHESIS_KIND if hypotheses[hid].kind and hypotheses[hid].kind != kind
            else t.DROP_HYPOTHESIS_TWICE if hid in used else "")
    if rule:
        run.drop(rule, label)
        cleared = {"hypothesis_id": ""}
        if isinstance(node, t.Opportunity):
            cleared["reframed_from"] = ""
        return _replace(node, **cleared)
    used.add(hid)
    return node


def build(raw: Mapping, resolve: Resolve, items: "Sequence[t.ClaimItem]",
          hypotheses: "Sequence[t.HypothesisLine]", *, outcome: t.OutcomeInput, model: str,
          key: str) -> "tuple[t.Synthesis, tuple[t.Drop, ...]]":
    """The checked tree and the drops this pass made."""
    run = _Run(resolve)
    by_id = {item.fact_id: item for item in items}
    opportunities = _structure(run, _opportunities(run, raw["opportunities"]))
    experienced = _experienced(opportunities, by_id)
    for node in opportunities:
        if not experienced[node.node_id]:
            run.drop(t.DROP_NO_EVIDENCE, f"{node.node_id}: {node.statement}")
    opportunities = [n for n in opportunities if experienced[n.node_id]]
    kept_ids = {n.node_id for n in opportunities}
    solutions = _solutions(run, raw["solutions"], kept_ids, set(kept_ids), by_id)
    known, used = {h.hypothesis_id: h for h in hypotheses}, set()
    opportunities = [_mapped(run, n, t.KIND_OPPORTUNITY, known, used) for n in opportunities]
    solutions = [_mapped(run, n, t.KIND_SOLUTION, known, used) for n in solutions]
    if outcome.given:
        root = t.OutcomeNode(text=outcome.text, proposed=False)
    else:
        root = t.OutcomeNode(text=clean(raw["outcome"]["text"], MAX_STATEMENT_CHARS), proposed=True)
    result = t.Synthesis(model=model, key=key, outcome=root, opportunities=tuple(opportunities),
                         solutions=tuple(solutions), opinion_fact_ids=run.facts(raw["opinions"]),
                         drops=tuple(run.drops))
    return result, tuple(run.drops)


def from_model(raw: Mapping, items: "Sequence[t.ClaimItem]", hypotheses: "Sequence[t.HypothesisLine]", *,
               outcome: t.OutcomeInput, model: str) -> t.Synthesis:
    by_alias = aliases(items)

    def resolve(alias: str) -> Optional[str]:
        item = by_alias.get(alias)
        return item.fact_id if item is not None else None

    result, _ = build(raw, resolve, items, hypotheses, outcome=outcome, model=model,
                      key=input_key(items, hypotheses, model, outcome))
    return result


def from_store(raw: Mapping, items: "Sequence[t.ClaimItem]", hypotheses: "Sequence[t.HypothesisLine]", *,
               outcome: t.OutcomeInput, model: str, key: str) -> t.Synthesis:
    """Raises ValueError when the stored tree breaks any rule: a cache is
    never repaired on load."""
    known = {item.fact_id for item in items}
    result, drops = build(raw, lambda ref: ref if ref in known else None, items, hypotheses,
                          outcome=outcome, model=model, key=key)
    if drops:
        raise ValueError("the stored tree breaks the rules: "
                         + "; ".join(f"{d.rule} ({d.what})" for d in drops[:5]))
    changed = _repairs(raw, result)
    if changed:
        raise ValueError(f"the stored tree is not in the form the checks write: {changed}")
    return result


def _repairs(raw: Mapping, result: t.Synthesis) -> str:
    """What the rebuild changed WITHOUT a drop (a cleaned statement, a merged
    citation, a skipped assumption, another outcome): empty when nothing."""
    if (raw["outcome"]["text"], raw["outcome"]["proposed"]) != (result.outcome.text, result.outcome.proposed):
        return "the outcome"
    if [f for f in raw["opinions"]] != list(result.opinion_fact_ids):
        return "the opinions"
    pairs = list(zip(raw["opportunities"], result.opportunities)) + list(zip(raw["solutions"], result.solutions))
    for entry, node in pairs:
        stored = (entry["id"], entry["statement"], len(entry["evidence"]), entry["next_story"],
                  [(a["text"], a["type"], a["importance"]) for a in entry.get("assumptions", [])])
        rebuilt = (node.node_id, node.statement, len(node.evidence), node.next_story,
                   [(a.text, a.type, a.importance) for a in getattr(node, "assumptions", ())])
        if stored != rebuilt or [b for _f, b in entry["evidence"]] != [e.bearing for e in node.evidence]:
            return f"node {node.node_id}"
    return ""
