"""Source adapters: each real export shape becomes cited sections (app/kb/)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.kb import sources
from app.kb.document import CODE, CONVERSATION, EMAIL, INTERVIEW, RESEARCH

VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.500
<v Sam>So when did you last do this by hand?</v>

2
00:00:05.000 --> 00:00:09.000
<v Dana>Last Friday. I rebuilt the export.</v>

3
00:00:09.000 --> 00:01:12.250
<v Dana>Took most of the afternoon.</v>
"""

SRT = """1
00:00:01,000 --> 00:00:03,000
Sam: How do you track it today?

2
00:00:03,500 --> 00:00:07,000
Dana: A spreadsheet, honestly.
"""


def _one(path, **kwargs):
    loaded = sources.load(path, **kwargs)
    assert not loaded.skipped, loaded.skipped
    assert len(loaded.documents) == 1
    return loaded.documents[0]


def test_vtt_voice_tags_become_turns_and_same_speaker_cues_merge(tmp_path):
    path = tmp_path / "call.vtt"
    path.write_text(VTT, encoding="utf-8")
    document = _one(path)
    assert document.source_type == CONVERSATION
    assert document.participants == ("Sam", "Dana")
    assert [s.speaker for s in document.sections] == ["Sam", "Dana"]
    assert document.sections[1].text == "Last Friday. I rebuilt the export. Took most of the afternoon."
    # Located by when the turn ENDED: the merged turn ends at 01:12.
    assert document.sections[1].location == "turn 2 (01:12)"


def test_srt_with_name_prefixes(tmp_path):
    path = tmp_path / "call.srt"
    path.write_text(SRT, encoding="utf-8")
    document = _one(path)
    assert [(s.speaker, s.text) for s in document.sections] == [
        ("Sam", "How do you track it today?"), ("Dana", "A spreadsheet, honestly."),
    ]


def test_a_plain_text_transcript_is_read_as_a_conversation(tmp_path):
    path = tmp_path / "otter.txt"
    path.write_text(
        "Sam 00:01: How did onboarding go?\nDana 00:05: Badly.\nIt took a week.\nSam 00:20: Why?\n",
        encoding="utf-8",
    )
    document = _one(path)
    assert document.source_type == CONVERSATION
    assert document.sections[1].text == "Badly. It took a week."
    assert document.sections[1].speaker == "Dana"


