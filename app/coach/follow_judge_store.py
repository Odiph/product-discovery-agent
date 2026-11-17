"""The follow-up judgment's cache: `context/followed.json`. Its only job is that file.

One judgment per node, keyed by `follow_judge.judgment_key` -- every item
sent (the topic label and the interviewer's turns after it), the model, the
instructions and the tool schema. A cache over other turns, other topics,
another model or another prompt is STALE; a file that does not parse into a
valid judgment is UNREADABLE. Both come back with a reason the command
prints, and neither is ever used.

Tolerant on load; strict on save. Holds the interviewer's own words and topic
labels only, never anything an interviewee said, and lives under `context/`,
which is git-ignored with the rest of the node's data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from app.coach import follow_judge as judge_mod
from app.coach import json_cache
from app.coach.json_cache import ABSENT, FRESH, STALE, UNREADABLE  # noqa: F401 -- re-exported

CACHE_FILENAME = "followed.json"
FORMAT_VERSION = 1


@dataclass(frozen=True)
class CacheState:
    status: str
    judgment: Optional[judge_mod.Judgment] = None
    """Set only when `status == FRESH`."""
    reason: str = ""


def load(context_dir: Path, items: "Sequence[judge_mod.FollowItem]", model: str) -> CacheState:
    payload, status, reason = json_cache.read(Path(context_dir) / CACHE_FILENAME, FORMAT_VERSION,
                                              "follow-up judgment")
    if payload is None:
        return CacheState(status, reason=reason)
    made_with = payload.get("model")
    if made_with != model:
        return CacheState(STALE, reason=f"it was judged by {made_with!r}, and the judge model is now {model!r}")
    if payload.get("key") != judge_mod.judgment_key(items, model):
        return CacheState(STALE, reason="your questions, the topics or the instructions changed since it was judged")
    try:
        judgment = _judgment(payload, model=model)
        _check(judgment, sent=set(judge_mod.unique_items(items)))
    except (KeyError, TypeError, ValueError) as exc:
        return CacheState(UNREADABLE, reason=f"{CACHE_FILENAME} is malformed ({exc})")
    return CacheState(FRESH, judgment=judgment)


def write(context_dir: Path, judgment: judge_mod.Judgment) -> Path:
    """Raises `ValueError` for a judgment that breaks its own rules; nothing
    is written then."""
    _check(judgment)
    return json_cache.write(Path(context_dir) / CACHE_FILENAME, {
        "version": FORMAT_VERSION,
        "model": judgment.model,
        "key": judgment.key,
        "items": [{"topic": entry.topic, "turns": [{"n": n, "text": text} for n, text in entry.turns],
                   "followed": followed} for entry, followed in judgment.answers],
    })


def _judgment(payload: dict, *, model: str) -> judge_mod.Judgment:
    raw = payload["items"]
    if not isinstance(raw, list):
        raise ValueError("items is not a list")
    answers = []
    for entry in raw:
        topic, turns, followed = entry["topic"], entry["turns"], entry["followed"]
        if not isinstance(topic, str) or not isinstance(turns, list):
            raise ValueError("an item needs a string topic and a list of turns")
        pairs = []
        for turn in turns:
            n, text = turn["n"], turn["text"]
            if not isinstance(n, int) or isinstance(n, bool) or not isinstance(text, str):
                raise ValueError("a turn needs a whole number n and a string text")
            pairs.append((n, text))
        if not isinstance(followed, bool):
            raise ValueError("an answer is not true or false")
        answers.append((judge_mod.FollowItem(topic=topic, turns=tuple(pairs)), followed))
    return judge_mod.Judgment(model=model, key=str(payload["key"]), answers=tuple(answers))


def _check(judgment: judge_mod.Judgment, *, sent: "Optional[set]" = None) -> None:
    seen: "set" = set()
    for entry, followed in judgment.answers:
        if not entry.topic.strip() or not entry.turns or any(not text.strip() for _, text in entry.turns):
            raise ValueError("an item has a blank topic or turn")
        if entry in seen:
            raise ValueError(f"the item for topic {entry.topic!r} is listed twice")
        if not isinstance(followed, bool):
            raise ValueError(f"the answer for topic {entry.topic!r} is not true or false")
        if sent is not None and entry not in sent:
            raise ValueError(f"an answer for topic {entry.topic!r} is for turns never sent")
        seen.add(entry)
