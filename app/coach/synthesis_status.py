"""What each node's evidence adds up to, computed in code from the cited
claims, in DISTINCT INTERVIEWS: never a claim count, never the model's.

The words are Teresa Torres's (Continuous Discovery Habits, and her opportunity solution tree writing):

- an OPPORTUNITY is heard: in 1 interview a "single story", in 2
  "recurring", in 3 or more "established"; "well met for some" when a claim
  says something they use already meets the need. A parent counts its own
  interviews and its descendants'. Absence never refutes a need: a "not
  experienced" claim is shown as a count and changes no status.
- a SOLUTION has an interview signal, not a test result: "thin" when fewer
  than 3 interviews touch it, "leaning for" when 3 or more support it and at
  least twice as many as contradict it, "leaning against" the mirror,
  "mixed" otherwise.
- an ASSUMPTION is the only thing ever "tested", and every one starts
  "untested": interview claims are evidence about it, never a test.

The thresholds are this tool's heuristic, not Torres's; every surface shows
the raw counts beside the word.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from app.coach import synthesis_types as t

SINGLE_STORY = "single story"
RECURRING = "recurring"
ESTABLISHED = "established"
WELL_MET = "well met for some"
ESTABLISHED_AT = 3

LEANING_FOR = "leaning for"
LEANING_AGAINST = "leaning against"
MIXED = "mixed"
THIN = "thin"
SIGNAL_AT = 3
"""Interviews touching a solution below which its signal is thin."""
LEAN_RATIO = 2

UNTESTED = "untested"
LEAP_OF_FAITH = "leap of faith"


@dataclass(frozen=True)
class OpportunityStatus:
    heard_in: "tuple[str, ...]"
    """Interviews with `experiences` evidence, its descendants' included."""
    met_in: "tuple[str, ...]"
    not_experienced_in: "tuple[str, ...]"
    status: str

    @property
    def well_met(self) -> bool:
        return bool(self.met_in)


@dataclass(frozen=True)
class SolutionStatus:
    for_in: "tuple[str, ...]"
    against_in: "tuple[str, ...]"
    signal: str

    @property
    def touching(self) -> int:
        return len(set(self.for_in) | set(self.against_in))


def heard_status(interviews: int) -> str:
    if interviews >= ESTABLISHED_AT:
        return ESTABLISHED
    return RECURRING if interviews == 2 else SINGLE_STORY


def signal(for_count: int, against_count: int, touching: int) -> str:
    if touching < SIGNAL_AT:
        return THIN
    if for_count >= SIGNAL_AT and for_count >= LEAN_RATIO * against_count:
        return LEANING_FOR
    if against_count >= SIGNAL_AT and against_count >= LEAN_RATIO * for_count:
        return LEANING_AGAINST
    return MIXED


def _sessions(evidence: "Sequence[t.Evidence]", bearing: str, by_id: "Mapping[str, t.ClaimItem]") -> "set[str]":
    return {by_id[e.fact_id].session_id for e in evidence if e.bearing == bearing and e.fact_id in by_id}


def children_of(opportunities: "Sequence[t.Opportunity]") -> "dict[Optional[str], list[t.Opportunity]]":
    found: "dict[Optional[str], list[t.Opportunity]]" = {}
    for node in opportunities:
        found.setdefault(node.parent_id, []).append(node)
    return found


def opportunity_statuses(opportunities: "Sequence[t.Opportunity]",
                         by_id: "Mapping[str, t.ClaimItem]") -> "dict[str, OpportunityStatus]":
    children = children_of(opportunities)
    result: "dict[str, OpportunityStatus]" = {}

    def visit(node: t.Opportunity) -> "set[str]":
        heard = _sessions(node.evidence, t.EXPERIENCES, by_id)
        for child in children.get(node.node_id, ()):
            heard |= visit(child)
        result[node.node_id] = OpportunityStatus(
            heard_in=tuple(sorted(heard)), met_in=tuple(sorted(_sessions(node.evidence, t.ALREADY_MET, by_id))),
            not_experienced_in=tuple(sorted(_sessions(node.evidence, t.NOT_EXPERIENCED, by_id))),
            status=heard_status(len(heard)))
        return heard

    for root in children.get(None, ()):
        visit(root)
    return result


def solution_status(solution: t.Solution, by_id: "Mapping[str, t.ClaimItem]") -> SolutionStatus:
    for_in, against_in = _sessions(solution.evidence, t.SUPPORTS, by_id), _sessions(solution.evidence,
                                                                                    t.CONTRADICTS, by_id)
    return SolutionStatus(for_in=tuple(sorted(for_in)), against_in=tuple(sorted(against_in)),
                          signal=signal(len(for_in), len(against_in), len(for_in | against_in)))


def assumption_interviews(assumption: t.Assumption, by_id: "Mapping[str, t.ClaimItem]") -> "tuple[str, ...]":
    return tuple(sorted({by_id[f].session_id for f in assumption.fact_ids if f in by_id}))


def is_leap_of_faith(assumption: t.Assumption, by_id: "Mapping[str, t.ClaimItem]") -> bool:
    """High importance and no interview evidence: what to test first."""
    return assumption.importance == t.IMPORTANCE_HIGH and not assumption_interviews(assumption, by_id)
