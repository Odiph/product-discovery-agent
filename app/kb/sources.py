"""Turns a path into documents: picks the adapter by what the path is.

A session directory is an interview; a repository is code; any other
directory is walked for the file types below. A file's type comes from its
extension, except that a `.txt`/`.md` made of `Name: text` lines is read as a
conversation -- and `--type` overrides the guess either way. Each document
records which: a guessed research type keeps its text off MCP and out of the
digest (app/kb/document.py `explicit_type`).

Nothing holding a credential is stored (app/kb/secret_scan.py), and a walk
never leaves the folder it was given -- not by a symlink, not by a junction.
"""

from __future__ import annotations

import mailbox
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from app.kb import code, pdf, secret_scan, spoken, written
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
        return _load_directory(path, source_type, root=path.resolve())
    return _load_one_file(path, source_type)


def _load_one_file(path: Path, source_type: Optional[str]) -> Loaded:
    refusal = secret_scan.name_refusal(path)
    if refusal:
        return Loaded((), (Skipped(str(path), refusal),))
    try:
        return _screened(_load_file(path, source_type), source_type)
    except _UNREADABLE as exc:
        return Loaded((), (Skipped(str(path), _reason(exc)),))


def _load_directory(path: Path, source_type: Optional[str], *, root: Path) -> Loaded:
    if source_type in (None, INTERVIEW) and spoken.is_session_dir(path):
        try:
            return _screened([spoken.from_session(path)], source_type)
        except _UNREADABLE as exc:
            return Loaded((), (Skipped(str(path), _reason(exc)),))
    if source_type == CODE or (source_type is None and code.is_repository(path)):
        document, refused = code.read_repository(path)
        screened = _screened([document], source_type)
        return Loaded(screened.documents, tuple(Skipped(p, r) for p, r in refused) + screened.skipped)
    documents: "list[Document]" = []
    skipped: "list[Skipped]" = []
    for child in sorted(path.iterdir()):
        if child.name.startswith(".") or child.name in _WALK_SKIPPED_DIRS or not _inside(root, child):
            continue
        if child.is_dir() or child.suffix.lower() in SUPPORTED_SUFFIXES:
            refusal = secret_scan.name_refusal(child)
            if refusal:
                skipped.append(Skipped(str(child), refusal))
                continue
            loaded = _load_directory(child, source_type, root=root) if child.is_dir() else _load_one_file(child, source_type)
            documents.extend(loaded.documents)
            skipped.extend(loaded.skipped)
    return Loaded(tuple(documents), tuple(skipped))


def _inside(root: Path, child: Path) -> bool:
    """`is_symlink()` is False for an NTFS junction (Python 3.12), so a
    junction was followed straight out of the folder being added. Both link
    kinds are skipped, and whatever is left must still resolve inside the
    root: a link of a kind not named here is caught by where it lands."""
    if child.is_symlink() or child.is_junction():
        return False
    try:
        return child.resolve().is_relative_to(root)
    except OSError:
        return False


def _screened(documents: "list[Document]", source_type: Optional[str]) -> Loaded:
    """The last step before a document can be stored: refuse any holding a
    credential, and record whether its type is the one the operator named."""
    kept: "list[Document]" = []
    skipped: "list[Skipped]" = []
    for document in documents:
        refusal = secret_scan.document_refusal(document)
        if refusal:
            skipped.append(Skipped(document.origin, refusal))
            continue
        if source_type is not None and document.source_type == source_type:
            document = replace(document, explicit_type=True)
        kept.append(document)
    return Loaded(tuple(kept), tuple(skipped))


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
