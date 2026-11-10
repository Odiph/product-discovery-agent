"""Reads one project's sessions into the mirror (`mirror.py`). Shared by the
`mirror` command, the hub panel and the MCP `get_mirror` tool, so all three
count the same way.

An in-person session whose speakers are not yet confirmed contributes its
critique but no walked-past moments: its roles are live guesses, and a
moment is precisely a claim about who said what. A session with no speech at
all (an aborted start, a device test) is left out. A session that cannot be
read at all is left out AND named in `Mirror.unreadable`, so one damaged
directory never takes the report down and never vanishes silently either.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.coach import mirror as mirror_mod
from app.coach import walked_past
from app.coach.asked_store import CRITIQUE_DOC_FILENAME
from app.session import evidence as ev
from app.session.reader import MalformedRecordError, list_session_ids, read_session

logger = logging.getLogger(__name__)


def load(sessions_root: Path) -> mirror_mod.Mirror:
    rows, unreadable = [], []
    for session_id in list_session_ids(Path(sessions_root)):
        try:
            row = _session(Path(sessions_root) / session_id)
        except Exception as exc:  # noqa: BLE001 -- per-session boundary; see the module docstring
            # The TYPE only: a parser's message can quote the file.
            logger.warning("mirror: session %s skipped (%s)", session_id, type(exc).__name__)
            unreadable.append(session_id)
            continue
        if row is not None:
            rows.append(row)
    return mirror_mod.build(rows, unreadable=unreadable)


def turn_texts(session_dir: Path) -> "dict[tuple[int, ...], str]":
    """The words of each turn, keyed by its seqs, from the SAME transcript
    the detector read -- for `mirror --show`, which prints them locally."""
    return {turn.seqs: turn.text for turn in walked_past.turns(_records(session_dir, _meta(session_dir)))}


def _session(session_dir: Path) -> Optional[mirror_mod.SessionMirror]:
    meta = _meta(session_dir)
    critique = _critique(session_dir)
    records = _records(session_dir, meta)
    turns = walked_past.turns(records)
    if not turns and critique is None:
        return None
    if ev.extract_refusal(meta) is None:
        offers = sum(1 for t in turns if t.speaker == walked_past.INTERVIEWEE and walked_past.offer_signals(t.text))
        moments = walked_past.detect(records)
    else:
        offers, moments = 0, []
    started = meta.get("started_at")
    return mirror_mod.session_mirror(
        session_dir.name,
        date=started[:10] if isinstance(started, str) and started else None,
        critique=critique,
        offers=offers,
        walked_past=moments,
    )


def _meta(session_dir: Path) -> "dict[str, Any]":
    try:
        meta = ev.read_meta(session_dir)
    except ev.EvidenceStateError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _records(session_dir: Path, meta: "dict[str, Any]"):
    try:
        return read_session(session_dir, transcript_filename=ev.transcript_filename_for(meta)).records
    except (MalformedRecordError, ValueError, OSError):
        return ()


def _critique(session_dir: Path) -> "Optional[dict[str, Any]]":
    path = session_dir / CRITIQUE_DOC_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return payload if isinstance(payload, dict) else None
