"""`python -m app forget <session>`: erasing one interview and everything
derived from it, and nothing else.

Every test builds TWO interviews and erases one, because the failure that
matters is not "forget missed a file" -- it is "forget took a second person's
interview with it". The other session's files are compared byte for byte.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import main as main_mod
from app import projects as projects_mod
from app.coach import corpus_store
from app.coach.corpus import Fact
from app.kb import digest as kb_digest
from app.kb.document import INTERVIEW, RESEARCH, Document, Section
from app.kb.store import KnowledgeStore
from app.projects import KNOWLEDGE_DIR_NAME

GONE = "20261101T100000"
KEPT = "20261102T100000"
# Text that must never be printed: it stands for the customer's own words.
SPOKEN = "we export everything to a spreadsheet every friday"
CLAIM = "they rebuild the report by hand weekly"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(projects_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(tmp_path / "context"))
    return tmp_path


def _session(sessions_root: Path, session_id: str, *, room_audio: bool = False) -> Path:
    session_dir = sessions_root / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "session.json").write_text(json.dumps({"started_at": "2026-11-01T10:00:00"}), encoding="utf-8")
    (session_dir / "transcript.jsonl").write_text(
        json.dumps({"kind": "segment", "seq": 1, "speaker": "interviewee", "text": SPOKEN}) + "\n",
        encoding="utf-8",
    )
    if room_audio:
        (session_dir / "room.wav").write_bytes(b"RIFF" + b"\x00" * 64)
    return session_dir


def _fact(session_id: str, fact_id: str) -> Fact:
    return Fact(id=fact_id, session_id=session_id, seqs=(1,), claim=CLAIM,
                provenance="evidence", quoted_text=SPOKEN)


def _rows(context_dir: Path, filename: str, *session_ids: str) -> None:
    rows = [{"session_id": sid, "claim": CLAIM, "reason": "unlocatable-quote", "seqs": [1]} for sid in session_ids]
    (context_dir / filename).write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _node(repo: Path, path: str = "acme") -> "projects_mod.ProjectPaths":
    return projects_mod.resolve(path, repo_root=repo)


def _interview_doc(session_id: str) -> Document:
    return Document(
        source_type=INTERVIEW, origin=f"session:{session_id}", title=f"Interview {session_id}",
        sections=(Section(text=SPOKEN, location="turn 1", speaker="interviewee"),),
    )


def _populate(repo: Path, path: str = "acme") -> "projects_mod.ProjectPaths":
    """Two interviews filed at one node, each with a row in every
    session-keyed file and a copy in the node's knowledge base."""
    paths = _node(repo, path)
    for session_id in (GONE, KEPT):
        _session(paths.sessions_root, session_id)
    paths.context_dir.mkdir(parents=True)
    corpus_store.write_facts(paths.context_dir, [_fact(GONE, "f1"), _fact(KEPT, "f2"), _fact(GONE, "f3")])
    for name in ("rejections.json", "demotions.json"):
        _rows(paths.context_dir, name, GONE, KEPT)
    (paths.context_dir / "declined_proposals.json").write_text(json.dumps([
        {"hypothesis_id": "h1", "proposed_state": "refuted", "declined_at": "2026-11-03T00:00:00Z", "session_id": GONE},
        {"hypothesis_id": "h1", "proposed_state": "refuted", "declined_at": "2026-11-04T00:00:00Z", "session_id": KEPT},
    ]), encoding="utf-8")
    store = KnowledgeStore.for_node(paths.node_dir)
    for session_id in (GONE, KEPT):
        store.put(_interview_doc(session_id))
    store.put(Document(source_type=RESEARCH, origin="notes.md", title="notes",
                       sections=(Section(text="market notes", location="p1"),)))
    return paths


def _forget(*argv: str) -> int:
    return main_mod.main(["forget", *argv])


