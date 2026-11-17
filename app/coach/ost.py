"""The Opportunity Solution Tree (Teresa Torres): a VIEW over evidence this
product already holds, never a second store of it.

Outcome at the root, opportunities under it, solutions under opportunities,
and every node carrying its per-interview evidence. The parts and where each
one lives:

- **The outcome** is the one new artifact, `context/outcome.json`. Not a
  brief item: the brief is grounding for the LIVE coach's prompt, and an
  outcome slipped into it would change what the coach says mid-call -- a
  behaviour change nobody asked for, arriving through a planning field. Not a
  hypothesis either: an outcome is a target, it has no falsifier, and
  `Hypothesis` rightly refuses to exist without one. Written only by the
  author page (`app/web/author.py`), read tolerantly here.
- **The structure** is `Hypothesis.kind` and `Hypothesis.parent`, in the
  hypotheses file that already exists. So the tree changes only when the
  operator saves the hypotheses -- the same explicit human accept every other
  change to them takes -- and gate 19's pinned writer set is untouched.
- **The counts** come from `interview_summary.standing`, the one home of the
  per-INTERVIEW rule. This module counts nothing; it re-reads the corpus on
  every call, which is the whole of "the tree updates after every extract".
- **The candidates** are `themes.unbound_themes`: recurring claims no
  hypothesis predicted. Listed beside the tree, never in it -- a theme becomes
  an opportunity only when a human writes one.

Quote-free by construction: it is handed `FactRef`s, which have no
`quoted_text` field, and holds only labels, statements and counts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from app.coach import interview_summary as summary_mod
from app.coach import themes as themes_mod
from app.coach.corpus import (
    HYPOTHESIS_KIND_OPPORTUNITY, HYPOTHESIS_KIND_SOLUTION, tree_problems,
)

OUTCOME_FILENAME = "outcome.json"
OUTCOME_KEY = "outcome"
# One sentence of intent, not a document. Long enough for "Cut first-month
# churn from 12% to under 5% by Q3" in either language with room to spare.
MAX_OUTCOME_CHARS = 500

OUTCOME_MISSING = "missing"
OUTCOME_PRESENT = "present"
OUTCOME_UNREADABLE = "unreadable"

STATUS_NO_HYPOTHESES = "no-hypotheses"
STATUS_NOT_EXTRACTED = "not-extracted"
STATUS_TREE = "tree"
# Pinned by equality: a fifth state is a decision, not drift.
ALL_TREE_STATUSES = frozenset({STATUS_NO_HYPOTHESES, STATUS_NOT_EXTRACTED, STATUS_TREE})


@dataclass(frozen=True)
class Outcome:
    state: str
    text: str = ""

    @property
    def is_set(self) -> bool:
        """A saved blank is the operator clearing it: not set, and said so."""
        return self.state == OUTCOME_PRESENT and bool(self.text.strip())


def read_outcome(context_dir: "Path | str") -> Outcome:
    """Tolerant, never raising: a reader of a planning field must not take a
    command down. UNREADABLE is kept apart from MISSING because the remedy
    differs -- one is "write one", the other is "repair the file first"."""
    path = Path(context_dir) / OUTCOME_FILENAME
    if not path.is_file():
        return Outcome(OUTCOME_MISSING)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return Outcome(OUTCOME_UNREADABLE)
    if not isinstance(raw, dict) or not isinstance(raw.get(OUTCOME_KEY), str):
        return Outcome(OUTCOME_UNREADABLE)
    return Outcome(OUTCOME_PRESENT, raw[OUTCOME_KEY])


def validate_outcome_payload(body: Any) -> "tuple[Optional[dict], Optional[str]]":
    """Strict on save: exactly `{"outcome": <string>}`, trimmed, bounded. An
    empty string is allowed and means "cleared"."""
    if not isinstance(body, dict) or set(body) != {OUTCOME_KEY}:
        return None, f"outcome must be a JSON object with exactly one key, {OUTCOME_KEY!r}"
    text = body[OUTCOME_KEY]
    if not isinstance(text, str):
        return None, "outcome must be a string"
    text = text.strip()
    if len(text) > MAX_OUTCOME_CHARS:
        return None, f"outcome is {len(text)} characters; keep it to one sentence (at most {MAX_OUTCOME_CHARS})"
    return {OUTCOME_KEY: text}, None


@dataclass(frozen=True)
class TreeNode:
    hypothesis_id: str
    kind: Optional[str]
    statement: str
    state: str
    is_scorable: bool
    supporting_interviews: int
    contrary_interviews: int
    unclear_interviews: int
    total_interviews: int
    children: "tuple[TreeNode, ...]" = ()


@dataclass(frozen=True)
class Candidate:
    """A recurring theme no hypothesis predicted. `interviews` is how many
    distinct interviews it recurs in, as `themes` itself reports it."""

    label: "tuple[str, ...]"
    interviews: int
    claims: "tuple[str, ...]"


@dataclass(frozen=True)
class Tree:
    status: str
    outcome: Outcome
    opportunities: "tuple[TreeNode, ...]"
    unclassified: "tuple[TreeNode, ...]"
    candidates: "tuple[Candidate, ...]"
    problems: "tuple[str, ...]"
    extracted_interviews: int
    corpus_exists: bool


def _node(hypothesis: Any, refs: Sequence, project: str, children=()) -> TreeNode:
    standing = summary_mod.standing(hypothesis, refs, project=project)
    return TreeNode(
        hypothesis_id=standing.hypothesis_id,
        kind=hypothesis.kind,
        statement=standing.statement,
        state=standing.state,
        is_scorable=standing.is_scorable,
        supporting_interviews=standing.supporting_interviews,
        contrary_interviews=standing.contrary_interviews,
        unclear_interviews=standing.unclear_interviews,
        total_interviews=standing.total_interviews,
        children=tuple(children),
    )


def build_tree(
    hypotheses: Sequence, refs: Sequence, *, outcome: Outcome, corpus_exists: bool, project: str = ""
) -> Tree:
    """The tree for one node. `refs` are `FactRef`s; `hypotheses` are loaded
    `Hypothesis` records in file order, which is the order shown.

    A solution whose parent is missing or is not an opportunity is shown
    UNCLASSIFIED, with the fault in `problems` -- never dropped, and never
    hung under a node it does not belong to."""
    refs = tuple(refs)
    opportunity_ids = {h.id for h in hypotheses if h.kind == HYPOTHESIS_KIND_OPPORTUNITY}
    solutions_by_parent: "dict[str, list]" = {}
    for h in hypotheses:
        if h.kind == HYPOTHESIS_KIND_SOLUTION and h.parent in opportunity_ids:
            solutions_by_parent.setdefault(h.parent, []).append(h)
    placed = {s.id for group in solutions_by_parent.values() for s in group}

    opportunities = tuple(
        _node(h, refs, project, [_node(s, refs, project) for s in solutions_by_parent.get(h.id, ())])
        for h in hypotheses
        if h.kind == HYPOTHESIS_KIND_OPPORTUNITY
    )
    unclassified = tuple(
        _node(h, refs, project)
        for h in hypotheses
        if h.kind != HYPOTHESIS_KIND_OPPORTUNITY and h.id not in placed
    )
    candidates = tuple(
        Candidate(label=theme.label, interviews=len(theme.sessions), claims=theme.claims)
        for theme in themes_mod.unbound_themes(refs)
    )
    if not hypotheses:
        status = STATUS_NO_HYPOTHESES
    elif not corpus_exists:
        status = STATUS_NOT_EXTRACTED
    else:
        status = STATUS_TREE
    return Tree(
        status=status,
        outcome=outcome,
        opportunities=opportunities,
        unclassified=unclassified,
        candidates=candidates,
        problems=tree_problems(hypotheses),
        extracted_interviews=summary_mod.count_interviews(refs),
        corpus_exists=corpus_exists,
    )
