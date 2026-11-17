"""The shapes `synthesize` sends and keeps: its inputs (claims, hypotheses,
the outcome, the previous tree) and its answer, the opportunity solution tree
(outcome > opportunities, nestable > solutions > assumptions).

Data only. The rules live in `synthesis_validate.py` (what is dropped),
`synthesis_status.py` (what each node's evidence adds up to) and
`synthesis_warnings.py` (what is flagged but kept). No count lives here: every
interview count is computed from the cited claims when the tree is shown.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# How a claim bears on an OPPORTUNITY. "Not experienced" only shrinks its
# share and "already met" marks a need some customers have solved: neither
# ever refutes a need someone described (Torres: absence is sizing).
EXPERIENCES = "experiences"
NOT_EXPERIENCED = "not_experienced"
ALREADY_MET = "already_met"
OPPORTUNITY_BEARINGS = (EXPERIENCES, NOT_EXPERIENCED, ALREADY_MET)

# How a claim bears on a SOLUTION: an interview signal, never a test result.
SUPPORTS = "supports"
CONTRADICTS = "contradicts"
SOLUTION_BEARINGS = (SUPPORTS, CONTRADICTS)

ORIGINS = ("customer", "operator", "model")
"""Who proposed a solution: a claim, a hypothesis, or the model itself."""
ORIGIN_UNKNOWN = "unknown"
ASSUMPTION_TYPES = ("desirability", "usability", "feasibility", "viability", "ethical")
TYPE_UNKNOWN = "unknown"
IMPORTANCE_HIGH = "high"
IMPORTANCE_LOW = "low"
IMPORTANCES = (IMPORTANCE_HIGH, IMPORTANCE_LOW)

KIND_OPPORTUNITY = "opportunity"
KIND_SOLUTION = "solution"

# The rules that DROP part of the model's answer (`synthesis_validate.py`).
# Each drop is recorded as (rule, what was dropped) and reported.
DROP_UNKNOWN_CLAIM = "unknown-claim-id"
DROP_BAD_BEARING = "bearing-not-allowed"
DROP_UNKNOWN_HYPOTHESIS = "unknown-hypothesis-id"
DROP_HYPOTHESIS_KIND = "hypothesis-kind-mismatch"
DROP_HYPOTHESIS_TWICE = "hypothesis-mapped-twice"
DROP_DUPLICATE_ID = "duplicate-node-id"
DROP_MULTI_PARENT = "more-than-one-parent"
DROP_CYCLE = "parent-cycle"
DROP_UNKNOWN_PARENT = "unknown-parent"
DROP_ORPHAN_SOLUTION = "solution-without-opportunity"
DROP_NO_EVIDENCE = "no-interview-evidence"
DROP_UNSTATED = "no-statement"
DROP_RULES = (DROP_UNKNOWN_CLAIM, DROP_BAD_BEARING, DROP_UNKNOWN_HYPOTHESIS, DROP_HYPOTHESIS_KIND,
              DROP_HYPOTHESIS_TWICE, DROP_DUPLICATE_ID, DROP_MULTI_PARENT, DROP_CYCLE, DROP_UNKNOWN_PARENT,
              DROP_ORPHAN_SOLUTION, DROP_NO_EVIDENCE, DROP_UNSTATED)
DROP_WORDS = {
    DROP_UNKNOWN_CLAIM: "cited claim id(s) that do not exist",
    DROP_BAD_BEARING: "citation(s) with a bearing that does not fit the node",
    DROP_UNKNOWN_HYPOTHESIS: "mapping(s) to an unknown hypothesis",
    DROP_HYPOTHESIS_KIND: "mapping(s) to a hypothesis of the other kind",
    DROP_HYPOTHESIS_TWICE: "mapping(s) to a hypothesis another node already maps",
    DROP_DUPLICATE_ID: "node(s) listed twice",
    DROP_MULTI_PARENT: "opportunit(ies) with more than one parent",
    DROP_CYCLE: "opportunit(ies) on a cycle of parents",
    DROP_UNKNOWN_PARENT: "unknown parent(s), lifted to the top level",
    DROP_ORPHAN_SOLUTION: "solution(s) with no valid opportunity",
    DROP_NO_EVIDENCE: "node(s) with evidence from no interview",
    DROP_UNSTATED: "node(s) with no id or statement",
}
"""How each drop rule reads to a person: the terminal and the hub say the same words."""


@dataclass(frozen=True)
class ClaimItem:
    """What one claim contributes to the request and to the cache key."""

    fact_id: str
    session_id: str
    claim: str
    bearings: "tuple[tuple[str, str], ...]"


@dataclass(frozen=True)
class HypothesisLine:
    """An operator hypothesis as a LABEL to reconcile against, never the
    skeleton: id, statement, and the operator's own kind and parent."""

    hypothesis_id: str
    statement: str
    kind: str = ""
    parent: str = ""


