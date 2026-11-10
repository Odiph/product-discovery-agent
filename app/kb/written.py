"""Adapters for written sources: plain text and Markdown, saved web pages,
Word documents, and email (`.eml`, `.mbox`). Standard library only.

Paragraphs are the sections, located by the line they start on (or the
paragraph ordinal for formats without lines), so a citation lands on the
passage rather than on the file.
"""

from __future__ import annotations

import email
import hashlib
import email.policy
import mailbox
import re
import zipfile
import zlib
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from xml.etree import ElementTree

from app.kb.document import EMAIL, RESEARCH, Document, Section

MAX_DOCX_XML_BYTES = 50_000_000
# Every title is cut here, at ingestion, as the PDF adapter's is: a subject
# line or a `<title>` is the sender's or the page's text, of any length.
MAX_TITLE_CHARS = 120
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_SKIPPED_HTML = frozenset({"script", "style", "noscript", "svg", "head", "template"})
_BLOCK_HTML = frozenset({
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "header", "footer",
})
# Quoted history in a reply ("On Tue, Dana wrote:" and every `>` line below
# it) is the PREVIOUS message, already indexed on its own when the thread is
# in the export. Keeping it would make every reply match its whole thread.
_REPLY_HEADER = re.compile(r"^(On .{4,200} wrote:|.{0,80}כתב/ה:|.{0,80}כתב:)\s*$")


class UnreadableSourceError(ValueError):
    pass


def from_text(path: Path, text: str, *, source_type: str = RESEARCH) -> Document:
    return Document(
        source_type=source_type,
        origin=str(Path(path).resolve()),
        title=(_markdown_title(text) or Path(path).stem)[:MAX_TITLE_CHARS],
        sections=tuple(_paragraphs(text)),
    )


def from_html(path: Path, text: str) -> Document:
    parser = _TextExtractor()
    parser.feed(text)
    parser.close()
    body = "\n".join(parser.lines)
    return Document(
        source_type=RESEARCH,
        origin=str(Path(path).resolve()),
        title=((parser.title or "").strip() or Path(path).stem)[:MAX_TITLE_CHARS],
        sections=tuple(_numbered_paragraphs(body.split("\n\n"), "paragraph")),
    )


def from_docx(path: Path) -> Document:
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            # The compressed size says nothing: a 290 KB file can hold 300 MB.
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise UnreadableSourceError(
                    f"{path.name}: its text is larger than {MAX_DOCX_XML_BYTES // 1_000_000} MB uncompressed"
                )
            xml = archive.read(info)
        root = ElementTree.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError, zlib.error, ElementTree.ParseError) as exc:
        raise UnreadableSourceError(f"{path.name} is not a readable .docx ({type(exc).__name__})") from exc
    paragraphs = list(_docx_paragraphs(root))
    return Document(
        source_type=RESEARCH,
        origin=str(Path(path).resolve()),
        title=next((p for p in paragraphs if p), Path(path).stem)[:MAX_TITLE_CHARS],
        sections=tuple(_numbered_paragraphs(paragraphs, "paragraph")),
    )


def _docx_paragraphs(element) -> Iterable[str]:
    """Outermost paragraphs only: a text box's paragraph sits INSIDE another
    one, whose text already includes it. Tabs and breaks become spaces, or
    the words either side of them run together."""
    for child in element:
        if child.tag == f"{_WORD_NS}p":
            pieces = []
            for node in child.iter():
                if node.tag == f"{_WORD_NS}p" and node is not child:
                    pieces.append(" ")  # a text box's paragraph is its own words
                elif node.tag == f"{_WORD_NS}t":
                    pieces.append(node.text or "")
                elif node.tag in (f"{_WORD_NS}tab", f"{_WORD_NS}br", f"{_WORD_NS}cr"):
                    pieces.append(" ")
            yield "".join(pieces).strip()
        else:
            yield from _docx_paragraphs(child)


def from_eml(path: Path, raw: bytes) -> Document:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    return _email_document(message, origin=str(Path(path).resolve()), fallback_title=Path(path).stem)


