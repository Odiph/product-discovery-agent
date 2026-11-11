"""The prompted judgment's cache: `context/prompted.json`. Its only job is that file.

One judgment per node, keyed by `prompt_judge.judgment_key` -- every item
sent (the interviewer's question, its context and the topic label), the
model, the instructions and the tool schema. A cache over other questions,
other topics, another model or another prompt is STALE; a file that does not
parse into a valid judgment is UNREADABLE. Both come back with a reason the
command prints, and neither is ever used: a judgment applied to a regrouped
project would mark answers prompted by questions that never asked about them.

Tolerant on load; strict on save (a blank question or topic, an item listed
twice, or an answer that is not a boolean raises before anything is written).
Holds the interviewer's own words and topic labels only, never anything an
interviewee said, and lives under `context/`, which is git-ignored with the
rest of the node's data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from app.coach import json_cache
from app.coach import prompt_judge as judge_mod
from app.coach.json_cache import ABSENT, FRESH, STALE, UNREADABLE  # noqa: F401 -- re-exported

CACHE_FILENAME = "prompted.json"
FORMAT_VERSION = 1


@dataclass(frozen=True)
class CacheState:
    status: str
    judgment: Optional[judge_mod.Judgment] = None
    """Set only when `status == FRESH`."""
    reason: str = ""


def load(context_dir: Path, items: "Sequence[judge_mod.PromptItem]", model: str) -> CacheState:
    payload, status, reason = json_cache.read(Path(context_dir) / CACHE_FILENAME, FORMAT_VERSION,
                                              "prompted judgment")
    if payload is None:
        return CacheState(status, reason=reason)
    made_with = payload.get("model")
    if made_with != model:
        return CacheState(STALE, reason=f"it was judged by {made_with!r}, and the extract model is now {model!r}")
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
        "items": [{"question": entry.question, "earlier": list(entry.earlier), "topic": entry.topic,
                   "asked": asked} for entry, asked in judgment.answers],
    })


def _judgment(payload: dict, *, model: str) -> judge_mod.Judgment:
    raw = payload["items"]
    if not isinstance(raw, list):
        raise ValueError("items is not a list")
    answers = []
    for entry in raw:
        question, earlier, topic, asked = entry["question"], entry["earlier"], entry["topic"], entry["asked"]
        if not (isinstance(question, str) and isinstance(topic, str) and isinstance(earlier, list)
                and all(isinstance(e, str) for e in earlier)):
            raise ValueError("an item needs a string question, a list of earlier strings and a string topic")
        if not isinstance(asked, bool):
            raise ValueError("an answer is not true or false")
        answers.append((judge_mod.PromptItem(question=question, earlier=tuple(earlier), topic=topic), asked))
    return judge_mod.Judgment(model=model, key=str(payload["key"]), answers=tuple(answers))


def _check(judgment: judge_mod.Judgment, *, sent: "Optional[set]" = None) -> None:
    seen: "set" = set()
    for entry, asked in judgment.answers:
        if not entry.question.strip() or not entry.topic.strip():
            raise ValueError("an item has a blank question or topic")
        if entry in seen:
            raise ValueError(f"the item for topic {entry.topic!r} is listed twice")
        if not isinstance(asked, bool):
            raise ValueError(f"the answer for topic {entry.topic!r} is not true or false")
        if sent is not None and entry not in sent:
            raise ValueError(f"an answer for topic {entry.topic!r} is for a question never sent")
        seen.add(entry)
