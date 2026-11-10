"""Reads one node's claims and transcripts into `missed.find`. Shared by the
`missed` command and the mirror's section, so both count the same way.

Facts are projected onto `missed.CitedClaim` the moment they load, so the
quote is never held here. Transcripts are read through `mirror_load`, the
same reader the walked-past detector uses, so an in-person session's
confirmed after-meeting transcript is the one judged -- and a session whose
speakers are still live guesses is not judged at all.

Raises `CorpusValidationError` for a malformed corpus; the callers report it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Sequence

from app.coach import context as coach_context
from app.coach import corpus as coach_corpus
from app.coach import missed as missed_mod
from app.coach import mirror_load
from app.coach import walked_past
from app.session import evidence as ev
from app.session.reader import list_session_ids

logger = logging.getLogger(__name__)


def read_claims(context_dir: Path) -> "tuple[missed_mod.CitedClaim, ...]":
    """Every claim in the node's corpus, quote-free; empty when none is written."""
    context_dir = Path(context_dir)
    if not (context_dir / coach_corpus.FACTS_FILENAME).is_file():
        return ()
    return tuple(missed_mod.cited_claim(fact) for fact in coach_corpus.load_facts(context_dir, sessions_root=None))


def load(context_dir: Path, sessions_root: Path, *, groups: "Optional[Sequence]" = None,
         claims: "Optional[Sequence[missed_mod.CitedClaim]]" = None) -> missed_mod.Report:
    """`groups`: the model's topics, or `None` for the lexical grouping.
    `claims`: `read_claims`' result when the caller already has it."""
    context_dir, sessions_root = Path(context_dir), Path(sessions_root)
    claims = read_claims(context_dir) if claims is None else tuple(claims)
    if not claims:
        return missed_mod.find((), {})
    # Only directories actually on disk: a session id is a corpus string, and
    # `sessions_root / id` must never be built from one that is not listed.
    on_disk = set(list_session_ids(sessions_root)) if sessions_root.is_dir() else set()
    turns_by_session, unconfirmed = {}, set()
    for session_id in sorted({claim.session_id for claim in claims} & on_disk):
        session_dir = sessions_root / session_id
        try:
            meta = mirror_load.session_meta(session_dir)
            turns = walked_past.turns(mirror_load.session_records(session_dir, meta))
        except Exception as exc:  # noqa: BLE001 -- per-session boundary, as in mirror_load
            logger.warning("missed: session %s skipped (%s)", session_id, type(exc).__name__)
            continue
        if not turns:
            continue
        turns_by_session[session_id] = turns
        if ev.extract_refusal(meta) is not None:
            unconfirmed.add(session_id)
    return missed_mod.find(claims, turns_by_session, unconfirmed=frozenset(unconfirmed), groups=groups,
                           scripts=session_scripts(context_dir, sessions_root, sorted(turns_by_session)),
                           vocabulary=missed_mod.project_vocabulary(turns_by_session),
                           flagged={sid: flagged_seqs(sessions_root / sid) for sid in turns_by_session})


# The critic's flags that mean "this question put the interviewer's idea in
# the interviewee's mouth" -- never a follow-up, whatever its words.
NOT_A_FOLLOW_UP_FLAGS = ("is_pitch", "is_leading")


def flagged_seqs(session_dir: Path) -> "frozenset[int]":
    """Seqs of the session's questions the critic flagged as a pitch or
    leading, from its `questions_critique.json` (read through `mirror_load`,
    as the mirror reads it). Only each row's `seqs` and `judgment` are read,
    never its text. No file, an unreadable one, or a malformed row: nothing
    flagged, which only keeps the detector as generous as it was."""
    critique = mirror_load.session_critique(Path(session_dir))
    rows = critique.get("turns") if critique is not None else None
    if not isinstance(rows, list):
        return frozenset()
    seqs: "set[int]" = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("judgment"), dict):
            continue
        row_seqs = row.get("seqs")
        if not isinstance(row_seqs, list) or not all(isinstance(q, int) and not isinstance(q, bool) for q in row_seqs):
            continue
        if any(row["judgment"].get(flag) is True for flag in NOT_A_FOLLOW_UP_FLAGS):
            seqs.update(row_seqs)
    return frozenset(seqs)


def session_scripts(context_dir: Path, sessions_root: Path,
                    session_ids: "Sequence[str]") -> "dict[str, tuple[str, ...]]":
    """Each session's guide questions: the `context_survey` snapshot `start`
    wrote into its session.json, else the project's survey -- an imported or
    mock interview has no snapshot. Tolerant: an unreadable survey means no
    guide questions to exclude, which only keeps the detector generous."""
    project: "Optional[tuple[str, ...]]" = None
    scripts: "dict[str, tuple[str, ...]]" = {}
    for session_id in session_ids:
        try:
            snapshot = mirror_load.session_meta(Path(sessions_root) / session_id).get("context_survey")
        except Exception:  # noqa: BLE001 -- per-session boundary, as in `load`
            snapshot = None
        if isinstance(snapshot, list):
            scripts[session_id] = tuple(e["text"] for e in snapshot
                                        if isinstance(e, dict) and isinstance(e.get("text"), str))
            continue
        if project is None:
            project = _project_survey(Path(context_dir))
        scripts[session_id] = project
    return scripts


def _project_survey(context_dir: Path) -> "tuple[str, ...]":
    if not (context_dir / coach_context.SURVEY_FILENAME).is_file():
        return ()  # no guide at all: nothing to exclude, and nothing worth a warning
    try:
        return tuple(item.text for item in coach_context.load_survey(context_dir))
    except Exception as exc:  # noqa: BLE001 -- see `session_scripts`
        logger.warning("missed: the project survey was not read (%s); no guide questions excluded",
                       type(exc).__name__)
        return ()
