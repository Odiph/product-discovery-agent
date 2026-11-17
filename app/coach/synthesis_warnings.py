"""The tree's SOFT rules: cheap, noisy heuristics that flag a node and never
drop it (the research's section 8, rules 5 to 12). Computed on every view,
never stored, so a new rule applies to a cached tree too.

On an opportunity: not in the customer's first-person voice; a solution
word (a solution in disguise?); a metric or business word (a business goal
in disguise?); a parent with a single child opportunity (fill in siblings).
On siblings of either kind: statements or cited claims that overlap. On any
node: a next story that is not about past behaviour. On the tree: more than
seven top-level opportunities.

"At least three solutions" (what else could we do?) is Torres's rule for the
TARGET opportunity, the one a person chooses to work on next, never for every
node. No surface marks a target yet, so the tree carries one note saying to
pick one; `target_id` is the hook a target-picking surface passes, and then
only that node is held to three.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from app.coach import synthesis_types as t
from app.coach.synthesis_status import children_of

NOT_FIRST_PERSON = "not-first-person"
SOLUTION_WORDS = "solution-words"
BUSINESS_WORDS = "business-words"
SIBLINGS_OVERLAP = "siblings-overlap"
SINGLE_CHILD = "single-child"
TOO_MANY_TOP = "too-many-top-level"
FEW_SOLUTIONS = "fewer-than-three-solutions"
STORY_NOT_PAST = "story-not-past-behaviour"
NO_TARGET = "no-target-opportunity"
NO_TARGET_MESSAGE = "No target opportunity chosen yet. Pick one, then generate at least 3 solutions for it."

MAX_TOP_LEVEL = 7
MIN_SOLUTIONS = 3
OVERLAP_AT = 0.6

_FIRST_PERSON = re.compile(r"\b(i|i'm|im|i've|i'd|i'll|me|my|mine|myself|we|we're|our|us)\b", re.IGNORECASE)
# Deliverable nouns anywhere, and an imperative verb at the start ("Add...", "Build..."):
# "build" alone is a noun to a developer ("my build finished"), so only the leading verb counts.
_SOLUTION = re.compile(r"(^\s*(add|build|create|make|let|allow|give|show|integrate)\b|\b(dashboard|app|button|"
                       r"integration|feature|features|automatically|automate|tool|report|plugin|widget|setting|"
                       r"mode|option)\b)", re.IGNORECASE)
_BUSINESS = re.compile(r"(%|\b(increase|reduce|churn|conversion|conversions|revenue|retention|engagement|kpi|"
                       r"metric|metrics|roi|arpu|dau|mau|monetize|upsell)\b)", re.IGNORECASE)
_PAST_STEMS = ("tell me about the last time", "tell me about a time", "walk me through", "the last time you",
               "when was the last time", "think back to", "describe the last time", "tell me about when")
_FUTURE = re.compile(r"\b(would you|will you|could you see|do you think|imagine)\b", re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_STOP = frozenset({"the", "and", "for", "that", "with", "when", "can't", "cannot", "what", "have", "from", "this",
                   "they", "their", "want", "need", "into", "about", "while"})


@dataclass(frozen=True)
class NodeWarning:
    node_id: str
    """Empty for a warning about the whole tree."""
    rule: str
    message: str


def is_past_behaviour(story: str) -> bool:
    lowered = " ".join(story.lower().split())
    return any(lowered.startswith(stem) or f" {stem}" in lowered[:60] for stem in _PAST_STEMS) \
        and not _FUTURE.search(lowered)


def words(text: str) -> "frozenset[str]":
    return frozenset(w for w in _WORD.findall(text.lower()) if w not in _STOP)


def jaccard(a: "frozenset | set", b: "frozenset | set") -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _phrasing(node: t.Opportunity) -> "list[NodeWarning]":
    found = []
    if not _FIRST_PERSON.search(node.statement):
        found.append(NodeWarning(node.node_id, NOT_FIRST_PERSON, "not in the customer's first-person voice"))
    if _SOLUTION.search(node.statement):
        found.append(NodeWarning(node.node_id, SOLUTION_WORDS,
                             "names a solution: is there more than one way to address it?"))
    if _BUSINESS.search(node.statement):
        found.append(NodeWarning(node.node_id, BUSINESS_WORDS, "reads as a business goal, not a customer need"))
    return found


def _story(node) -> "list[NodeWarning]":
    if is_past_behaviour(node.next_story):
        return []
    if not node.next_story.strip():
        return [NodeWarning(node.node_id, STORY_NOT_PAST, "no next story to ask for")]
    return [NodeWarning(node.node_id, STORY_NOT_PAST,
                    "the next story is not about past behaviour (ask \"Tell me about the last time...\")")]


def _overlaps(siblings: Sequence) -> "list[NodeWarning]":
    found = []
    for index, first in enumerate(siblings):
        for second in siblings[index + 1:]:
            wording = jaccard(words(first.statement), words(second.statement))
            claims = jaccard({e.fact_id for e in first.evidence}, {e.fact_id for e in second.evidence})
            if max(wording, claims) >= OVERLAP_AT:
                message = f"overlaps its sibling {second.node_id}: are they distinct?"
                found.append(NodeWarning(first.node_id, SIBLINGS_OVERLAP, message))
    return found


def _target(target_id: Optional[str], opportunities: Sequence[t.Opportunity],
            by_opportunity: "dict[str, list[t.Solution]]") -> "list[NodeWarning]":
    if not opportunities:
        return []
    if not target_id:
        return [NodeWarning("", NO_TARGET, NO_TARGET_MESSAGE)]
    under = len(by_opportunity.get(target_id, ()))
    if under >= MIN_SOLUTIONS or target_id not in {node.node_id for node in opportunities}:
        return []
    return [NodeWarning(target_id, FEW_SOLUTIONS, f"the target has {under} solution(s): generate at least "
                                                  f"{MIN_SOLUTIONS}; what else could we do?")]


def warnings(synthesis: t.Synthesis, *, target_id: Optional[str] = None) -> "tuple[NodeWarning, ...]":
    """`target_id`: the opportunity a person chose to work on, when one is chosen."""
    opportunities, solutions = synthesis.opportunities, synthesis.solutions
    children = children_of(opportunities)
    by_opportunity: "dict[str, list[t.Solution]]" = {}
    for solution in solutions:
        by_opportunity.setdefault(solution.opportunity_id, []).append(solution)
    found: "list[NodeWarning]" = []
    top = children.get(None, [])
    if len(top) > MAX_TOP_LEVEL:
        found.append(NodeWarning("", TOO_MANY_TOP, f"{len(top)} top-level opportunities: more than {MAX_TOP_LEVEL} "
                                               "is hard to compare; group them under broader needs"))
    for node in opportunities:
        found += _phrasing(node) + _story(node)
        if len(children.get(node.node_id, ())) == 1:
            found.append(NodeWarning(node.node_id, SINGLE_CHILD, "one child opportunity only: fill in its siblings"))
    found += _target(target_id, opportunities, by_opportunity)
    for solution in solutions:
        found += _story(solution)
    groups: "list[Sequence]" = [list(group) for group in children.values()] + list(by_opportunity.values())
    for group in groups:
        found += _overlaps(group)
    return tuple(found)


def for_node(found: "Sequence[NodeWarning]", node_id: Optional[str]) -> "list[NodeWarning]":
    return [w for w in found if w.node_id == (node_id or "")]