def _snapshot(root: Path) -> "dict[str, bytes]":
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _session_ids_in(path: Path) -> "list[str]":
    return [row.get("session_id") for row in json.loads(path.read_text(encoding="utf-8"))]


# --- the dry run --------------------------------------------------------------


def test_without_yes_it_lists_what_it_would_delete_and_deletes_nothing(repo, capsys):
    _populate(repo)
    before = _snapshot(repo)

    assert _forget(GONE, "--project", "acme") == 0

    out = capsys.readouterr().out
    assert _snapshot(repo) == before
    assert str(repo / "projects" / "acme" / "sessions" / GONE) in out
    assert "facts.json: 2 rows" in out
    assert "rejections.json: 1 row" in out
    assert "demotions.json: 1 row" in out
    assert "declined_proposals.json: 1 row" in out
    assert "knowledge base: 1 document" in out
    assert "--yes" in out and "Nothing was deleted" in out


def test_the_listing_never_prints_what_anyone_said(repo, capsys):
    _populate(repo)
    _forget(GONE, "--project", "acme")
    _forget(GONE, "--project", "acme", "--yes")
    captured = capsys.readouterr()
    for text in (captured.out, captured.err):
        assert SPOKEN not in text
        assert CLAIM not in text


# --- the erasure --------------------------------------------------------------


def test_yes_erases_one_interview_and_leaves_the_other_byte_identical(repo, capsys):
    paths = _populate(repo)
    kept_dir_before = _snapshot(paths.sessions_root / KEPT)

    assert _forget(GONE, "--project", "acme", "--yes") == 0

    assert not (paths.sessions_root / GONE).exists()
    assert _snapshot(paths.sessions_root / KEPT) == kept_dir_before
    facts = json.loads((paths.context_dir / "facts.json").read_text(encoding="utf-8"))
    assert [f["id"] for f in facts] == ["f2"]
    for name in ("rejections.json", "demotions.json", "declined_proposals.json"):
        assert _session_ids_in(paths.context_dir / name) == [KEPT], name
    origins = sorted(s.document.origin for s in KnowledgeStore.for_node(paths.node_dir).all())
    assert origins == ["notes.md", f"session:{KEPT}"]
    assert not list(paths.context_dir.glob("*.tmp"))


def test_a_second_run_finds_nothing_left(repo, capsys):
    _populate(repo)
    assert _forget(GONE, "--project", "acme", "--yes") == 0
    capsys.readouterr()
    assert _forget(GONE, "--project", "acme") == 1
    assert "Nothing found" in capsys.readouterr().out


def test_rows_are_removed_even_after_the_directory_was_deleted_by_hand(repo, capsys):
    # The README used to tell people to delete the directory themselves, so
    # there are corpora out there whose rows outlived their interview.
    import shutil

    paths = _populate(repo)
    shutil.rmtree(paths.sessions_root / GONE)

    assert _forget(GONE, "--project", "acme", "--yes") == 0
    assert _session_ids_in(paths.context_dir / "facts.json") == [KEPT]
    assert _session_ids_in(paths.context_dir / "rejections.json") == [KEPT]


def test_a_root_session_is_erased_from_the_root_context(repo, capsys):
    _session(repo / "sessions", GONE, room_audio=True)
    _session(repo / "sessions", KEPT)
    (repo / "context").mkdir()
    corpus_store.write_facts(repo / "context", [_fact(GONE, "f1"), _fact(KEPT, "f2")])

    assert _forget(GONE, "--yes") == 0
    assert not (repo / "sessions" / GONE).exists()
    assert (repo / "sessions" / KEPT).is_dir()
    assert _session_ids_in(repo / "context" / "facts.json") == [KEPT]


