"""`kb add` reads PDFs: one section per page, located by page number.

The PDFs here are built byte by byte, so the suite carries no binary fixture
and every case says exactly what is in the file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.kb import pdf, sources, written


def _pdf(pages: "list[str]", *, title: "str | None" = None, encrypt: bool = False) -> bytes:
    """A minimal valid PDF: one Helvetica text line per page."""
    objects: "list[bytes]" = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # filled in once the pages object exists
    pages_id = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for text in pages:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1")
        stream = b"BT /F1 12 Tf 72 720 Td (" + escaped + b") Tj ET"
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        kids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (pages_id, font, content)
        ))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
    objects[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    info = add(b"<< /Title (" + title.encode("latin-1") + b") >>") if title else None

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    trailer = b"<< /Size %d /Root %d 0 R" % (len(objects) + 1, catalog)
    if info:
        trailer += b" /Info %d 0 R" % info
    trailer += b" >>"
    out += b"trailer\n" + trailer + b"\nstartxref\n%d\n%%%%EOF\n" % xref_at
    data = bytes(out)
    if encrypt:
        from io import BytesIO

        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter(clone_from=PdfReader(BytesIO(data)))
        writer.encrypt(user_password="secret", algorithm="RC4-128")
        buffer = BytesIO()
        writer.write(buffer)
        data = buffer.getvalue()
    return data


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_each_page_is_a_section_located_by_its_page_number(tmp_path):
    path = _write(tmp_path, "study.pdf", _pdf(["Users export invoices weekly.", "", "Nobody reads the dashboard."]))
    document = pdf.from_pdf(path)
    assert [(s.location, s.text) for s in document.sections] == [
        ("page 1", "Users export invoices weekly."),
        ("page 3", "Nobody reads the dashboard."),
    ]
    assert document.source_type == "research"
    assert document.origin == str(path.resolve())


def test_the_title_is_the_pdfs_own_then_its_first_line(tmp_path):
    titled = _write(tmp_path, "a.pdf", _pdf(["Body text."], title="Churn study 2026"))
    untitled = _write(tmp_path, "b.pdf", _pdf(["First line here."]))
    assert pdf.from_pdf(titled).title == "Churn study 2026"
    assert pdf.from_pdf(untitled).title == "First line here."


def test_a_pdf_with_no_text_says_so_rather_than_adding_nothing(tmp_path):
    path = _write(tmp_path, "scan.pdf", _pdf(["", ""]))
    with pytest.raises(written.UnreadableSourceError, match="no text"):
        pdf.from_pdf(path)


def test_a_damaged_pdf_is_a_clean_refusal(tmp_path):
    path = _write(tmp_path, "broken.pdf", b"%PDF-1.4\nthis is not a pdf at all")
    with pytest.raises(written.UnreadableSourceError, match="broken.pdf"):
        pdf.from_pdf(path)


def test_a_password_protected_pdf_is_refused_not_guessed(tmp_path):
    path = _write(tmp_path, "locked.pdf", _pdf(["Private."], encrypt=True))
    with pytest.raises(written.UnreadableSourceError, match="password"):
        pdf.from_pdf(path)


def test_too_many_pages_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_PDF_PAGES", 2)
    path = _write(tmp_path, "long.pdf", _pdf(["a", "b", "c"]))
    with pytest.raises(written.UnreadableSourceError, match="pages"):
        pdf.from_pdf(path)


def test_kb_sources_load_a_pdf_and_a_folder_of_them(tmp_path):
    _write(tmp_path, "one.pdf", _pdf(["Alpha finding."]))
    _write(tmp_path, "two.pdf", b"%PDF-1.4 junk")
    loaded = sources.load(tmp_path)
    assert [d.title for d in loaded.documents] == ["Alpha finding."]
    assert [Path(s.path).name for s in loaded.skipped] == ["two.pdf"]
    assert ".pdf" in sources.SUPPORTED_SUFFIXES
