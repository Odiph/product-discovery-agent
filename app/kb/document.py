"""The one shape every source adapter produces.

A `Document` is a list of `Section`s, each carrying the human-readable
location a citation points at ("turn 12 (03:21)", "line 40", "message 3").
Sections are what retrieval chunks; the location is what a hit cites, so a
reader can always walk from a search result back to the exact place.

Source types are kept apart on purpose. An interview, a conversation recorded
elsewhere, an email, a research note and a README are different kinds of
knowing, and `standing` counts interview evidence only: nothing here may ever
become a vote for or against a hypothesis.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Optional

INTERVIEW = "interview"
"""A session recorded by this tool."""
CONVERSATION = "conversation"
"""A conversation recorded elsewhere: a Zoom/Meet/Otter export, a pasted transcript."""
EMAIL = "email"
RESEARCH = "research"
"""Notes, articles, reports, saved web pages."""
CODE = "code"
"""A repository: its READMEs and docs, and a summary of what is built."""

SOURCE_TYPES = (INTERVIEW, CONVERSATION, EMAIL, RESEARCH, CODE)
# Types whose sections carry speaker turns. The mirror (B2) runs only on these.
SPOKEN_TYPES = frozenset({INTERVIEW, CONVERSATION})

DOC_ID_LENGTH = 12
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Section:
    text: str
    location: str
    speaker: Optional[str] = None


@dataclass(frozen=True)
class Document:
    source_type: str
    origin: str
    """Where it came from: an absolute path, `path#message-3` inside an mbox,
    or `session:<id>` for this tool's own interviews. Identity is
    (source_type, origin), so re-adding the same file replaces it."""
    title: str
    sections: "tuple[Section, ...]"
    date: Optional[str] = None
    participants: "tuple[str, ...]" = ()

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unknown source type {self.source_type!r}; expected one of {SOURCE_TYPES}")

    @property
    def doc_id(self) -> str:
        return doc_id_for(self.source_type, self.origin)

    @property
    def has_speakers(self) -> bool:
        return any(section.speaker for section in self.sections)

    @property
    def content_hash(self) -> str:
        """Over everything an adapter read. Not the origin: identity already
        is the origin, and the hash answers "did the content change"."""
        payload = {
            "title": self.title,
            "date": self.date,
            "participants": list(self.participants),
            "sections": [asdict(section) for section in self.sections],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def text_chars(self) -> int:
        return sum(len(section.text) for section in self.sections)

    def to_record(self) -> "dict[str, Any]":
        return {
            "schema": SCHEMA_VERSION,
            "doc_id": self.doc_id,
            "content_hash": self.content_hash,
            "source_type": self.source_type,
            "origin": self.origin,
            "title": self.title,
            "date": self.date,
            "participants": list(self.participants),
            "sections": [asdict(section) for section in self.sections],
        }

    @classmethod
    def from_record(cls, record: "dict[str, Any]") -> "Document":
        return cls(
            source_type=record["source_type"],
            origin=record["origin"],
            title=record["title"],
            date=record.get("date"),
            participants=tuple(record.get("participants") or ()),
            sections=tuple(
                Section(text=s["text"], location=s["location"], speaker=s.get("speaker"))
                for s in record["sections"]
            ),
        )


def doc_id_for(source_type: str, origin: str) -> str:
    digest = hashlib.sha256(f"{source_type}\0{origin}".encode("utf-8")).hexdigest()
    return digest[:DOC_ID_LENGTH]
