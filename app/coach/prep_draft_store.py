"""The question draft's cache: `context/prep_draft.json`. Its only job is that file.

One draft per node, keyed by `prep_draft.draft_key` -- the exact inputs sent
(gaps, survey, brief, hypotheses, habit and topic labels), the model, the
instructions, the tool schema and the prompt version. A draft for other
inputs, another model or another prompt is STALE; a file that does not parse
into a valid draft is UNREADABLE. Both come back with a reason the command
prints, and neither is ever used.

Holds the drafted questions and what was dropped, nothing an interviewee
said, and lives under `context/`, git-ignored with the rest of the node's data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.coach import json_cache
from app.coach import prep_draft as draft_mod
from app.coach.json_cache import ABSENT, FRESH, STALE, UNREADABLE  # noqa: F401 -- re-exported

CACHE_FILENAME = "prep_draft.json"
FORMAT_VERSION = 1


@dataclass(frozen=True)
class CacheState:
    status: str
    draft: Optional[draft_mod.Draft] = None
    """Set only when `status == FRESH`."""
    reason: str = ""


def load(context_dir: Path, drafted: draft_mod.DraftInputs, model: str) -> CacheState:
    payload, status, reason = json_cache.read(Path(context_dir) / CACHE_FILENAME, FORMAT_VERSION,
                                              "question draft")
    if payload is None:
        return CacheState(status, reason=reason)
    made_with = payload.get("model")
    if made_with != model:
        return CacheState(STALE, reason=f"it was drafted by {made_with!r}, and the judge model is now {model!r}")
    if payload.get("key") != draft_mod.draft_key(drafted, model):
        return CacheState(STALE, reason="the gaps, the survey, the brief, the hypotheses, the habits, the topics "
                                        "or the instructions changed since it was drafted")
    try:
        draft = _draft(payload, model=model)
        _check(draft, sent={g.gap_id for g in drafted.gaps})
    except (KeyError, TypeError, ValueError) as exc:
        return CacheState(UNREADABLE, reason=f"{CACHE_FILENAME} is malformed ({exc})")
    return CacheState(FRESH, draft=draft)


def write(context_dir: Path, draft: draft_mod.Draft) -> Path:
    """Raises `ValueError` for a draft that breaks its own rules; nothing is written then."""
    _check(draft)
    return json_cache.write(Path(context_dir) / CACHE_FILENAME, {
        "version": FORMAT_VERSION,
        "model": draft.model,
        "key": draft.key,
        "questions": [{"gap_id": q.gap_id, "text": q.text, "why": q.why} for q in draft.questions],
        "dropped": [{"gap_id": d.gap_id, "text": d.text, "reason": d.reason} for d in draft.dropped],
    })


def _rows(payload: dict, name: str, fields: "tuple[str, str, str]") -> "list[tuple[str, str, str]]":
    raw = payload[name]
    if not isinstance(raw, list):
        raise ValueError(f"{name} is not a list")
    rows = []
    for entry in raw:
        row = tuple(entry[f] for f in fields)
        if not all(isinstance(value, str) for value in row):
            raise ValueError(f"every {name} entry needs string {', '.join(fields)}")
        rows.append(row)
    return rows


def _draft(payload: dict, *, model: str) -> draft_mod.Draft:
    questions = tuple(draft_mod.Question(*row) for row in _rows(payload, "questions", ("gap_id", "text", "why")))
    dropped = tuple(draft_mod.DroppedQuestion(*row)
                    for row in _rows(payload, "dropped", ("gap_id", "text", "reason")))
    return draft_mod.Draft(model=model, key=str(payload["key"]), questions=questions, dropped=dropped)


def _check(draft: draft_mod.Draft, *, sent: "Optional[set]" = None) -> None:
    for question in draft.questions:
        if not question.text.strip() or not question.gap_id.strip():
            raise ValueError("a question has a blank text or gap id")
        if sent is not None and question.gap_id not in sent:
            raise ValueError(f"a question cites gap {question.gap_id!r}, which was never sent")
