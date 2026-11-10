"""Turns a path into documents: picks the adapter by what the path is.

A session directory is an interview; a repository is code; any other
directory is walked for the file types below. A file's type comes from its
extension, except that a `.txt`/`.md` made of `Name: text` lines is read as a
conversation -- and `--type` overrides the guess either way.
"""

from __future__ import annotations

import mailbox
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.kb import code, pdf, spoken, written
from app.kb.document import CODE, CONVERSATION, EMAIL, INTERVIEW, RESEARCH, Document
from app.session.evidence import EvidenceStateError
from app.session.reader import MalformedRecordError

TEXT_SUFFIXES = frozenset({".txt", ".md", ".markdown", ".rst"})
SUBTITLE_SUFFIXES = frozenset({".vtt", ".srt"})
HTML_SUFFIXES = frozenset({".html", ".htm"})
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | SUBTITLE_SUFFIXES | HTML_SUFFIXES | {".docx", ".pdf", ".eml", ".mbox"}
MAX_FILE_BYTES = 25_000_000
# Everything one damaged file can raise. Caught PER FILE, so one bad export
# is a line in the report, never the end of a batch.
_UNREADABLE = (
    written.UnreadableSourceError, spoken.NotASessionError, EvidenceStateError, MalformedRecordError,
    mailbox.Error, UnicodeError, ValueError, OSError,
)
_WALK_SKIPPED_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__"})

@dataclass(frozen=True)
class Skipped:
    path: str
    reason: str


@dataclass(frozen=True)
class Loaded:
    documents: "tuple[Document, ...]"
    skipped: "tuple[Skipped, ...]"


def load(path: Path, *, source_type: Optional[str] = None) -> Loaded:
    path = Path(path)
    if not path.exists():
        return Loaded((), (Skipped(str(path), "no such file or directory"),))
    if path.is_dir():
        return _load_directory(path, source_type)
    try:
        return Loaded(tuple(_load_file(path, source_type)), ())
    except _UNREADABLE as exc:
        return Loaded((), (Skipped(str(path), _reason(exc)),))


def _load_directory(path: Path, source_type: Optional[str]) -> Loaded:
    if source_type in (None, INTERVIEW) and spoken.is_session_dir(path):
        try:
            return Loaded((spoken.from_session(path),), ())
        except _UNREADABLE as exc:
            return Loaded((), (Skipped(str(path), _reason(exc)),))
    if source_type == CODE or (source_type is None and code.is_repository(path)):
        return Loaded((code.from_repository(path),), ())
    documents: "list[Document]" = []
    skipped: "list[Skipped]" = []
    for child in sorted(path.iterdir()):
        if child.is_symlink() or child.name.startswith(".") or child.name in _WALK_SKIPPED_DIRS:
            continue
        if child.is_dir() or child.suffix.lower() in SUPPORTED_SUFFIXES:
            loaded = load(child, source_type=source_type)
            documents.extend(loaded.documents)
            skipped.extend(loaded.skipped)
    return Loaded(tuple(documents), tuple(skipped))


def _load_file(path: Path, source_type: Optional[str]) -> "list[Document]":
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise written.UnreadableSourceError(
            f"unsupported file type {suffix or '(none)'}; supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    if path.stat().st_size > MAX_FILE_BYTES:
        raise written.UnreadableSourceError(f"larger than {MAX_FILE_BYTES // 1_000_000} MB")
    if suffix == ".mbox":
        return written.from_mbox(path)
    if suffix == ".eml":
        return [written.from_eml(path, path.read_bytes())]
    if suffix == ".docx":
        return [_retyped(written.from_docx(path), source_type)]
    if suffix == ".pdf":
        return [_retyped(pdf.from_pdf(path), source_type)]
    text = path.read_text(encoding="utf-8-sig")
    if suffix in SUBTITLE_SUFFIXES:
        return [spoken.from_subtitles(path, text)]
    if suffix in HTML_SUFFIXES:
        return [_retyped(written.from_html(path, text), source_type)]
    if source_type == CONVERSATION or (source_type is None and spoken.looks_like_speaker_transcript(text)):
        return [spoken.from_speaker_text(path, text)]
    return [written.from_text(path, text, source_type=source_type if source_type in (RESEARCH, CODE, EMAIL) else RESEARCH)]


def _reason(exc: BaseException) -> str:
    # Our own refusals are written for the operator. Anything else is named
    # by its type: a parser's message can quote the file's content.
    if isinstance(exc, (written.UnreadableSourceError, spoken.NotASessionError, EvidenceStateError, OSError)):
        return str(exc)
    return f"could not be read ({type(exc).__name__})"


def _retyped(document: Document, source_type: Optional[str]) -> Document:
    if source_type in (None, document.source_type) or source_type in (INTERVIEW, CONVERSATION):
        return document
    return Document(
        source_type=source_type, origin=document.origin, title=document.title,
        sections=document.sections, date=document.date, participants=document.participants,
    )
