"""Stability between runs: the previous tree, sent back as context, and the
diff against it, which the terminal reports and the views carry.

`prior_of` keeps labels and structure only (node ids, statements, parents,
mapped hypothesis ids): model-written text and ids, never a claim. A new
node is matched to an old one of the same kind by, in order, the same mapped
hypothesis, the same statement, the same id, then statement words in common
(`MATCH_AT`). Matched with another statement: renamed. Matched under
another parent: moved. Unmatched new: added. Unmatched old: removed.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Mapping, Optional, Sequence

from app.coach import synthesis_types as t
from app.coach.synthesis_warnings import words, jaccard

MATCH_AT = 0.5
TOP_LEVEL = "(top level)"


def prior_of(synthesis: t.Synthesis) -> t.PriorTree:
    nodes = [t.PriorNode(kind=t.KIND_OPPORTUNITY, node_id=n.node_id, statement=n.statement, parent_id=n.parent_id,
                         hypothesis_id=n.hypothesis_id) for n in synthesis.opportunities]
    nodes += [t.PriorNode(kind=t.KIND_SOLUTION, node_id=n.node_id, statement=n.statement,
                          parent_id=n.opportunity_id, hypothesis_id=n.hypothesis_id) for n in synthesis.solutions]
    return t.PriorTree(outcome=synthesis.outcome.text, nodes=tuple(nodes))


def _same(a: str, b: str) -> bool:
    return " ".join(a.casefold().split()) == " ".join(b.casefold().split())


_RULES: "tuple[Callable[[t.PriorNode, t.PriorNode], bool], ...]" = (
    lambda new, old: bool(new.hypothesis_id) and new.hypothesis_id == old.hypothesis_id,
    lambda new, old: _same(new.statement, old.statement),
    lambda new, old: new.node_id == old.node_id,
    lambda new, old: jaccard(words(new.statement), words(old.statement)) >= MATCH_AT,
)


def match(before: "Sequence[t.PriorNode]", after: "Sequence[t.PriorNode]") -> "dict[int, int]":
    """{index in `after`: index in `before`}, one rule at a time over every
    node, so a strong match is never taken by a weaker one first."""
    pairs: "dict[int, int]" = {}
    for rule in _RULES:
        for i, new in enumerate(after):
            if i in pairs:
                continue
            for j, old in enumerate(before):
                if j not in pairs.values() and old.kind == new.kind and rule(new, old):
                    pairs[i] = j
                    break
    return pairs


def _statement_of(nodes: "Sequence[t.PriorNode]", node_id: Optional[str]) -> str:
    if node_id is None:
        return TOP_LEVEL
    return next((n.statement for n in nodes if n.node_id == node_id and n.kind == t.KIND_OPPORTUNITY), node_id)


def diff(before: t.PriorTree, after: t.PriorTree) -> t.TreeDiff:
    old, new = before.nodes, after.nodes
    pairs = match(old, new)
    old_id_of: "Mapping[str, str]" = {new[i].node_id: old[j].node_id for i, j in pairs.items()
                                     if new[i].kind == t.KIND_OPPORTUNITY}
    added, moved, renamed = [], [], []
    for i, node in enumerate(new):
        if i not in pairs:
            added.append(t.DiffEntry(kind=node.kind, node_id=node.node_id, statement=node.statement))
            continue
        was = old[pairs[i]]
        if not _same(node.statement, was.statement):
            renamed.append(t.DiffEntry(kind=node.kind, node_id=node.node_id, statement=node.statement,
                                       before=was.statement))
        # A new parent that matches no old node is a move even from the top level,
        # where the old parent is None too.
        under_new_parent = node.parent_id is not None and node.parent_id not in old_id_of
        parent_then = old_id_of.get(node.parent_id) if node.parent_id is not None else None
        if under_new_parent or parent_then != was.parent_id:
            moved.append(t.DiffEntry(kind=node.kind, node_id=node.node_id, statement=node.statement,
                                     before=_statement_of(old, was.parent_id),
                                     after=_statement_of(new, node.parent_id)))
    taken = set(pairs.values())
    removed = [t.DiffEntry(kind=n.kind, node_id=n.node_id, statement=n.statement)
               for j, n in enumerate(old) if j not in taken]
    return t.TreeDiff(added=tuple(added), removed=tuple(removed), moved=tuple(moved), renamed=tuple(renamed))


def with_diff(result: t.Synthesis, prior: t.PriorTree) -> t.Synthesis:
    return replace(result, diff=diff(prior, prior_of(result)))
