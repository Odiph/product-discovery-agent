"""The holes in the opportunity tree, for `prep`: where the next interview
should start.

A hole is an opportunity heard in one interview at most (one story is not a
pattern yet), or a solution whose interview signal is mixed or thin. Each
carries the tree's own `next_story` question. Opportunities come first, in
tree order, then mixed solutions, then thin ones; at most `MAX_HOLES` are
shown and the rest counted.

Read from the cached tree only, through `synthesis_view.load_fresh`, so the
statuses are the ones the hub and `get_tree` show. Never a model call, and
never a stale tree: holes in a tree the claims have moved past would send the
interviewer after the wrong gap, so a stale or missing tree yields a note
saying how to rebuild it instead. Never claim text either, only node
statements, counts and the next-story question.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from app.coach import interview_summary as summary_mod
from app.coach import synthesis as syn
from app.coach import synthesis_status as status_mod
from app.coach import synthesis_store as store
from app.coach import synthesis_types as t

OPPORTUNITY = "opportunity"
SOLUTION = "solution"
MAX_HOLES = 6

REBUILD = ("Your opportunity tree is out of date, so its holes are not shown: ask your agent to rebuild it "
           "(/discovery:synthesize), or run `python -m app synthesize --yes`.")
MISSING = ("No opportunity tree yet, so prep cannot point at its holes: `python -m app synthesize` shows "
           "what it would send and the cost.")


@dataclass(frozen=True)
class TreeHole:
    node_id: str
    kind: str
    statement: str
    status: str
    """The tree's own word: "single story", "mixed" or "thin"."""
    reason: str
    ask: str
    """The node's next-story question; empty when the tree gave none."""


@dataclass(frozen=True)
class TreeHoles:
    holes: "tuple[TreeHole, ...]" = ()
    note: str = ""
    """Why there are no holes to show (no tree, a stale or unreadable one); empty otherwise."""
    more: int = 0
    """Holes past `MAX_HOLES`, counted, not shown."""


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def holes(result: t.Synthesis, refs: Sequence[Any]) -> TreeHoles:
    by_id = {item.fact_id: item for item in syn.claim_items(refs)}
    total = summary_mod.count_interviews(refs)
    statuses = status_mod.opportunity_statuses(result.opportunities, by_id)
    found = []
    for node in result.opportunities:
        heard = len(statuses[node.node_id].heard_in) if node.node_id in statuses else 0
        if heard > 1:
            continue
        reason = (f"heard in 1 of {_plural(total, 'interview')}: one story is not a pattern yet" if heard
                  else "no interview has told a story of it yet")
        found.append(TreeHole(node.node_id, OPPORTUNITY, node.statement, status_mod.SINGLE_STORY, reason,
                              node.next_story))
    solutions = [(s, status_mod.solution_status(s, by_id)) for s in result.solutions]
    for wanted in (status_mod.MIXED, status_mod.THIN):
        for solution, status in solutions:
            if status.signal != wanted:
                continue
            if wanted == status_mod.MIXED:
                reason = f"interview signal mixed: {len(status.for_in)} for, {len(status.against_in)} against"
            else:
                verb = "bears" if status.touching == 1 else "bear"
                reason = (f"interview signal thin: {_plural(status.touching, 'interview')} {verb} on it, "
                          f"{status_mod.SIGNAL_AT} needed")
            found.append(TreeHole(solution.node_id, SOLUTION, solution.statement, wanted, reason,
                                  solution.next_story))
    return TreeHoles(tuple(found[:MAX_HOLES]), "", max(0, len(found) - MAX_HOLES))


def load(context_dir: Path, refs: Sequence[Any], hypotheses: Sequence[Any]) -> TreeHoles:
    """The holes for these claims and hypotheses, or a note saying why there are none to show."""
    if not syn.claim_items(refs):
        return TreeHoles()
    from app.coach import synthesis_view  # lazy: it pulls in the model resolver

    state = synthesis_view.load_fresh(Path(context_dir), refs, hypotheses)
    if state.status == store.FRESH and state.synthesis is not None:
        return holes(state.synthesis, refs)
    if state.status == store.STALE:
        return TreeHoles(note=REBUILD)
    if state.status == store.ABSENT:
        return TreeHoles(note=MISSING)
    return TreeHoles(note=f"The opportunity tree could not be read ({state.reason}): "
                          "`python -m app synthesize --yes` rebuilds it.")
