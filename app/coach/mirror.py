"""The mirror: what the INTERVIEWER keeps doing, across every interview in a
project (backlog B2).

Two sources, both per session, neither calling a model here:
- the question critique (`critique-questions`, `questions_critique.json`):
  how each of your questions was banded and flagged;
- the walked-past detector (`walked_past.py`): offers you did not follow.

A HABIT is a flag that shows up in two or more interviews -- one leading
question is a slip, the same flag in interview after interview is a pattern.
The TREND compares the earlier half of the critiqued interviews with the
later half, in rates, so a long interview does not outweigh a short one.

Pure: the caller loads each session; this module only aggregates. Rows carry
counts, flags and sequence numbers, never words.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from app.coach.walked_past import Moment

# The critique summary's flag counters, in the order a report lists them.
FLAG_KEYS = (
    "leading", "hypothetical_or_future_tense", "pitch", "opinion_seeking", "confirmation_only",
    "off_topic",
)
MIN_SESSIONS_FOR_HABIT = 2
MIN_SESSIONS_FOR_TREND = 2


@dataclass(frozen=True)
class SessionMirror:
    session_id: str
    date: Optional[str]
    judged: Optional[int]
    """Questions the critique banded; None when the session was never critiqued."""
    clean: Optional[int]
    flags: "Mapping[str, int]"
    offers: int
    walked_past: "tuple[Moment, ...]"
    uncertain: Optional[int] = None
    """Questions banded uncertain -- mostly follow-ups the critic could not
    place without what the interviewee had just said. None when unknown."""

    @property
    def critiqued(self) -> bool:
        return self.judged is not None

    @property
    def clean_rate(self) -> Optional[float]:
        """Clean out of the questions the critic could DECIDE. An uncertain
        question is not an unclean one: counting it as such scored good
        follow-ups as failures. None when nothing was decided."""
        if not self.judged:
            return None
        decided = self.judged - (self.uncertain or 0)
        if decided <= 0:
            return None
        return (self.clean or 0) / decided


@dataclass(frozen=True)
class Habit:
    flag: str
    sessions: int
    total: int


@dataclass(frozen=True)
class Trend:
    earlier_sessions: int
    later_sessions: int
    earlier_clean_rate: float
    later_clean_rate: float
    earlier_flag_rates: "Mapping[str, float]"
    later_flag_rates: "Mapping[str, float]"


@dataclass(frozen=True)
class Mirror:
    sessions: "tuple[SessionMirror, ...]"
    habits: "tuple[Habit, ...]"
    trend: Optional[Trend]
    unreadable: "tuple[str, ...]" = ()

    @property
    def uncritiqued(self) -> "tuple[str, ...]":
        return tuple(s.session_id for s in self.sessions if not s.critiqued)

    @property
    def walked_past_total(self) -> int:
        return sum(len(s.walked_past) for s in self.sessions)

    @property
    def offers_total(self) -> int:
        return sum(s.offers for s in self.sessions)


def session_mirror(
    session_id: str,
    *,
    date: Optional[str],
    critique: "Optional[Mapping[str, Any]]",
    offers: int,
    walked_past: "Sequence[Moment]",
) -> SessionMirror:
    """`critique` is the parsed critique artifact, or None. Only its summary
    numbers are read: the per-turn text it also holds stays where it is."""
    summary = (critique or {}).get("summary") if critique else None
    judged = _count(summary.get("judged")) if isinstance(summary, Mapping) else None
    clean = _count(summary.get("clean")) if judged is not None else None
    if judged is None or clean is None or clean > judged:
        # A hand-edited or drifted artifact (a 250% clean rate, a negative
        # count, `true` for a number) is treated as no critique at all.
        judged, clean, flags = None, None, {}
    else:
        flags = {key: n for key in FLAG_KEYS if (n := _count(summary.get(key))) is not None and n <= judged}
    uncertain = _uncertain(summary, critique, judged, clean) if judged is not None else None
    return SessionMirror(
        session_id=session_id, date=date, judged=judged, clean=clean, flags=flags,
        offers=offers, walked_past=tuple(walked_past), uncertain=uncertain,
    )


def _uncertain(summary, critique, judged: int, clean: int) -> Optional[int]:
    """The summary's count, or -- for a critique written before it was
    recorded -- the uncertain bands among its turns. A count that cannot fit
    beside the clean ones is not trusted."""
    count = _count(summary.get("uncertain"))
    if count is None:
        turns = critique.get("turns")
        if not isinstance(turns, list):
            return None
        count = sum(
            1 for turn in turns
            if isinstance(turn, Mapping) and isinstance(turn.get("judgment"), Mapping)
            and turn["judgment"].get("band") == "uncertain"
        )
    return count if clean + count <= judged else None


def _count(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def build(sessions: "Sequence[SessionMirror]", *, unreadable: "Sequence[str]" = ()) -> Mirror:
    ordered = tuple(sorted(sessions, key=lambda s: (s.date or "", s.session_id)))
    return Mirror(sessions=ordered, habits=_habits(ordered), trend=_trend(ordered),
                  unreadable=tuple(unreadable))


def _habits(sessions: "Sequence[SessionMirror]") -> "tuple[Habit, ...]":
    habits = []
    for flag in FLAG_KEYS:
        hits = [s.flags.get(flag, 0) for s in sessions if s.flags.get(flag, 0) > 0]
        if len(hits) >= MIN_SESSIONS_FOR_HABIT:
            habits.append(Habit(flag=flag, sessions=len(hits), total=sum(hits)))
    return tuple(sorted(habits, key=lambda h: (-h.sessions, -h.total, h.flag)))


def _trend(sessions: "Sequence[SessionMirror]") -> Optional[Trend]:
    critiqued = [s for s in sessions if s.critiqued and s.clean_rate is not None]
    if len(critiqued) < MIN_SESSIONS_FOR_TREND:
        return None
    half = len(critiqued) // 2
    # An odd count gives the middle interview to the LATER half: the question
    # is "am I getting better", and the most recent evidence should not be
    # the part left out.
    earlier, later = critiqued[:half], critiqued[half:]
    return Trend(
        earlier_sessions=len(earlier),
        later_sessions=len(later),
        earlier_clean_rate=_mean(s.clean_rate for s in earlier),
        later_clean_rate=_mean(s.clean_rate for s in later),
        earlier_flag_rates=_flag_rates(earlier, later),
        later_flag_rates=_flag_rates(later, earlier),
    )


def _flag_rates(half, other) -> "dict[str, float]":
    """Per flag, its mean rate over the interviews whose critique RECORDED it.
    A critique written before a flag existed (`off_topic` arrived 2026-10-21)
    has no count for it, which is not a count of zero: averaging it in as 0
    would show a change nobody made. A flag only half of the trend recorded
    is left out of both halves."""
    rates = {}
    for flag in FLAG_KEYS:
        recorded = [s for s in half if flag in s.flags]
        if recorded and any(flag in s.flags for s in other):
            rates[flag] = _mean(s.flags[flag] / s.judged for s in recorded)
    return rates


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0