def test_prose_with_colons_is_not_mistaken_for_a_transcript(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text(
        "# Market notes\n\nPricing: unclear.\n\nThe main competitors are A, B and C, and none of them "
        "handles Hebrew.\n\nRisks: churn, onboarding.\n\nAnother long paragraph without any label at all.\n"
        "More prose here.\nAnd here.\n",
        encoding="utf-8",
    )
    document = _one(path)
    assert document.source_type == RESEARCH
    assert document.title == "Market notes"
    assert document.sections[1].location == "line 3"


def test_type_override_wins(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Just a note.\n", encoding="utf-8")
    assert _one(path, source_type=CONVERSATION).source_type == CONVERSATION


def test_an_email_keeps_the_new_text_and_drops_the_quoted_thread(tmp_path):
    path = tmp_path / "reply.eml"
    path.write_bytes(
        b"From: Dana <dana@example.com>\r\nTo: sam@example.com\r\nSubject: Re: pricing\r\n"
        b"Date: Tue, 06 Oct 2026 10:00:00 +0300\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        b"We would pay per seat.\r\n\r\nOn Mon, 5 Oct 2026, Sam wrote:\r\n> what would you pay?\r\n"
    )
    document = _one(path)
    assert document.source_type == EMAIL
    assert document.title == "Re: pricing"
    assert document.date == "2026-10-06"
    assert document.participants == ("dana@example.com", "sam@example.com")
    assert " ".join(s.text for s in document.sections) == "We would pay per seat."


def test_an_html_only_email_is_read_as_text(tmp_path):
    path = tmp_path / "html.eml"
    path.write_bytes(
        b"From: a@example.com\r\nSubject: hi\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        b"<html><style>p{}</style><body><p>Hello <b>there</b></p></body></html>"
    )
    assert [s.text for s in _one(path).sections] == ["Hello there"]


def test_an_mbox_gives_one_document_per_message(tmp_path):
    path = tmp_path / "export.mbox"
    path.write_bytes(
        b"From a@example.com Mon Oct  5 10:00:00 2026\nFrom: a@example.com\nSubject: one\n"
        b"Message-ID: <m1@x>\n\nfirst body\n\n"
        b"From b@example.com Mon Oct  5 11:00:00 2026\nFrom: b@example.com\nSubject: two\n\nsecond body\n"
    )
    loaded = sources.load(path)
    assert [d.title for d in loaded.documents] == ["one", "two"]
    assert loaded.documents[0].origin.endswith("#<m1@x>")
    # No Message-ID: identity is the message's bytes, so a re-export with the
    # messages in another order still names the same document.
    assert "#sha256-" in loaded.documents[1].origin
    assert len({d.doc_id for d in loaded.documents}) == 2


def test_docx_paragraphs(tmp_path):
    path = tmp_path / "report.docx"
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (f'<w:document xmlns:w="{ns}"><w:body>'
           '<w:p><w:r><w:t>Findings</w:t></w:r></w:p><w:p/>'
           '<w:p><w:r><w:t>Users </w:t></w:r><w:r><w:t>export weekly.</w:t></w:r></w:p>'
           '</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    document = _one(path)
    assert document.title == "Findings"
    assert [(s.location, s.text) for s in document.sections] == [
        ("paragraph 1", "Findings"), ("paragraph 2", "Users export weekly."),
    ]


def test_a_broken_docx_is_skipped_with_a_reason(tmp_path):
    path = tmp_path / "bad.docx"
    path.write_bytes(b"not a zip")
    loaded = sources.load(path)
    assert not loaded.documents and "docx" in loaded.skipped[0].reason


def test_html_skips_scripts_and_keeps_the_title(tmp_path):
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><title>Survey results</title><script>var x='secret';</script></head>"
        "<body><h1>Results</h1><p>Most respondents export weekly.</p></body></html>",
        encoding="utf-8",
    )
    document = _one(path)
    assert document.title == "Survey results"
    assert "secret" not in " ".join(s.text for s in document.sections)
    assert [s.text for s in document.sections] == ["Results", "Most respondents export weekly."]


def test_pdf_and_unknown_types_are_skipped_and_say_why(tmp_path):
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "data.xlsx").write_bytes(b"PK")
    assert "PDF" in sources.load(tmp_path / "paper.pdf").skipped[0].reason
    assert "unsupported" in sources.load(tmp_path / "data.xlsx").skipped[0].reason


def test_a_folder_is_walked_and_its_skips_reported(tmp_path):
    (tmp_path / "a.md").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("beta\n", encoding="utf-8")
    (tmp_path / "c.pdf").write_bytes(b"%PDF")
    (tmp_path / ".hidden.md").write_text("no\n", encoding="utf-8")
    loaded = sources.load(tmp_path)
    assert sorted(d.title for d in loaded.documents) == ["a", "b"]
    assert [Path(s.path).name for s in loaded.skipped] == ["c.pdf"]


def test_a_repository_is_its_prose_plus_a_summary_not_its_source(tmp_path):
    repo = tmp_path / "product"
    (repo / ".git").mkdir(parents=True)
    (repo / "README.md").write_text("# Product\n\nIt exports invoices.\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "design.md").write_text("Design notes.\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("SECRET_SOURCE_LINE = 1\n", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "x.js").write_text("x", encoding="utf-8")
    (repo / "package.json").write_text(json.dumps({"name": "product", "description": "Invoice export"}),
                                       encoding="utf-8")
    document = _one(repo)
    assert document.source_type == CODE
    text = " ".join(s.text for s in document.sections)
    assert "SECRET_SOURCE_LINE" not in text
    assert "product: Invoice export" in document.sections[0].text
    assert ".js (" not in document.sections[0].text  # node_modules is not the product
    assert "Top-level directories: docs, src." in document.sections[0].text
    assert {s.location for s in document.sections[1:]} >= {"README.md:3", "docs/design.md:1"}


def _session(root, name, segments, **meta):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "session.json").write_text(json.dumps({"started_at": "2026-09-23T17:10:00+03:00", **meta}),
                                            encoding="utf-8")
    (directory / "transcript.jsonl").write_text(
        "".join(json.dumps({"kind": "segment", "seq": i, "speaker": sp, "text": tx,
                            "audio_start_s": 0.0, "audio_end_s": end}) + "\n"
                for i, (sp, tx, end) in enumerate(segments)),
        encoding="utf-8",
    )
    return directory


def test_a_session_becomes_an_interview_with_merged_turns(tmp_path):
    directory = _session(tmp_path, "20260923T171000", [
        ("interviewer", "When did you last do it?", 4.0),
        ("interviewee", "Friday.", 6.0),
        ("interviewee", "By hand.", 75.5),
    ], participant="Noa")
    document = _one(directory)
    assert document.source_type == INTERVIEW
    assert document.title == "Interview with Noa"
    assert document.date == "2026-09-23"
    assert document.origin == "session:20260923T171000"
    assert [(s.speaker, s.text, s.location) for s in document.sections] == [
        ("interviewer", "When did you last do it?", "turn 1 (00:04)"),
        ("interviewee", "Friday. By hand.", "turn 2 (01:15)"),
    ]


def test_an_unconfirmed_in_person_session_is_not_indexed(tmp_path):
    from app.session import evidence as ev

    directory = _session(tmp_path, "20260923T180000", [("interviewer", "hi", 1.0)],
                         capture="in-person", **{ev.EVIDENCE_KEY: ev.EVIDENCE_PENDING})
    meta = json.loads((directory / "session.json").read_text(encoding="utf-8"))
    if ev.extract_refusal(meta) is None:
        # The refusal is keyed on whatever marks a session in-person; mark it
        # the way the evidence module recognises.
        raise AssertionError("fixture does not look in-person to the evidence module")
    loaded = sources.load(directory)
    assert not loaded.documents and loaded.skipped


# --- regressions from the 2026-10-21 review: each was a real input that broke --------


def _docx(path, xml):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)


