"""The hub's survey coverage: this interview, and the project standing.

Two ANSWERS, not one, because they lead to different actions: "we missed
question 4 tonight" is a note about this call, and "question 4 has never been
asked, in six interviews" is a decision about the next one.

**Live records are replayed, never re-inferred.** Every judgement in a live
session was made by `app/coach/coverage.py` and written to the transcript;
this replays it (see `app/coach/coverage_report.py` for why a second
inference path would be a second answer to the same question).

**An interview with no live record is read the way `prep` reads it.** Only
the live coach writes coverage events, so an imported interview, or one
recorded with the coach off, has none; its silence used to read as "asked
nothing" and made the hub say every question was never asked. Those
interviews now take `app/coach/prep_load.py`'s reading, read-only and with no
model call: the model's cached reading (`python -m app coverage`) when fresh,
else the word match, else nothing (`untracked`). Each session carries its
`source`.

**The rule is one-way, as in `prep`.** A hit from a reconstructed interview
counts as asked; its silence is "not found, check by hand", never "never
asked". So `never_asked` is filled only when every interview has a live
record; `not_found` always carries the questions no interview was found to
ask, and the client words it by `sources`.

Degrades in its own section like everything else on the hub, and
per-session inside the standing: one unreadable transcript among twenty must
not cost the operator the other nineteen.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Sequence

from app.coach import coverage_report, prep_load
from app.coach.context import load_survey
from app.session.reader import read_session

logger = logging.getLogger(__name__)

LIVE = "live"
MODEL = "model"
WORDS = "words"
UNTRACKED = "untracked"
SOURCES = (LIVE, MODEL, WORDS, UNTRACKED)


def survey_item(item: Any) -> "dict[str, Any]":
    return {"id": item.id, "order": item.order, "text": item.text}


def _items(items: Sequence[Any]) -> "list[dict[str, Any]]":
    return [survey_item(item) for item in items]


def _survey(context_dir: Path) -> tuple:
    try:
        return tuple(load_survey(context_dir))
    except Exception as exc:  # noqa: BLE001 -- a project with no survey is the COMMON path
        # Not an error the operator has to act on: every real recording so far
        # ran with no survey at all. The absent survey is reported as absence
        # further down, via `reportable`, rather than as a failure here.
        logger.info("no readable survey for this project error_type=%s", type(exc).__name__)
        return ()


def _read_sessions(sessions_root: Path) -> "tuple[dict[str, tuple[str, ...]], list[str]]":
    """(live session -> the question ids it recorded, the readable sessions
    with no live record). An unreadable session is skipped, never fatal."""
    live: "dict[str, tuple[str, ...]]" = {}
    other: "list[str]" = []
    if not sessions_root.is_dir():
        return live, other
    for session_dir in sorted(sessions_root.iterdir()):
        if not session_dir.is_dir():
            continue
        try:
            read = read_session(session_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("skipping a session while counting coverage session=%s error_type=%s",
                           session_dir.name, type(exc).__name__)
            continue
        meta = read.metadata if isinstance(read.metadata, dict) else {}
        if prep_load.coverage_tracked(meta):
            live[session_dir.name] = coverage_report.asked_question_ids(read.records_of_kind("event"))
        else:
            other.append(session_dir.name)
    return live, other


def _reconstruct(paths: Any, survey: tuple, others: "list[str]"
                 ) -> "tuple[dict[str, str], dict[str, list[str]], str]":
    """(session -> source, session -> the question ids found, the stale-reading
    note) for the sessions with no live record, through `prep_load` only."""
    sources = {sid: UNTRACKED for sid in others}
    found: "dict[str, list[str]]" = {sid: [] for sid in others}
    if not others or not survey:
        # No survey: nothing to match, and no standing to put it in.
        return sources, found, ""
    try:
        reading = prep_load.model_reading(paths.context_dir, paths.sessions_root, survey)
        _, asked_in, _, _, reconstructed = prep_load.interviews_and_coverage(
            paths.sessions_root, survey=survey, reading=reading.asked)
    except Exception as exc:  # noqa: BLE001 -- the reading is a bonus; without it they stay unread
        logger.warning("could not read coverage back from transcripts error_type=%s", type(exc).__name__)
        return sources, found, ""
    read_by_model = set(reading.asked or ())
    for sid in others:
        if sid in reconstructed:
            sources[sid] = MODEL if sid in read_by_model else WORDS
            # In first-found order across the project, not this interview's
            # asked order: a reconstructed reading has no live sequence.
            found[sid] = [qid for qid, sessions in asked_in.items() if sid in sessions]
    return sources, found, reading.note


def _project(survey: tuple, live: dict, sources: dict, found: dict, note: str) -> "dict[str, Any]":
    per_session = {**{sid: tuple(ids) for sid, ids in found.items()}, **live}
    standing = coverage_report.project_survey_standing(per_session, survey=survey)
    counts = {source: 0 for source in SOURCES}
    counts[LIVE] = len(live)
    for source in sources.values():
        counts[source] += 1
    every_one_live = counts[LIVE] == standing.sessions_read
    return {
        "sessions_read": standing.sessions_read,
        # ONE-WAY: silence counts as "never asked" only where every interview
        # has a live record. Anywhere else it is `not_found`.
        "never_asked": _items(standing.never_asked) if every_one_live else [],
        "not_found": _items(standing.never_asked),
        "times_asked": {qid: standing.times_asked(qid) for qid in standing.asked_in_sessions},
        "sources": counts,
        "reading_note": note,
    }


def _session(paths: Any, session_id: str, survey: tuple, source: str,
             found: "Optional[list[str]]") -> "tuple[Optional[dict[str, Any]], Optional[str]]":
    """(the session payload, an error). `found` is None for a live session."""
    try:
        read = read_session(paths.sessions_root / session_id)
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    snapshot = read.metadata.get("context_survey")
    try:
        if found is None:
            coverage = coverage_report.coverage_for_session(read.records, session_survey=snapshot,
                                                            project_survey=survey)
        else:
            coverage = coverage_report.coverage_from_ids(found, session_survey=snapshot, project_survey=survey)
    except Exception as exc:  # noqa: BLE001 -- a stored survey that no longer parses
        return None, f"{type(exc).__name__}: {exc}"
    live = found is None
    return {
        # `reportable` before anything else, because it is the field that keeps
        # "this interview ran without a survey" from rendering as "0 of 0
        # covered". They are different statements and only one of them is a miss.
        "reportable": coverage.is_reportable,
        "survey_source": coverage.survey_source,
        "source": source,
        "asked": _items(coverage.asked),
        # Only a live record can say a question was not asked. A reconstructed
        # interview's remainder is "not found": check by hand.
        "unasked": _items(coverage.unasked) if live else [],
        "not_found": [] if live else _items(coverage.unasked),
        "orphaned_question_ids": list(coverage.orphaned_question_ids),
        "total": coverage.total,
    }, None


def build(paths: Any, session_id: "Optional[str]") -> "dict[str, Any]":
    result: "dict[str, Any]" = {"session": None, "project": None, "error": None}
    survey = _survey(paths.context_dir)
    live, others = _read_sessions(paths.sessions_root)
    sources, found, note = _reconstruct(paths, survey, others)
    if survey:
        result["project"] = _project(survey, live, sources, found, note)
    if session_id is None or not (paths.sessions_root / session_id).is_dir():
        return result
    if session_id in live or session_id not in sources:
        # Not in `sources`: unreadable a moment ago, so the read below reports it.
        result["session"], result["error"] = _session(paths, session_id, survey, LIVE, None)
    else:
        result["session"], result["error"] = _session(paths, session_id, survey, sources[session_id],
                                                      found[session_id])
    return result
