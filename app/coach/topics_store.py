"""The model grouping's cache: `context/topics.json`. Its only job is that file.

One grouping per node, keyed by `topics.claims_key` -- every claim sent and
the model that grouped them. A cache over different claims or another model
is STALE and a file that does not parse into a valid grouping is UNREADABLE;
both come back with a reason the command prints, and neither is ever used.
A grouping silently applied to claims it was never made from would label one
interview's claim with another's topic and say nothing.

Tolerant on load (any defect is a status and a reason, never a crash); strict
on save (a grouping that breaks its own rules -- a claim in two topics, an
empty or unlabelled topic -- raises before anything is written). Written
atomically: temp file in the same directory, fsync, `os.replace`. Holds topic
labels and fact ids only, never claim text, and lives under `context/`, which
is git-ignored with the rest of the node's data.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from app.coach import topics as topics_mod

CACHE_FILENAME = "topics.json"
FORMAT_VERSION = 1

ABSENT = "absent"
FRESH = "fresh"
STALE = "stale"
UNREADABLE = "unreadable"


@dataclass(frozen=True)
class CacheState:
    status: str
    grouping: Optional[topics_mod.Grouping] = None
    """Set only when `status == FRESH`."""
    reason: str = ""


def load(context_dir: Path, lines: "Sequence[topics_mod.ClaimLine]", model: str) -> CacheState:
    path = Path(context_dir) / CACHE_FILENAME
    if not path.is_file():
        return CacheState(ABSENT)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return CacheState(UNREADABLE, reason=f"{CACHE_FILENAME} cannot be read ({type(exc).__name__})")
    if not isinstance(payload, dict) or payload.get("version") != FORMAT_VERSION:
        return CacheState(UNREADABLE, reason=f"{CACHE_FILENAME} is not a version-{FORMAT_VERSION} topic grouping")
    made_with = payload.get("model")
    if made_with != model:
        return CacheState(STALE, reason=f"it was grouped by {made_with!r}, and the extract model is now {model!r}")
    if payload.get("claims_key") != topics_mod.claims_key(lines, model):
        return CacheState(STALE, reason="the claims changed since it was grouped")
    try:
        grouping = _grouping(payload, model=model)
        _check(grouping, known={line.fact_id for line in lines})
    except (KeyError, TypeError, ValueError) as exc:
        return CacheState(UNREADABLE, reason=f"{CACHE_FILENAME} is malformed ({exc})")
    return CacheState(FRESH, grouping=grouping)


def write(context_dir: Path, grouping: topics_mod.Grouping) -> Path:
    """Raises `ValueError` for a grouping that breaks its own rules; nothing
    is written then."""
    _check(grouping)
    path = Path(context_dir) / CACHE_FILENAME
    payload = {
        "version": FORMAT_VERSION,
        "model": grouping.model,
        "claims_key": grouping.claims_key,
        "topics": [{"label": topic.label, "fact_ids": list(topic.fact_ids)} for topic in grouping.topics],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    return path


def _grouping(payload: dict, *, model: str) -> topics_mod.Grouping:
    raw = payload["topics"]
    if not isinstance(raw, list):
        raise ValueError("topics is not a list")
    topics = []
    for entry in raw:
        label, fact_ids = entry["label"], entry["fact_ids"]
        if not isinstance(label, str) or not isinstance(fact_ids, list) or not all(
                isinstance(fact_id, str) for fact_id in fact_ids):
            raise ValueError("a topic needs a string label and a list of string fact ids")
        topics.append(topics_mod.TopicGroup(label=label, fact_ids=tuple(fact_ids)))
    return topics_mod.Grouping(model=model, claims_key=str(payload["claims_key"]), topics=tuple(topics))


def _check(grouping: topics_mod.Grouping, *, known: "Optional[set[str]]" = None) -> None:
    placed: "set[str]" = set()
    for topic in grouping.topics:
        if not topic.label.strip():
            raise ValueError("a topic has no label")
        if not topic.fact_ids:
            raise ValueError(f"topic {topic.label!r} has no claims")
        for fact_id in topic.fact_ids:
            if fact_id in placed:
                raise ValueError(f"claim {fact_id} is in two topics")
            if known is not None and fact_id not in known:
                raise ValueError(f"topic {topic.label!r} names claim {fact_id}, which is not in the corpus")
            placed.add(fact_id)
