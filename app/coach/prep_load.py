"""What `prep` reads from the interviews on disk: which survey each one ran
with, and which questions it asked. Shared by `python -m app prep` and the
`author` page's prep panel, so the two can never judge a question
differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from app.coach import coverage_judge, coverage_report, coverage_store, reasoning_client, walked_past
from app.coach import missed as missed_mod
from app.coach import prep as prep_mod
from app.coach.context import SurveyItem
from app.session import evidence as ev
from app.session.reader import MalformedRecordError, list_session_ids, read_session


def coverage_tracked(meta: dict) -> bool:
    """Only the live coach writes coverage events. An imported interview, or
    a call recorded with the coach off, has no record of which questions were
    asked -- its silence is not "never asked". A session too old to say
    (no `coach_enabled` key) keeps the old reading: tracked."""
    return meta.get("engine") != "import" and meta.get("coach_enabled") is not False


def interviews_and_coverage(
    sessions_root, *, survey: "Sequence[SurveyItem]" = (),
    reading: "Optional[Mapping[str, Sequence[str]]]" = None,
) -> "tuple[dict, dict[str, list[str]], list[str], list[str], list[str]]":
    """Interviews are sessions where the interviewer said something: a device
    test or an aborted start must not count as "an interview that never asked
    question 4".

    An interview with no coverage record (see `coverage_tracked`) has it
    RECONSTRUCTED from its transcript: each interviewer turn matched to a
    guide question by the words they share (`missed`'s script matcher, the
    one that tells the guide moving on from a follow-up). Those interviews
    are returned as `reconstructed`. One where no turn matches any question
    stays `untracked`: asking none of the guide cannot be told from a
    matcher that cannot read it (an English interview, a Hebrew guide).

    `survey`: the project's guide, used where a session kept no snapshot of
    its own question texts. `reading`: the model's reading of untracked
    sessions (`model_reading`, from `python -m app coverage`); a session in
    it takes the model's questions instead of the word match, and counts as
    `reconstructed` -- the same one-way evidence -- even when the model
    found none."""
    guides: "dict[str, Optional[frozenset]]" = {}
    asked_in: "dict[str, list[str]]" = {}
    unconfirmed: "list[str]" = []
    untracked: "list[str]" = []
    reconstructed: "list[str]" = []
    for session_id, meta, asked, live in _interviews(sessions_root):
        if ev.extract_refusal(meta) is not None:
            unconfirmed.append(session_id)
        snapshot = meta.get("context_survey")
        guides[session_id] = (
            frozenset(e["id"] for e in snapshot if isinstance(e, dict) and isinstance(e.get("id"), str))
            if isinstance(snapshot, list) else None
        )
        if coverage_tracked(meta):
            events = [r for r in live if isinstance(r, dict) and r.get("kind") == "event"]
            question_ids = coverage_report.asked_question_ids(events)
        elif reading is not None and session_id in reading:
            question_ids = list(reading[session_id])
            reconstructed.append(session_id)
        else:
            question_ids = reconstructed_question_ids(asked, session_guide(snapshot, survey))
            (reconstructed if question_ids else untracked).append(session_id)
        for question_id in question_ids:
            asked_in.setdefault(question_id, []).append(session_id)
    return guides, asked_in, unconfirmed, untracked, reconstructed


def _interviews(sessions_root):
    """(id, meta, the interviewer's turn texts, the live records) of every
    session where the interviewer said something; a malformed session is
    skipped, never fatal."""
    sessions_root = Path(sessions_root)
    if not sessions_root.is_dir():
        return
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
        asked = [t.text for t in walked_past.turns(records) if t.speaker == walked_past.INTERVIEWER]
        if asked:
            yield session_id, meta, asked, live


def untracked_turns(sessions_root) -> "dict[str, tuple[str, ...]]":
    """The interviewer's turns of every interview with no live coverage
    record: what `python -m app coverage` sends, and what its cache is keyed on."""
    return {sid: tuple(asked) for sid, meta, asked, _ in _interviews(sessions_root) if not coverage_tracked(meta)}


@dataclass(frozen=True)
class Reading:
    asked: "Optional[dict[str, tuple[str, ...]]]"
    """Session -> the survey ids the model found; `None` when no fresh reading."""
    note: str = ""
    """Why it is not used, when it exists but is stale or unreadable."""


def model_reading(context_dir, sessions_root, survey: "Sequence[SurveyItem]") -> Reading:
    """The cached `coverage` reading, only when FRESH for exactly these
    interviews, this survey and the current extract model. Reads a file;
    never builds a model client."""
    if context_dir is None:
        return Reading(None)
    questions = coverage_judge.questions(survey)
    turns = untracked_turns(sessions_root)
    if not questions or not turns:
        return Reading(None)
    state = coverage_store.load(Path(context_dir), questions, turns, reasoning_client.resolve_judge_model(context_dir))
    if state.status == coverage_store.FRESH:
        return Reading(state.coverage.as_dict())
    if state.status == coverage_store.ABSENT:
        return Reading(None)
    return Reading(None, f"context/{coverage_store.CACHE_FILENAME} is {state.status} ({state.reason}), so the "
                         f"word match was used: re-run python -m app coverage --yes")


def session_guide(snapshot, survey: "Sequence[SurveyItem]") -> "tuple[tuple[str, str], ...]":
    """(id, text) of each question a session's guide held: its own snapshot's
    texts where it kept them, else the project survey's -- limited to the
    snapshot's ids when it kept only those. An imported interview has no
    snapshot and is matched against the whole project survey."""
    project = tuple((item.id, item.text) for item in survey)
    if not isinstance(snapshot, list):
        return project
    entries = [e for e in snapshot if isinstance(e, dict) and isinstance(e.get("id"), str)]
    own = tuple((e["id"], e["text"]) for e in entries if isinstance(e.get("text"), str))
    if own:
        return own
    ids = {e["id"] for e in entries}
    return tuple(pair for pair in project if pair[0] in ids)


def reconstructed_question_ids(turns: "Sequence[str]", guide: "Sequence[tuple[str, str]]") -> "list[str]":
    """The guide questions these interviewer turns asked, in the order first
    asked. Each question is keyed alone, so one too short to recognise is
    dropped without shifting the others' ids."""
    keyed = [(qid, keys) for qid, text in guide for keys in missed_mod.script_keys([text])]
    items = tuple(keys for _, keys in keyed)
    found: "list[str]" = []
    for text in turns:
        index = missed_mod._script_index(text, items)
        if index is not None and keyed[index][0] not in found:
            found.append(keyed[index][0])
    return found


def survey_proposals(survey: "tuple[SurveyItem, ...]", sessions_root: Path,
                     context_dir: "Optional[Path]" = None) -> "tuple[prep_mod.ItemProposal, ...]":
    """Only the questions `prep` would change: what the `author` page offers
    to apply. A question it would keep is not a proposal."""
    reading = model_reading(context_dir, sessions_root, survey).asked
    guides, asked_in, _, untracked, reconstructed = interviews_and_coverage(sessions_root, survey=survey,
                                                                            reading=reading)
    return tuple(p for p in prep_mod.item_proposals(survey, asked_in, guides,
                                                    untracked=untracked, reconstructed=reconstructed,
                                                    read_by_model=frozenset(reading or ()))
                 if p.action != prep_mod.KEEP)