@dataclass(frozen=True)
class OutcomeInput:
    """The operator's outcome (`context/outcome.json`), or none: then the
    model proposes one and the tree says so."""

    text: str = ""

    @property
    def given(self) -> bool:
        return bool(self.text.strip())


@dataclass(frozen=True)
class Evidence:
    fact_id: str
    bearing: str


@dataclass(frozen=True)
class Assumption:
    text: str
    type: str
    importance: str
    fact_ids: "tuple[str, ...]" = ()
    """Claims that bear on it. Evidence, never a test: every assumption is untested."""


@dataclass(frozen=True)
class Opportunity:
    node_id: str
    statement: str
    parent_id: Optional[str]
    evidence: "tuple[Evidence, ...]"
    hypothesis_id: str = ""
    reframed_from: str = ""
    next_story: str = ""


@dataclass(frozen=True)
class Solution:
    node_id: str
    opportunity_id: str
    statement: str
    origin: str
    evidence: "tuple[Evidence, ...]"
    hypothesis_id: str = ""
    assumptions: "tuple[Assumption, ...]" = ()
    next_story: str = ""


@dataclass(frozen=True)
class OutcomeNode:
    text: str
    proposed: bool
    """True when no outcome was given and this is the model's proposal."""


@dataclass(frozen=True)
class Drop:
    rule: str
    what: str


@dataclass(frozen=True)
class DiffEntry:
    kind: str
    node_id: str
    statement: str
    before: str = ""
    """For a rename, the old statement; for a move, the old parent's statement."""
    after: str = ""
    """For a move, the new parent's statement."""


@dataclass(frozen=True)
class TreeDiff:
    added: "tuple[DiffEntry, ...]" = ()
    removed: "tuple[DiffEntry, ...]" = ()
    moved: "tuple[DiffEntry, ...]" = ()
    renamed: "tuple[DiffEntry, ...]" = ()

    @property
    def any(self) -> bool:
        return bool(self.added or self.removed or self.moved or self.renamed)


@dataclass(frozen=True)
class Synthesis:
    model: str
    key: str
    outcome: OutcomeNode
    opportunities: "tuple[Opportunity, ...]"
    solutions: "tuple[Solution, ...]"
    opinion_fact_ids: "tuple[str, ...]" = ()
    """Praise and opinions: heard, not evidence. Never a node."""
    drops: "tuple[Drop, ...]" = ()
    diff: Optional[TreeDiff] = None
    """Against the previous tree, when there was one."""


@dataclass(frozen=True)
class PriorNode:
    kind: str
    """`KIND_OPPORTUNITY` or `KIND_SOLUTION`."""
    node_id: str
    statement: str
    parent_id: Optional[str]
    """An opportunity's parent (None at the top), or a solution's opportunity."""
    hypothesis_id: str = ""


@dataclass(frozen=True)
class PriorTree:
    """The previous tree as sent back for stability: labels and structure
    only, no claim text, no counts."""

    outcome: str
    nodes: "tuple[PriorNode, ...]"
