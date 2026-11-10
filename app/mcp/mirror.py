"""`get_mirror`: the interviewer's habits across a project's interviews, over
MCP. Numbers, flags and sequence numbers only.

The mirror is about the interviewer, but a walked-past moment is made of the
INTERVIEWEE's words, and the critique artifact holds the interviewer's
questions verbatim. Neither crosses: a moment is its time, its signal names
and the turn sequence numbers, so `/interview-gap` can say "you walked past
a workaround at 12:40 in the 3 October interview" and the operator reads the
words on their own machine (`python -m app mirror --show`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.coach import mirror_load

DESCRIPTION = (
    "The interviewer's own habits across every interview in one project: per interview, how many "
    "of their questions the critique judged, how many were clean and how many it was unsure of "
    "(the clean rate leaves those out: mostly follow-ups judged without what was said before them), "
    "which flags it raised "
    "(leading, hypothetical, pitch, opinion-seeking, confirmation-only, off-topic); HABITS (a flag in two or "
    "more interviews); the TREND from the earlier half of interviews to the later half; and "
    "WALKED-PAST moments -- an interviewee turn with a concrete occasion, workaround, cost or pain, "
    "followed by a question on something else -- as times and signal names. No words cross: read "
    "them with `python -m app mirror --show`. Walked-past is a detector, not a verdict. Interviews "
    "listed in 'uncritiqued' are missing from the habits and the trend, not clean."
)


def get(node) -> "dict[str, Any]":
    report = mirror_load.load(Path(node.sessions_root))
    trend = report.trend
    return {
        "project": node.path,
        "interviews": [
            {
                "session_id": row.session_id,
                "date": row.date,
                "critiqued": row.critiqued,
                "judged_questions": row.judged,
                "clean_questions": row.clean,
                "uncertain_questions": row.uncertain,
                "clean_rate": row.clean_rate,
                "flags": {flag: n for flag, n in row.flags.items()},
                "offers": row.offers,
                "walked_past": [
                    {
                        "at_s": moment.at_s,
                        "signals": list(moment.signals),
                        "acknowledged": moment.acknowledged,
                        "offer_seqs": list(moment.offer_seqs),
                        "next_question_seqs": list(moment.next_seqs),
                    }
                    for moment in row.walked_past
                ],
            }
            for row in report.sessions
        ],
        "habits": [{"flag": h.flag, "interviews": h.sessions, "questions": h.total} for h in report.habits],
        "trend": None if trend is None else {
            "earlier_interviews": trend.earlier_sessions,
            "later_interviews": trend.later_sessions,
            "earlier_clean_rate": trend.earlier_clean_rate,
            "later_clean_rate": trend.later_clean_rate,
            "earlier_flag_rates": {f: r for f, r in trend.earlier_flag_rates.items()},
            "later_flag_rates": {f: r for f, r in trend.later_flag_rates.items()},
        },
        "uncritiqued": list(report.uncritiqued),
        "unreadable": list(report.unreadable),
        "walked_past_total": report.walked_past_total,
        "offers_total": report.offers_total,
    }
