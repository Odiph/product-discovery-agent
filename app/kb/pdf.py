"""The PDF adapter: one section per page with text, located by page number.

The only adapter that is not standard library: it reads through `pypdf`
(pinned in requirements.txt; gate 3 counts it). Text only -- no images, no
OCR, so a scanned PDF has no text and is refused with that reason rather than
added as an empty document.
"""

from __future__ import annotations

import multiprocessing
from pathlib import Path

from pypdf import PdfReader

from app.kb.document import RESEARCH, Document, Section
from app.kb.written import UnreadableSourceError

# Size bounds, like the .docx adapter's: a PDF's file size says little about
# what it unpacks to. 2,000 pages is a long book; 20 MB of text is far past it.
MAX_PDF_PAGES = 2000
MAX_PDF_TEXT_CHARS = 20_000_000
# Wall clock for one PDF's parse, in its own process. A 2,000-page report
# reads in seconds; a minute is a parser that is not coming back.
PARSE_TIMEOUT_S = 60.0
_TITLE_CHARS = 120


def from_pdf(path: Path) -> Document:
    path = Path(path)
    outcome = _parse_isolated(path)
    if outcome[0] == "refused":
        raise UnreadableSourceError(outcome[1])
    _, sections, own_title = outcome
    if not sections:
        raise UnreadableSourceError(f"{path.name} has no text to read (a scan needs OCR first)")
    first_line = sections[0].text.split("\n", 1)[0]
    return Document(
        source_type=RESEARCH,
        origin=str(path.resolve()),
        title=(own_title.strip() or first_line or path.stem)[:_TITLE_CHARS],
        sections=tuple(sections),
    )


def _parse_isolated(path: Path) -> tuple:
    """Parses in a child process, killed after `PARSE_TIMEOUT_S`. Pages and
    text are capped above, time was not, and pypdf has had infinite-loop
    bugs: one hostile PDF must cost a skip line, never a hung `kb add`.
    Spawned (the only start method on Windows), so the worker is a module-
    level name the child imports; the limits travel as arguments, read here
    at call time."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_WORKER, args=(str(path), MAX_PDF_PAGES, MAX_PDF_TEXT_CHARS, sender), daemon=True,
    )
    process.start()
    sender.close()  # the child's end: only the child holds it now, so its exit is an EOF here
    try:
        if not receiver.poll(PARSE_TIMEOUT_S):
            raise UnreadableSourceError(
                f"{path.name}: reading it took longer than {PARSE_TIMEOUT_S:g} seconds, so it was stopped"
            )
        try:
            return receiver.recv()
        except EOFError as exc:
            raise UnreadableSourceError(f"{path.name} is not a readable PDF (the reader stopped)") from exc
    finally:
        receiver.close()
        if process.is_alive():
            process.kill()
        process.join(5)


def _parse_worker(path: str, max_pages: int, max_chars: int, conn) -> None:
    """In the child: ("ok", sections, title) or ("refused", reason)."""
    try:
        conn.send(_parse(Path(path), max_pages, max_chars))
    finally:
        conn.close()


def _parse(path: Path, max_pages: int, max_chars: int) -> tuple:
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            return ("refused", f"{path.name} is password-protected; save an unlocked copy to add it")
        if len(reader.pages) > max_pages:
            return ("refused", f"{path.name} has more than {max_pages} pages")
        sections = _page_sections(path, reader, max_chars)
        own_title = (reader.metadata.title if reader.metadata else None) or ""
    except UnreadableSourceError as exc:
        return ("refused", str(exc))
    except Exception as exc:  # noqa: BLE001 -- in the child, anything is a refusal, not a crash
        # Named by type only: a parser's message can quote the file's content.
        return ("refused", f"{path.name} is not a readable PDF ({type(exc).__name__})")
    return ("ok", sections, str(own_title))


_WORKER = _parse_worker


def _page_sections(path: Path, reader: PdfReader, max_chars: int) -> "list[Section]":
    sections: "list[Section]" = []
    total = 0
    for number, page in enumerate(reader.pages, start=1):
        text = " ".join((page.extract_text() or "").split())
        if not text:
            continue
        total += len(text)
        if total > max_chars:
            raise UnreadableSourceError(f"{path.name}: its text is larger than {max_chars // 1_000_000} MB")
        sections.append(Section(text=text, location=f"page {number}"))
    return sections
