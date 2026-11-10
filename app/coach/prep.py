"""Prep for the next interview: what the guide should change, and why
(backlog B4, first slice).

Every proposal cites its reason, and every reason is arithmetic the project
already computes -- `standing` for the hypotheses, survey coverage for the
questions, the mirror for the interviewer's habits. No model call, and
nothing is written: the operator owns the guide, and `author` is still the
only thing that changes it.

What this slice does NOT do: word new questions (that needs the model) or
judge a question "saturated" (nothing measures whether a question still
teaches anything; a question asked in every interview may be the one that
matters most). Both are stated to the reader rather than guessed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional, Sequence

KEEP = "keep"
MOVE_EARLIER = "move-earlier"

UNTESTED = "untested"
NO_CRITERION = "no-criterion"
ONLY_UNCLEAR = "only-unclear"
CONTESTED = "contested"
THIN = "thin"

MIN_INTERVIEWS_FOR_COVERAGE = 2
THIN_INTERVIEWS = 3


@dataclass(frozen=True)
class ItemProposal:
    item_id: str
    order: int
    text: str
    action: str
    reason: str


@dataclass(frozen=True)
class Gap:
    hypothesis_id: str
    statement: str
    kind: str
    reason: str


@dataclass(frozen=True)
class Prep:
    items: "tuple[ItemProposal, ...]"
    gaps: "tuple[Gap, ...]"
    avoid: "tuple[str, ...]"
    follow: "tuple[str, ...]"
    interviews: int
    unextracted: "tuple[str, ...]"


def item_proposals(
    survey: Sequence,
    asked_in: "dict[str, Sequence[str]]",
    guides: "dict[str, Optional[frozenset]]",
) -> "tuple[ItemProposal, ...]":
    """`asked_in`: question id -> the interviews that asked it. `guides`:
    interview -> the question ids its guide held (None when the session kept
    no snapshot). A question is judged only against the interviews that HAD
    it: one added last week was not "never asked" in July. A session older
    than the snapshot (None) is assumed to have held every question -- the
    only safe reading is unknown, and the reason says how many it counted."""
    proposals = []
    for item in sorted(survey, key=lambda i: i.order):
        eligible = [s for s, ids in guides.items() if ids is None or item.id in ids]
        times = len([s for s in asked_in.get(item.id, ()) if s in eligible])
        if len(eligible) >= MIN_INTERVIEWS_FOR_COVERAGE and times == 0:
            action, reason = MOVE_EARLIER, (f"never asked in the {len(eligible)} interviews that had it: "
                                            f"move it earlier, or drop it if it no longer matters")
        elif not guides:
            action, reason = KEEP, "no interview yet"
        elif not eligible:
            action, reason = KEEP, "new since the last interview"
        else:
            action, reason = KEEP, f"asked in {times} of the {len(eligible)} interviews that had it"
        proposals.append(ItemProposal(item.id, item.order, item.text, action, reason))
    return tuple(proposals)


def hypothesis_gaps(standings: Sequence) -> "tuple[Gap, ...]":
    """One gap per hypothesis at most, the most urgent first: a hypothesis
    with no decision rule cannot be judged by any amount of evidence, so that
    comes before everything else."""
    gaps = []
    for s in standings:
        gap = _gap(s)
        if gap is not None:
            gaps.append(gap)
    rank = {NO_CRITERION: 0, UNTESTED: 1, CONTESTED: 2, ONLY_UNCLEAR: 3, THIN: 4}
    return tuple(sorted(gaps, key=lambda g: (rank[g.kind], g.hypothesis_id)))


def _gap(s) -> Optional[Gap]:
    if not s.is_scorable:
        return Gap(s.hypothesis_id, s.statement, NO_CRITERION,
                   "no decision criterion: write one in `author` BEFORE the next interview, or no answer can settle it")
    if s.total_interviews == 0:
        target = f" -- aim a question at its falsifier: \"{s.falsifier}\"" if s.falsifier else ""
        return Gap(s.hypothesis_id, s.statement, UNTESTED, f"no interview has borne on it yet{target}")
    if s.supporting_interviews and s.contrary_interviews:
        return Gap(s.hypothesis_id, s.statement, CONTESTED,
                   f"{s.supporting_interviews} interview(s) for, {s.contrary_interviews} against: "
                   f"find what differs between those people")
    if not s.supporting_interviews and not s.contrary_interviews:
        return Gap(s.hypothesis_id, s.statement, ONLY_UNCLEAR,
                   f"only unclear evidence from {s.unclear_interviews} interview(s): ask for a specific recent occasion")
    if s.total_interviews < THIN_INTERVIEWS:
        return Gap(s.hypothesis_id, s.statement, THIN,
                   f"borne on by {s.total_interviews} interview(s) only")
    return None


def build(
    *,
    survey: Sequence,
    asked_in: "dict[str, Sequence[str]]",
    guides: "dict[str, Optional[frozenset]]",
    standings: Sequence,
    habits: Sequence,
    walked_past_signals: "Sequence[str]",
    unextracted: "Sequence[str]",
    flag_labels: "dict[str, str]",
) -> Prep:
    avoid = tuple(
        f"{flag_labels.get(h.flag, h.flag)} questions: in {h.sessions} interviews so far" for h in habits
    )
    follow = tuple(
        f"you walked past {n} {signal} offer(s): when one comes, ask for the last time it happened"
        for signal, n in Counter(walked_past_signals).most_common()
    )
    return Prep(
        items=item_proposals(survey, asked_in, guides),
        gaps=hypothesis_gaps(standings),
        avoid=avoid,
        follow=follow,
        interviews=len(guides),
        unextracted=tuple(unextracted),
    )
