"""What `prep` reads from the interviews on disk: which survey each one ran
with, and which questions it asked. Shared by `python -m app prep` and the
`author` page's prep panel, so the two can never judge a question
differently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.coach import coverage_report, walked_past
from app.coach import prep as prep_mod
from app.coach.context import SurveyItem
from app.session import evidence as ev
from app.session.reader import MalformedRecordError, list_session_ids, read_session


def interviews_and_coverage(sessions_root) -> "tuple[dict, dict[str, list[str]], list[str]]":
    """Interviews are sessions where the interviewer said something: a device
    test or an aborted start must not count as "an interview that never asked
    question 4"."""
    guides: "dict[str, Optional[frozenset]]" = {}
    asked_in: "dict[str, list[str]]" = {}
    unconfirmed: "list[str]" = []
    for session_id in sorted(list_session_ids(sessions_root)):
        session_dir = sessions_root / session_id
        try:
            meta = ev.read_meta(session_dir)
        except ev.EvidenceStateError:
            meta = {}
        meta = meta if isinstance(meta, dict) else {}
        try:
            records = read_session(session_dir, transcript_filename=ev.transcript_filename_for(meta)).records
            # Coverage events live in the LIVE transcript; an in-person
            # evidence transcript carries segments only. Read inside the same
            # guard: a bad live file costs this session, never the command.
            live = read_session(session_dir).records if ev.is_in_person(meta) else records
        except (MalformedRecordError, ValueError, OSError):
            continue
        if not any(t.speaker == walked_past.INTERVIEWER for t in walked_past.turns(records)):
            continue
        if ev.extract_refusal(meta) is not None:
            unconfirmed.append(session_id)
        snapshot = meta.get("context_survey")
        guides[session_id] = (
            frozenset(e["id"] for e in snapshot if isinstance(e, dict) and isinstance(e.get("id"), str))
            if isinstance(snapshot, list) else None
        )
        events = [r for r in live if isinstance(r, dict) and r.get("kind") == "event"]
        for question_id in coverage_report.asked_question_ids(events):
            asked_in.setdefault(question_id, []).append(session_id)
    return guides, asked_in, unconfirmed


def survey_proposals(survey: "tuple[SurveyItem, ...]", sessions_root: Path) -> "tuple[prep_mod.ItemProposal, ...]":
    """Only the questions `prep` would change: what the `author` page offers
    to apply. A question it would keep is not a proposal."""
    guides, asked_in, _ = interviews_and_coverage(sessions_root)
    return tuple(p for p in prep_mod.item_proposals(survey, asked_in, guides) if p.action != prep_mod.KEEP)
