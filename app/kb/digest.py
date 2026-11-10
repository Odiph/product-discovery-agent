"""The coach digest: the knowledge base, summarised once, for the live coach.

`kb digest` (app/kb/digest_model.py makes the model call) turns each research
and code document into a few short points, each citing the section it came
from. They are kept in `knowledge/coach_digest.json` with the content hash of
the document they summarise, so a document is summarised again only when it
changed, and a point from an edited or removed document never reaches a
prompt.

At `start`, `coach_notes` picks the points most related to the interview (its
survey, hypotheses and brief) by keyword search, then fills the rest of a
fixed budget with the others, and the coach gets them once, in its cached
prompt. Retrieval at session start, nothing per cycle: the live latency
budget is untouched.

**Only research and code.** Interviews, conversations recorded elsewhere and
emails hold other people's words, and another customer's speech must never
reach a live prompt (GC-08). They are refused when the digest is made and
filtered again when it is read -- against the stored document's own type, so
a hand-edited digest cannot carry one in under another label.

**Research only when the operator typed it so.** A PDF, a saved page or a
`.md` without `Name:` lines is research by GUESS, and a call transcript saved
as one is speech. Guessed research is refused here and filtered again on
read, against the stored document's own `explicit_type`, like the type
filter above; `kb add --type research <path>` confirms one. A transcript
added with `--type research` is still research to this module: that is why
`kb digest` lists what it would send and sends nothing without `--yes`.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

from app.kb.document import CODE, RESEARCH, Document, Section
from app.kb.index import KeywordIndex
from app.kb.store import KnowledgeStore

DIGEST_FILENAME = "coach_digest.json"
DIGEST_SCHEMA_VERSION = 1
DIGEST_SOURCE_TYPES = (RESEARCH, CODE)
MAX_POINT_CHARS = 280
MAX_LABEL_CHARS = 120
# What reaches the prompt: about 1,000 tokens, small beside the rubric, and
# paid as a cache read on every cycle after the first.
COACH_BUDGET_CHARS = 4000
_SEARCH_LIMIT = 200
GUESSED_RESEARCH = "research typed by guess"
"""The `Plan.not_digested` key for research the operator has not confirmed."""


class DigestError(ValueError):
    pass


@dataclass(frozen=True)
class Point:
    text: str
    location: str


@dataclass(frozen=True)
class Entry:
    doc_id: str
    content_hash: str
    source_type: str
    title: str
    points: "tuple[Point, ...]"


@dataclass(frozen=True)
class CoachNote:
    """One point as the coach is shown it, with where it came from."""

    text: str
    title: str
    location: str
    source_type: str


@dataclass(frozen=True)
class Plan:
    to_summarize: "tuple[Document, ...]"
    kept: "tuple[Entry, ...]"
    dropped: "tuple[Entry, ...]"
    not_digested: "dict[str, int]"
    """Documents left out by source type, so `kb digest` can say why."""


def digest_path(knowledge_dir: Path) -> Path:
    return Path(knowledge_dir) / DIGEST_FILENAME


def plan(entries: Sequence[Entry], documents: Iterable[Document], *, damaged_ids: "frozenset[str]" = frozenset()) -> Plan:
    """`damaged_ids` are documents on disk that could not be read this time:
    their notes are kept as they are, never dropped and paid for again."""
    by_id = {entry.doc_id: entry for entry in entries}
    to_summarize: "list[Document]" = []
    kept: "list[Entry]" = []
    skipped: Counter = Counter()
    for document in documents:
        if document.source_type not in DIGEST_SOURCE_TYPES:
            skipped[document.source_type] += 1
            continue
        if not _digestible(document.source_type, document.explicit_type):
            skipped[GUESSED_RESEARCH] += 1
            continue
        entry = by_id.get(document.doc_id)
        if entry is not None and entry.content_hash == document.content_hash:
            kept.append(entry)
        else:
            to_summarize.append(document)
    kept.extend(entry for entry in entries if entry.doc_id in damaged_ids)
    kept_ids = {entry.doc_id for entry in kept}
    dropped = tuple(entry for entry in entries if entry.doc_id not in kept_ids)
    return Plan(tuple(to_summarize), tuple(kept), dropped, dict(skipped))


def _digestible(source_type: str, explicit_type: bool) -> bool:
    """Code always (a repository is typed by what the folder is); research
    only when the operator named the type."""
    return source_type == CODE or (source_type == RESEARCH and explicit_type)


def load(knowledge_dir: Path) -> "tuple[Entry, ...]":
    path = digest_path(knowledge_dir)
    if not path.is_file():
        return ()
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        return tuple(
            Entry(
                doc_id=_text(raw["doc_id"]),
                content_hash=_text(raw["content_hash"]),
                source_type=_text(raw["source_type"]),
                title=_text(raw["title"]),
                points=tuple(Point(text=_text(p["text"]), location=_text(p["location"])) for p in raw["points"]),
            )
            for raw in record["entries"]
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DigestError(f"{path.name} is damaged ({type(exc).__name__}); run `kb digest` again to rebuild it") from exc


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected text")
    return value


def label(value: str) -> str:
    """A title or location as it may appear in a prompt: one line, bounded.
    Both come from the document (a file name, a first heading), so a newline
    must not be able to start a line of its own."""
    return " ".join(value.split())[:MAX_LABEL_CHARS]


def save(knowledge_dir: Path, entries: Sequence[Entry]) -> None:
    path = digest_path(knowledge_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"schema": DIGEST_SCHEMA_VERSION, "entries": [asdict(entry) for entry in entries]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def select(entries: Sequence[Entry], query: str, *, budget_chars: int = COACH_BUDGET_CHARS) -> "tuple[CoachNote, ...]":
    """The points most related to `query` first, then the rest in digest
    order, until `budget_chars` of point text is used. Deterministic: the
    coach's cached prompt must be byte-stable for the same inputs."""
    notes = [
        CoachNote(text=" ".join(point.text.split())[:MAX_POINT_CHARS], title=label(entry.title),
                  location=label(point.location), source_type=entry.source_type)
        for entry in entries
        if entry.source_type in DIGEST_SOURCE_TYPES
        for point in entry.points
    ]
    # Each point is its own one-section document, so a hit names one point.
    as_documents = [
        Document(source_type=note.source_type, origin=f"digest:{i}", title=note.title,
                 sections=(Section(text=note.text, location=note.location),))
        for i, note in enumerate(notes)
    ]
    position = {document.doc_id: i for i, document in enumerate(as_documents)}
    hits = KeywordIndex(as_documents).search(query, limit=_SEARCH_LIMIT, per_document=1)
    ranked = [position[hit.doc_id] for hit in hits]
    ranked_set = set(ranked)
    order = ranked + [i for i in range(len(notes)) if i not in ranked_set]

    chosen: "list[CoachNote]" = []
    used = 0
    for i in order:
        # The whole line as the prompt renders it, not only the note.
        size = len(notes[i].text) + len(notes[i].title) + len(notes[i].location) + 8
        if used + size > budget_chars:
            continue
        chosen.append(notes[i])
        used += size
    return tuple(chosen)


def coach_notes(knowledge_dir: Path, query: str, *, budget_chars: int = COACH_BUDGET_CHARS) -> "tuple[tuple[CoachNote, ...], int]":
    """What the coach is shown at `start`, and how many digest entries were
    left out because their document changed, was removed, or is research typed by guess, since `kb digest`
    last ran (the caller says so). Raises `DigestError` for a damaged digest."""
    entries = load(knowledge_dir)
    if not entries:
        return (), 0
    stored, _ = KnowledgeStore(knowledge_dir).scan()
    current = {
        item.doc_id: (item.content_hash, item.document.source_type)
        for item in stored if _digestible(item.document.source_type, item.document.explicit_type)
    }
    fresh = tuple(
        entry for entry in entries
        if current.get(entry.doc_id) == (entry.content_hash, entry.source_type)
        and entry.source_type in DIGEST_SOURCE_TYPES
    )
    return select(fresh, query, budget_chars=budget_chars), len(entries) - len(fresh)