def from_mbox(path: Path) -> "list[Document]":
    box = mailbox.mbox(str(path), factory=None, create=False)
    documents = []
    seen: "set[str]" = set()
    try:
        for index, raw_message in enumerate(box, start=1):
            message = email.message_from_bytes(raw_message.as_bytes(), policy=email.policy.default)
            raw = raw_message.as_bytes()
            # Identity must survive a re-export: the Message-ID, or else the
            # message's own bytes -- never its position in the file. The same
            # message under two labels is indexed once.
            key = (message.get("Message-ID") or "").strip() or "sha256-" + hashlib.sha256(raw).hexdigest()[:16]
            if key in seen:
                continue
            seen.add(key)
            documents.append(_email_document(
                message,
                origin=f"{Path(path).resolve()}#{key}",
                fallback_title=f"{Path(path).stem} message {index}",
            ))
    finally:
        box.close()
    return documents


def _email_document(message: EmailMessage, *, origin: str, fallback_title: str) -> Document:
    body = _email_body(message)
    people = []
    for _, address in getaddresses(
        [str(v) for header in ("From", "To", "Cc") for v in message.get_all(header, [])]
    ):
        if address and address not in people:
            people.append(address)
    return Document(
        source_type=EMAIL,
        origin=origin,
        title=(str(message.get("Subject") or "").strip() or fallback_title)[:MAX_TITLE_CHARS],
        date=_email_date(message),
        participants=tuple(people),
        sections=tuple(_paragraphs(_strip_quoted_history(body))),
    )


def _email_body(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, ValueError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    if part.get_content_subtype() == "html":
        parser = _TextExtractor()
        parser.feed(content)
        parser.close()
        return "\n".join(parser.lines)
    return content


def _email_date(message: EmailMessage) -> Optional[str]:
    value = message.get("Date")
    if not value:
        return None
    try:
        return parsedate_to_datetime(str(value)).date().isoformat()
    except (TypeError, ValueError):
        return None


def _strip_quoted_history(body: str) -> str:
    """Drops the quoted lines and their "On ... wrote:" header, and keeps
    everything else: a bottom-posted or inline reply has its new text AFTER
    the quote."""
    kept = []
    for line in body.replace("\r\n", "\n").split("\n"):
        if _REPLY_HEADER.match(line.strip()) or line.lstrip().startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept)


def _markdown_title(text: str) -> Optional[str]:
    for line in text.splitlines()[:40]:
        if line.startswith("# "):
            return line[2:].strip() or None
    return None


def _paragraphs(text: str) -> Iterable[Section]:
    """Blank-line-separated paragraphs, each located by its first line."""
    current: "list[str]" = []
    start = 0
    for number, line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        if line.strip():
            if not current:
                start = number
            current.append(line.strip())
        elif current:
            yield Section(text=" ".join(current), location=f"line {start}")
            current = []
    if current:
        yield Section(text=" ".join(current), location=f"line {start}")


def _numbered_paragraphs(paragraphs: Iterable[str], noun: str) -> Iterable[Section]:
    number = 0
    for paragraph in paragraphs:
        cleaned = " ".join(paragraph.split())
        if cleaned:
            number += 1
            yield Section(text=cleaned, location=f"{noun} {number}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: "list[str]" = []
        self.title: Optional[str] = None
        self._skipping: "list[str]" = []
        self._in_title = False
        self._buffer: "list[str]" = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "title":
            self._in_title = True
        elif tag == "body":
            # HTML lets `</head>` (and a stray `<svg>`'s close) be omitted;
            # the body starting is the one reliable end of everything skipped.
            self._skipping = []
        elif tag in _SKIPPED_HTML:
            self._skipping.append(tag)
        elif tag in _BLOCK_HTML:
            self._flush()

    def handle_endtag(self, tag) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in _SKIPPED_HTML:
            if tag in self._skipping:
                del self._skipping[len(self._skipping) - 1 - self._skipping[::-1].index(tag):]
        elif tag in _BLOCK_HTML:
            self._flush()

    def handle_data(self, data) -> None:
        if self._in_title:
            self.title = (self.title or "") + data
        elif not self._skipping:
            self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = " ".join("".join(self._buffer).split())
        self._buffer = []
        if text:
            self.lines.append(text)
            self.lines.append("")
