"""The PDF adapter: one section per page with text, located by page number.

The only adapter that is not standard library: it reads through `pypdf`
(pinned in requirements.txt; gate 3 counts it). Text only -- no images, no
OCR, so a scanned PDF has no text and is refused with that reason rather than
added as an empty document.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PyPdfError

from app.kb.document import RESEARCH, Document, Section
from app.kb.written import UnreadableSourceError

# Size bounds, like the .docx adapter's: a PDF's file size says little about
# what it unpacks to. 2,000 pages is a long book; 20 MB of text is far past it.
MAX_PDF_PAGES = 2000
MAX_PDF_TEXT_CHARS = 20_000_000
_TITLE_CHARS = 120


def from_pdf(path: Path) -> Document:
    path = Path(path)
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise UnreadableSourceError(f"{path.name} is password-protected; save an unlocked copy to add it")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise UnreadableSourceError(f"{path.name} has more than {MAX_PDF_PAGES} pages")
        sections = _page_sections(path, reader)
        own_title = (reader.metadata.title if reader.metadata else None) or ""
    except UnreadableSourceError:
        raise
    except (PdfReadError, PyPdfError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
        # Named by type only: a parser's message can quote the file's content.
        raise UnreadableSourceError(f"{path.name} is not a readable PDF ({type(exc).__name__})") from exc
    if not sections:
        raise UnreadableSourceError(f"{path.name} has no text to read (a scan needs OCR first)")
    first_line = sections[0].text.split("\n", 1)[0]
    return Document(
        source_type=RESEARCH,
        origin=str(path.resolve()),
        title=(own_title.strip() or first_line or path.stem)[:_TITLE_CHARS],
        sections=tuple(sections),
    )


def _page_sections(path: Path, reader: PdfReader) -> "list[Section]":
    sections: "list[Section]" = []
    total = 0
    for number, page in enumerate(reader.pages, start=1):
        text = " ".join((page.extract_text() or "").split())
        if not text:
            continue
        total += len(text)
        if total > MAX_PDF_TEXT_CHARS:
            raise UnreadableSourceError(f"{path.name}: its text is larger than {MAX_PDF_TEXT_CHARS // 1_000_000} MB")
        sections.append(Section(text=text, location=f"page {number}"))
    return sections
