"""The coverage reading's cache: `context/coverage.json`. Its only job is that file.

Keyed by `coverage_judge.coverage_key`: every survey question and every
interviewer turn sent, the model, the instructions and the tool schema. A
new interview, a re-imported transcript, a reworded survey, another model or
another prompt makes it STALE; a file that does not parse is UNREADABLE.
`prep` uses it only when FRESH and otherwise falls back to the word match,
saying why. Tolerant on load; strict on save (a survey id that is not a
question, a session listed twice). Holds the operator's guide and own turns
only, never anything an interviewee said; `context/` is git-ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from app.coach import coverage_judge as judge_mod
from app.coach import json_cache
from app.coach.json_cache import ABSENT, FRESH, STALE, UNREADABLE  # noqa: F401 -- re-exported

CACHE_FILENAME = "coverage.json"
FORMAT_VERSION = 1


@dataclass(frozen=True)
class CacheState:
    status: str
    coverage: Optional[judge_mod.Coverage] = None
    reason: str = ""


def load(context_dir: Path, survey_questions: "Sequence[tuple[str, str]]",
         session_turns: "Mapping[str, Sequence[str]]", model: str) -> CacheState:
    payload, status, reason = json_cache.read(Path(context_dir) / CACHE_FILENAME, FORMAT_VERSION,
                                              "coverage reading")
    if payload is None:
        return CacheState(status, reason=reason)
    made_with = payload.get("model")
    if made_with != model:
        return CacheState(STALE, reason=f"it was read by {made_with!r}, and the extract model is now {model!r}")
    if payload.get("key") != judge_mod.coverage_key(survey_questions, session_turns, model):
        return CacheState(STALE, reason="the survey or the interviews changed since it was read")
    try:
        coverage = _coverage(payload, model=model)
        _check(coverage, question_ids={qid for qid, _ in survey_questions},
               session_ids={sid for sid, _ in judge_mod.sessions(session_turns)})
    except (KeyError, TypeError, ValueError) as exc:
        return CacheState(UNREADABLE, reason=f"{CACHE_FILENAME} is malformed ({exc})")
    return CacheState(FRESH, coverage=coverage)


def write(context_dir: Path, coverage: judge_mod.Coverage,
          question_ids: "Optional[set[str]]" = None) -> Path:
    _check(coverage, question_ids=question_ids)
    return json_cache.write(Path(context_dir) / CACHE_FILENAME, {
        "version": FORMAT_VERSION,
        "model": coverage.model,
        "key": coverage.key,
        "sessions": [{"session_id": sid, "asked": list(ids)} for sid, ids in coverage.asked],
    })


def _coverage(payload: dict, *, model: str) -> judge_mod.Coverage:
    raw = payload["sessions"]
    if not isinstance(raw, list):
        raise ValueError("sessions is not a list")
    asked = []
    for entry in raw:
        sid, ids = entry["session_id"], entry["asked"]
        if not isinstance(sid, str) or not isinstance(ids, list) or not all(isinstance(q, str) for q in ids):
            raise ValueError("a session needs a string id and a list of string question ids")
        asked.append((sid, tuple(ids)))
    return judge_mod.Coverage(model=model, key=str(payload["key"]), asked=tuple(asked))


def _check(coverage: judge_mod.Coverage, *, question_ids: "Optional[set[str]]" = None,
           session_ids: "Optional[set[str]]" = None) -> None:
    seen: "set[str]" = set()
    for sid, ids in coverage.asked:
        if not sid.strip():
            raise ValueError("a session id is blank")
        if sid in seen:
            raise ValueError(f"session {sid} is listed twice")
        if session_ids is not None and sid not in session_ids:
            raise ValueError(f"session {sid} was never sent")
        if len(set(ids)) != len(ids):
            raise ValueError(f"session {sid} lists a question twice")
        if question_ids is not None and not set(ids) <= question_ids:
            raise ValueError(f"session {sid} names a question that is not in the survey")
        seen.add(sid)
