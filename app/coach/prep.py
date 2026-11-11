"""Prep for the next interview: what the guide should change, and why
(backlog B4, first slice).

Every proposal cites its reason, and every reason is arithmetic the project
already computes -- `standing` for the hypotheses, survey coverage for the
questions, the mirror for the interviewer's habits, `missed` for the topics
interviewees kept raising unasked (read from its caches only). No model call, and
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
from typing import Collection, Optional, Sequence

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
class RaisedTopic:
    """A topic interviewees kept raising without being asked (`missed`),
    with the arithmetic behind it. Only the topic's label: never a claim."""

    label: str
    raised: int
    """Interviews it came up in unprompted."""
    of: int
    """Interviews with extracted claims."""
    followed: int
    judged: int
    reason: str


@dataclass(frozen=True)
class Prep:
    items: "tuple[ItemProposal, ...]"
    gaps: "tuple[Gap, ...]"
    avoid: "tuple[str, ...]"
    follow: "tuple[str, ...]"
    interviews: int
    unextracted: "tuple[str, ...]"
    raised: "tuple[RaisedTopic, ...]" = ()


def item_proposals(
    survey: Sequence,
    asked_in: "dict[str, Sequence[str]]",
    guides: "dict[str, Optional[frozenset]]",
    *,
    untracked: "Collection[str]" = frozenset(),
    reconstructed: "Collection[str]" = frozenset(),
    read_by_model: "Collection[str]" = frozenset(),
) -> "tuple[ItemProposal, ...]":
    """`asked_in`: question id -> the interviews that asked it. `guides`:
    interview -> the question ids its guide held (None when the session kept
    no snapshot). A question is judged only against the interviews that HAD
    it: one added last week was not "never asked" in July. A session older
    than the snapshot (None) is assumed to have held every question -- the
    only safe reading is unknown, and the reason says how many it counted.

    `untracked`: interviews with no record of which questions were asked at
    all (imported, or recorded with the coach off). Their silence is not
    evidence, so they are left out and named, never counted as "never asked"
    (2026-11-11: 12 imported interviews made every question "move earlier").

    `reconstructed`: interviews whose `asked_in` entries were read back from
    the transcript (`prep_load`), not recorded live. One-way evidence: a
    reconstructed hit counts as asked, but reconstructed silence never makes
    "never asked". On the mock interviews the word matcher found 52 of 91
    questions really asked (s2: 2 of 10), so its counts are a floor ("at
    least") and only interviews with a live record can say "never".

    `read_by_model`: the reconstructed interviews whose questions came from
    the model's reading (`python -m app coverage`) rather than the word
    match. The same one-way rule: no recall measurement on real interviews
    justifies reading the model's silence as "never asked" yet (the mock
    interviews measure the word match, and the model only live). Only the
    label differs."""
    untracked, reconstructed = frozenset(untracked), frozenset(reconstructed)
    read_by_model = frozenset(read_by_model) & reconstructed
    proposals = []
    for item in sorted(survey, key=lambda i: i.order):
        eligible = [s for s, ids in guides.items()
                    if s not in untracked and (ids is None or item.id in ids)]
        times = len([s for s in asked_in.get(item.id, ()) if s in eligible])
        rebuilt = sum(1 for s in eligible if s in reconstructed)
        by_model = sum(1 for s in eligible if s in read_by_model)
        recorded = len(eligible) - rebuilt
        left_out = _sources(rebuilt - by_model, len(untracked), by_model)
        missed_by = ("the transcript match misses a question asked in other words" if rebuilt > by_model else
                     "the model's reading of the transcript can miss one too")
        floor = "at least " if rebuilt else ""
        if recorded >= MIN_INTERVIEWS_FOR_COVERAGE and times == 0:
            action, reason = MOVE_EARLIER, (f"never asked in the {len(eligible)} interviews that had it: "
                                            f"move it earlier, or drop it if it no longer matters{left_out}")
        elif eligible and times == 0 and rebuilt:
            action, reason = KEEP, (f"not found in the {len(eligible)} interviews that had it{left_out}: "
                                    f"{missed_by}, so check by hand before moving it")
        elif not eligible and untracked and all(s in untracked for s in guides):
            action, reason = KEEP, (f"not tracked: the {len(untracked)} interviews so far were imported or "
                                    f"recorded with the coach off, and only the live coach records which "
                                    f"questions were asked")
        elif not guides:
            action, reason = KEEP, "no interview yet"
        elif not eligible:
            action, reason = KEEP, "new since the last interview"
        else:
            action, reason = KEEP, f"asked in {floor}{times} of the {len(eligible)} interviews that had it{left_out}"
        proposals.append(ItemProposal(item.id, item.order, item.text, action, reason))
    return tuple(proposals)


def _sources(reconstructed: int, untracked: int, by_model: int = 0) -> str:
    notes = []
    if by_model:
        notes.append(f"{by_model} from the model's reading of the transcript")
    if reconstructed:
        notes.append(f"{reconstructed} reconstructed from the transcript")
    if untracked:
        notes.append(f"{untracked} untracked interviews left out")
    return f" ({'; '.join(notes)})" if notes else ""


def raised_topics(topics: Sequence, interviews: int) -> "tuple[RaisedTopic, ...]":
    """`topics`: `missed.Report.topics` (already floored at
    `missed.MIN_INTERVIEWS` unprompted interviews, most walked past first).
    A topic is proposed only when it was walked past in MORE judged
    interviews than it was followed up in: one you mostly follow up is
    already in your hands (on the mock interviews, a topic followed up in 5
    of 6 came out as "add a question" under a one-miss rule), and one nobody
    could judge says nothing about you."""
    raised = []
    for topic in topics:
        tally = topic.tally
        missed = tally.judged_interviews - tally.followed_interviews
        if missed <= tally.followed_interviews:
            continue
        label = ", ".join(topic.label) or "(no shared words)"
        unjudged = tally.raised_interviews - tally.judged_interviews
        tail = f" ({unjudged} could not be judged)" if unjudged else ""
        reason = (f"raised without being asked in {tally.raised_interviews} of {interviews} interviews, "
                  f"followed up in {tally.followed_interviews}{tail}: add a question about it, or ask for the "
                  f"last time it happened when it comes up")
        raised.append(RaisedTopic(label, tally.raised_interviews, interviews, tally.followed_interviews,
                                  tally.judged_interviews, reason))
    return tuple(raised)


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
    untracked: "Collection[str]" = frozenset(),
    reconstructed: "Collection[str]" = frozenset(),
    read_by_model: "Collection[str]" = frozenset(),
    raised_from: "Sequence" = (),
    extracted_interviews: int = 0,
) -> Prep:
    """`raised_from`: `missed.Report.topics`; `extracted_interviews`: its
    `interviews`."""
    avoid = tuple(
        f"{flag_labels.get(h.flag, h.flag)} questions: in {h.sessions} interviews so far" for h in habits
    )
    follow = tuple(
        f"you walked past {n} {signal} offer(s): when one comes, ask for the last time it happened"
        for signal, n in Counter(walked_past_signals).most_common()
    )
    return Prep(
        items=item_proposals(survey, asked_in, guides, untracked=untracked, reconstructed=reconstructed,
                             read_by_model=read_by_model),
        gaps=hypothesis_gaps(standings),
        avoid=avoid,
        follow=follow,
        interviews=len(guides),
        unextracted=tuple(unextracted),
        raised=raised_topics(raised_from, extracted_interviews),
    )