def test_a_truncated_docx_is_one_skip_not_the_end_of_the_batch(tmp_path):
    _docx(tmp_path / "a.docx", "<w:document")
    (tmp_path / "b.md").write_text("still indexed\n", encoding="utf-8")
    loaded = sources.load(tmp_path)
    assert [d.title for d in loaded.documents] == ["b"]
    assert "ParseError" in loaded.skipped[0].reason


def test_a_docx_bomb_is_refused_before_it_is_inflated(tmp_path, monkeypatch):
    from app.kb import written

    monkeypatch.setattr(written, "MAX_DOCX_XML_BYTES", 1000)
    _docx(tmp_path / "bomb.docx", "<w:document>" + " " * 5000 + "</w:document>")
    assert "uncompressed" in sources.load(tmp_path / "bomb.docx").skipped[0].reason


def test_a_text_box_paragraph_is_not_indexed_twice_and_tabs_separate_words(tmp_path):
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    _docx(tmp_path / "box.docx",
          f'<w:document xmlns:w="{ns}"><w:body><w:p><w:r><w:t>Outer</w:t><w:tab/><w:t>text</w:t></w:r>'
          '<w:r><w:txbxContent><w:p><w:r><w:t>boxed</w:t></w:r></w:p></w:txbxContent></w:r></w:p>'
          '</w:body></w:document>')
    assert [s.text for s in _one(tmp_path / "box.docx").sections] == ["Outer text boxed"]


def test_a_bottom_posted_reply_keeps_its_new_text(tmp_path):
    path = tmp_path / "bottom.eml"
    path.write_bytes(b"From: a@example.com\r\nSubject: s\r\n\r\nOn Tue, Dana wrote:\r\n> old\r\n\r\nMy actual answer.\r\n")
    assert [s.text for s in _one(path).sections] == ["My actual answer."]


def test_an_mbox_indexes_one_message_once_however_it_is_labelled(tmp_path):
    path = tmp_path / "dupes.mbox"
    message = b"From: a@example.com\nSubject: same\nMessage-ID: <dup@x>\n\nbody\n\n"
    path.write_bytes(b"From a@example.com Mon Oct  5 10:00:00 2026\n" + message
                     + b"From a@example.com Mon Oct  5 10:00:00 2026\n" + message)
    assert len(sources.load(path).documents) == 1


def test_html_with_an_unclosed_head_keeps_its_body(tmp_path):
    path = tmp_path / "saved.html"
    path.write_text("<html><head><title>T</title><body><p>hello</p>", encoding="utf-8")
    document = _one(path)
    assert (document.title, [s.text for s in document.sections]) == ("T", ["hello"])


def test_a_cue_with_two_voices_is_two_turns(tmp_path):
    path = tmp_path / "teams.vtt"
    path.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<v Alice>Hi</v><v Bob>Hello back</v>\n",
                    encoding="utf-8")
    assert [(s.speaker, s.text) for s in _one(path).sections] == [("Alice", "Hi"), ("Bob", "Hello back")]


def test_a_wrapped_line_with_a_colon_is_not_a_speaker(tmp_path):
    path = tmp_path / "call.txt"
    path.write_text("Sam: Is it expensive?\nDana: Very. It really is: expensive\nIt really is: expensive, honestly\n"
                    "Sam: How much?\nDana: Too much.\n", encoding="utf-8")
    document = _one(path, source_type=CONVERSATION)
    assert document.participants == ("Sam", "Dana")


def test_a_link_out_of_a_repository_is_not_followed(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("PRIVATE_OUTSIDE_TEXT\n", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    try:
        (repo / "NOTES.md").symlink_to(outside)
    except OSError:
        import pytest
        pytest.skip("this machine cannot create symlinks without privilege")
    document = _one(repo)
    assert "PRIVATE_OUTSIDE_TEXT" not in " ".join(s.text for s in document.sections)


def test_a_corrupt_session_is_skipped_and_the_rest_still_load(tmp_path):
    good = _session(tmp_path / "sessions", "20260923T171000", [("interviewee", "fine", 1.0)])
    bad = tmp_path / "sessions" / "20260923T180000"
    bad.mkdir()
    (bad / "session.json").write_text("{", encoding="utf-8")
    loaded = sources.load(tmp_path / "sessions")
    assert [d.origin for d in loaded.documents] == [f"session:{good.name}"]
    assert loaded.skipped and "secret" not in loaded.skipped[0].reason
