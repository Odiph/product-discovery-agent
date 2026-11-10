"""What `kb add` refuses to store, and what it records about how it typed a file.

Every secret below is assembled at runtime from pieces, so no key-shaped
literal sits in the source for a scanner (or a reader) to trip on. Each
refusal is checked for the reason AND for the secret's absence from it: the
skip line is printed, and a reason that quoted the key would leak it there.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from app.kb import code, pdf, sources, written
from app.kb.document import CODE, EMAIL, RESEARCH, Document, Section
from app.kb.store import KnowledgeStore

_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
_ANTHROPIC = "sk-ant-" + "api03-" + "x" * 40
_ANTHROPIC_SHORT = "sk-ant-" + "abc123"
_OPENAI = "sk-" + "proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
_GITHUB = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
_GITHUB_PAT = "github_pat_" + "11ABCDEFG0" + "a" * 30
_SLACK = "xoxb-" + "123456789012-abcdefABCDEF"
_PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"
_ASSIGNED = "api_key = " + "Zx81kq2LmP0aVv7TtR3s"
_ASSIGNED_ENV = "OPENAI_API_KEY=" + "Zx81kq2LmP0aVv7TtR3s"
_ASSIGNED_PASSWORD = 'password: "' + "hunter2hunter2hunter2" + '"'

SECRETS = [_AWS, _ANTHROPIC, _ANTHROPIC_SHORT, _OPENAI, _GITHUB, _GITHUB_PAT, _SLACK, _PEM,
           _ASSIGNED, _ASSIGNED_ENV, _ASSIGNED_PASSWORD]


# --- 1a: refused by name ---------------------------------------------------------


@pytest.mark.parametrize("name", [
    "secrets.txt", "my-passwords.md", "api_key.txt", "API-KEYS.md", "aws-credentials.md",
    "github_token.txt", "id_rsa.txt", "id_ed25519.md", "server.pem.txt", "tls.key.md", "cert.p12.txt",
    ".env.md",
])
def test_a_file_named_like_a_secret_is_refused_unread(tmp_path, name):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / name).write_text("Nothing secret in here at all.\n", encoding="utf-8")
    (folder / "keep.md").write_text("Teams export every Friday.\n", encoding="utf-8")
    loaded = sources.load(folder)
    assert [Path(d.origin).name for d in loaded.documents] == ["keep.md"]
    if name.startswith("."):
        return  # hidden files are never walked at all
    assert [Path(s.path).name for s in loaded.skipped] == [name]
    assert "secret" in loaded.skipped[0].reason
    # Given by hand, too: the name is the refusal, not the walk.
    direct = sources.load(folder / name)
    assert not direct.documents and direct.skipped


@pytest.mark.parametrize("name", ["tokenization-study.md", "passport-study.md", "keynote.md", "secretary-interviews.md"])
def test_a_name_that_merely_contains_the_word_is_read(tmp_path, name):
    (tmp_path / name).write_text("Research text.\n", encoding="utf-8")
    loaded = sources.load(tmp_path / name)
    assert loaded.documents and not loaded.skipped


# --- 1b: refused by content -------------------------------------------------------


@pytest.mark.parametrize("secret", SECRETS)
def test_a_document_holding_a_secret_is_refused_and_the_reason_does_not_quote_it(tmp_path, secret):
    path = tmp_path / "runbook.md"
    path.write_text(f"# Deploy\n\nFirst log in.\n\nThen use {secret} to push.\n", encoding="utf-8")
    loaded = sources.load(path)
    assert loaded.documents == ()
    (skip,) = loaded.skipped
    assert "secret" in skip.reason and "line 5" in skip.reason
    assert secret not in skip.reason
    for piece in secret.replace("=", " ").replace('"', " ").replace(":", " ").split():
        if len(piece) >= 8:
            assert piece not in skip.reason


@pytest.mark.parametrize("benign", [
    "Password: we reset it every month.",
    "The token economy came up twice.",
    "They use sk-learn for the model.",
    "Our api key rotation is manual and painful.",
    "secret = the onboarding call",
])
def test_ordinary_prose_about_secrets_is_not_refused(tmp_path, benign):
    path = tmp_path / "notes.md"
    path.write_text(f"# Notes\n\n{benign}\n", encoding="utf-8")
    loaded = sources.load(path)
    assert len(loaded.documents) == 1 and not loaded.skipped


def test_a_secret_in_an_email_is_never_stored(tmp_path):
    mail = tmp_path / "m.eml"
    mail.write_text(f"From: a@b.c\nSubject: access\n\nHere is the key: {_AWS}\n", encoding="utf-8")
    loaded = sources.load(mail)
    assert loaded.documents == () and _AWS not in loaded.skipped[0].reason


def test_one_secret_in_an_mbox_refuses_that_message_only(tmp_path):
    box = tmp_path / "export.mbox"
    box.write_text(
        "From a@b.c Mon Oct  5 10:00:00 2026\nMessage-ID: <1@x>\nSubject: one\n\nPlain words.\n\n"
        f"From a@b.c Mon Oct  5 11:00:00 2026\nMessage-ID: <2@x>\nSubject: two\n\nkey {_GITHUB}\n\n",
        encoding="utf-8",
    )
    loaded = sources.load(box)
    assert [d.title for d in loaded.documents] == ["one"]
    assert len(loaded.skipped) == 1 and "<2@x>" in loaded.skipped[0].path
    assert _GITHUB not in loaded.skipped[0].reason


def test_a_secret_in_a_repository_doc_drops_that_file_not_the_repository(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "r"\n', encoding="utf-8")
    (repo / "README.md").write_text("# R\n\nA billing CLI.\n", encoding="utf-8")
    (repo / "docs" / "runbook.md").write_text(f"Deploy with {_OPENAI}.\n", encoding="utf-8")
    (repo / "docs" / "secrets.md").write_text("Nothing here.\n", encoding="utf-8")
    loaded = sources.load(repo)
    (document,) = loaded.documents
    assert document.source_type == CODE
    blob = json.dumps(document.to_record())
    assert "billing CLI" in blob and _OPENAI not in blob and "secrets.md" not in blob
    assert sorted(Path(s.path).name for s in loaded.skipped) == ["runbook.md", "secrets.md"]
    assert all(_OPENAI not in s.reason for s in loaded.skipped)


# --- 2: typed by the operator, or by guess ----------------------------------------


def test_the_type_is_recorded_as_guessed_or_given(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Notes\n\nTeams export every Friday.\n", encoding="utf-8")
    (guessed,) = sources.load(path).documents
    (given,) = sources.load(path, source_type=RESEARCH).documents
    assert guessed.source_type == given.source_type == RESEARCH
    assert guessed.explicit_type is False and given.explicit_type is True
    # Identity is type + origin, so confirming overwrites the same document.
    assert guessed.doc_id == given.doc_id


def test_a_type_given_that_the_file_cannot_take_is_not_recorded_as_given(tmp_path):
    mail = tmp_path / "m.eml"
    mail.write_text("From: a@b.c\nSubject: hi\n\nWords.\n", encoding="utf-8")
    (document,) = sources.load(mail, source_type=RESEARCH).documents
    assert document.source_type == EMAIL and document.explicit_type is False


def test_confirming_a_guessed_document_flips_it_in_place(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Notes\n\nTeams export every Friday.\n", encoding="utf-8")
    store = KnowledgeStore(tmp_path / "knowledge")
    (guessed,) = sources.load(path).documents
    assert store.put(guessed) == "added"
    (given,) = sources.load(path, source_type=RESEARCH).documents
    assert store.put(given) == "updated"
    (stored,) = store.all()
    assert stored.document.explicit_type is True
    # Re-adding the folder by guess later does not silently un-confirm it.
    assert store.put(guessed) == "unchanged"
    assert store.all()[0].document.explicit_type is True


def test_a_document_on_disk_from_before_the_field_counts_as_guessed():
    record = Document(source_type=RESEARCH, origin="/n.md", title="N",
                      sections=(Section(text="x", location="line 1"),), explicit_type=True).to_record()
    del record["explicit_type"]
    assert Document.from_record(record).explicit_type is False


# --- 3: an NTFS junction is not followed out of the root --------------------------


def _junction(link: Path, target: Path) -> None:
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                            capture_output=True, text=True)
    if result.returncode != 0 or not link.exists():
        pytest.skip(f"cannot create a junction here: {result.stderr.strip() or result.stdout.strip()}")


@pytest.fixture
def junction(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.md").write_text("Private words outside the root.\n", encoding="utf-8")
    made: "list[Path]" = []

    def make(link: Path) -> Path:
        link.parent.mkdir(parents=True, exist_ok=True)
        _junction(link, outside)
        made.append(link)
        return link

    yield make
    for link in made:
        subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)


def test_a_folder_walk_does_not_follow_a_junction(tmp_path, junction):
    root = tmp_path / "root"
    root.mkdir()
    (root / "mine.md").write_text("Mine.\n", encoding="utf-8")
    junction(root / "linked")
    loaded = sources.load(root)
    assert [Path(d.origin).name for d in loaded.documents] == ["mine.md"]
    assert "Private words" not in json.dumps([d.to_record() for d in loaded.documents])


def test_a_repository_walk_does_not_follow_a_junction(tmp_path, junction):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "r"\n', encoding="utf-8")
    (repo / "README.md").write_text("# R\n\nA CLI.\n", encoding="utf-8")
    junction(repo / "docs")
    junction(repo / "pkg" / "vendored")
    document = code.from_repository(repo)
    assert "Private words" not in json.dumps(document.to_record())
    # The tree summary counts files: one .md, the README -- not the one outside.
    assert ".md (1)" in document.sections[0].text


# --- 6: a PDF that never finishes parsing ------------------------------------------


def hang_forever(*_args) -> None:
    """Stands in for a pypdf infinite loop. Module level: the spawned child
    imports it by name."""
    while True:
        time.sleep(1)


def test_a_pdf_that_parses_forever_is_a_skip_not_a_hang(tmp_path, monkeypatch):
    path = tmp_path / "loop.pdf"
    path.write_bytes(b"%PDF-1.4 whatever")
    monkeypatch.setattr(pdf, "_WORKER", hang_forever)
    monkeypatch.setattr(pdf, "PARSE_TIMEOUT_S", 3.0)
    started = time.monotonic()
    loaded = sources.load(path)
    assert time.monotonic() - started < 30
    assert loaded.documents == ()
    assert "loop.pdf" in loaded.skipped[0].reason and "seconds" in loaded.skipped[0].reason


# --- 7: titles are bounded at ingestion --------------------------------------------


def test_an_email_subject_and_an_html_title_are_capped(tmp_path):
    mail = tmp_path / "m.eml"
    mail.write_text("From: a@b.c\nSubject: " + "s" * 5000 + "\n\nWords.\n", encoding="utf-8")
    page = tmp_path / "p.html"
    page.write_text("<title>" + "t" * 5000 + "</title><body><p>Words.</p></body>", encoding="utf-8")
    assert len(written.from_eml(mail, mail.read_bytes()).title) == written.MAX_TITLE_CHARS == 120
    assert len(written.from_html(page, page.read_text(encoding="utf-8")).title) == 120