def test_a_copy_in_another_projects_knowledge_base_is_reported_not_deleted(repo, capsys):
    # Session ids are timestamps, so the same id at another node may be a
    # DIFFERENT person's interview. Erasing it on a guess would be the defect
    # this command must never have.
    _session(repo / "sessions", GONE)
    other = _node(repo, "beta")
    other.node_dir.mkdir(parents=True)
    KnowledgeStore.for_node(other.node_dir).put(_interview_doc(GONE))
    _session(other.sessions_root, GONE)

    assert _forget(GONE, "--yes") == 0
    out = capsys.readouterr().out
    assert len(KnowledgeStore.for_node(other.node_dir).all()) == 1
    assert (other.sessions_root / GONE).is_dir()
    assert "beta" in out and "kb remove" in out
    assert f"forget {GONE} --project beta" in out


def test_digest_notes_of_a_removed_document_are_dropped(repo, capsys):
    paths = _populate(repo)
    gone_id = _interview_doc(GONE).doc_id
    knowledge_dir = paths.node_dir / KNOWLEDGE_DIR_NAME
    kb_digest.save(knowledge_dir, [
        kb_digest.Entry(doc_id=gone_id, content_hash="x", source_type=INTERVIEW, title="t",
                        points=(kb_digest.Point(text="p", location="turn 1"),)),
        kb_digest.Entry(doc_id="f" * len(gone_id), content_hash="y", source_type=RESEARCH, title="r",
                        points=(kb_digest.Point(text="q", location="p1"),)),
    ])

    assert _forget(GONE, "--project", "acme", "--yes") == 0
    assert [e.doc_id for e in kb_digest.load(knowledge_dir)] == ["f" * len(gone_id)]


# --- refusals: tolerant on load, strict on save --------------------------------


def test_a_file_that_will_not_parse_is_left_untouched_and_named(repo, capsys):
    paths = _populate(repo)
    broken = paths.context_dir / "rejections.json"
    broken.write_text("[{not json", encoding="utf-8")

    assert _forget(GONE, "--project", "acme", "--yes") == 1

    captured = capsys.readouterr()
    assert broken.read_text(encoding="utf-8") == "[{not json"
    assert "rejections.json" in captured.err and "untouched" in captured.err
    # Everything else still went: a damaged diagnostic log must not keep a
    # person's interview on disk.
    assert not (paths.sessions_root / GONE).exists()
    assert _session_ids_in(paths.context_dir / "facts.json") == [KEPT]


def test_a_corpus_that_fails_validation_is_left_untouched(repo, capsys):
    paths = _populate(repo)
    facts = paths.context_dir / "facts.json"
    facts.write_text(json.dumps([{"id": "f1", "session_id": GONE}]), encoding="utf-8")
    before = facts.read_bytes()

    assert _forget(GONE, "--project", "acme", "--yes") == 1
    assert facts.read_bytes() == before
    assert "facts.json" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["../acme", "a/b", "a\\b", "..", ".", "", "C:\\x"])
def test_a_session_id_that_could_name_a_path_is_refused_before_anything_is_read(repo, capsys, bad):
    _populate(repo)
    before = _snapshot(repo)
    assert _forget(bad, "--project", "acme", "--yes") == 2
    assert _snapshot(repo) == before
    assert "session id" in capsys.readouterr().err


def test_an_unknown_session_reports_nothing_found(repo, capsys):
    _populate(repo)
    assert _forget("20990101T000000", "--project", "acme", "--yes") == 1
    assert "Nothing found" in capsys.readouterr().out


def test_the_kept_hypothesis_boundary_is_reported_as_not_erased(repo, capsys):
    # `criterion_registered_after` lists session IDS (no words) as the record
    # of what existed when a rule was written. Rewriting it would forge a
    # pre-registration claim, so it stays -- and the operator is told.
    paths = _populate(repo)
    (paths.context_dir / "hypotheses.json").write_text(json.dumps([{
        "id": "h1", "statement": "s", "falsifier": "f", "state": "untested",
        "criterion": "c", "criterion_registered_after": [GONE],
    }]), encoding="utf-8")
    _forget(GONE, "--project", "acme")
    out = capsys.readouterr().out
    assert "pre-registration" in out
