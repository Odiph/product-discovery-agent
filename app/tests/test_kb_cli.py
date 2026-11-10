"""`python -m app kb ...` end to end, against a project tree in tmp_path."""

from __future__ import annotations

import json

import pytest

from app import main as main_mod
from app import projects as projects_mod
from app.kb.store import KnowledgeStore, KnowledgeStoreError


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(projects_mod, "REPO_ROOT", tmp_path)
    return tmp_path


def _kb(*argv):
    return main_mod.main(["kb", *argv])


def _node(root, path="acme"):
    return root / "projects" / path


def test_kb_needs_a_project(root, capsys):
    assert _kb("list") == 2
    assert "--project" in capsys.readouterr().err


def test_add_search_list_remove_round_trip(root, tmp_path, capsys):
    notes = tmp_path / "notes.md"
    notes.write_text("# Notes\n\nThey export to spreadsheets every Friday.\n", encoding="utf-8")
    assert _kb("add", str(notes), "--project", "acme") == 0
    out = capsys.readouterr().out
    assert "1 added" in out and "nothing was sent" in out

    assert _kb("search", "spreadsheet", "--project", "acme") == 0
    out = capsys.readouterr().out
    assert "[research] Notes -- line 3" in out

    doc_id = KnowledgeStore.for_node(_node(root)).all()[0].doc_id
    assert _kb("remove", doc_id[:6], "--project", "acme") == 0
    assert notes.is_file(), "removing from the index must never touch the source"
    assert _kb("list", "--project", "acme") == 0
    assert "empty" in capsys.readouterr().out


def test_re_adding_unchanged_is_a_no_op_and_a_change_replaces(root, tmp_path, capsys):
    notes = tmp_path / "n.txt"
    notes.write_text("first version\n", encoding="utf-8")
    _kb("add", str(notes), "--project", "acme")
    capsys.readouterr()
    _kb("add", str(notes), "--project", "acme")
    assert "0 added, 0 updated, 1 unchanged" in capsys.readouterr().out
    notes.write_text("second version\n", encoding="utf-8")
    _kb("add", str(notes), "--project", "acme")
    assert "0 added, 1 updated" in capsys.readouterr().out
    stored = KnowledgeStore.for_node(_node(root)).all()
    assert len(stored) == 1 and stored[0].document.sections[0].text == "second version"


def test_sessions_flag_indexes_the_projects_own_interviews(root, capsys):
    session = _node(root) / "sessions" / "20260923T171000"
    session.mkdir(parents=True)
    (session / "session.json").write_text(json.dumps({"participant": "Noa"}), encoding="utf-8")
    (session / "transcript.jsonl").write_text(
        json.dumps({"kind": "segment", "seq": 0, "speaker": "interviewee", "text": "we track it on paper",
                    "audio_start_s": 0.0, "audio_end_s": 3.0}) + "\n",
        encoding="utf-8",
    )
    assert _kb("add", "--sessions", "--project", "acme") == 0
    capsys.readouterr()
    _kb("search", "paper", "--project", "acme")
    assert "[interview] Interview with Noa -- turn 1 (00:03) -- interviewee" in capsys.readouterr().out


def test_the_knowledge_directory_is_never_listed_as_a_project(root, tmp_path):
    notes = tmp_path / "n.txt"
    notes.write_text("x\n", encoding="utf-8")
    _kb("add", str(notes), "--project", "acme")
    assert [n.path for n in projects_mod.list_projects(repo_root=root)] == ["acme"]


def test_nothing_to_add_and_everything_skipped_both_fail(root, tmp_path, capsys):
    assert _kb("add", "--project", "acme") == 2
    (tmp_path / "x.pdf").write_bytes(b"%PDF")
    assert _kb("add", str(tmp_path / "x.pdf"), "--project", "acme") == 1
    assert "PDF" in capsys.readouterr().out


def test_topics_command(root, tmp_path, capsys):
    for name, body in (("a.txt", "invoice export invoice export spreadsheet spreadsheet\n"),
                       ("b.txt", "invoice reminder invoice reminder calendar calendar\n")):
        (tmp_path / name).write_text(body, encoding="utf-8")
    _kb("add", str(tmp_path / "a.txt"), str(tmp_path / "b.txt"), "--project", "acme")
    capsys.readouterr()
    assert _kb("topics", "--project", "acme") == 0
    out = capsys.readouterr().out
    assert "Across the project: invoice (2)" in out


def test_bad_ids_are_refused_not_guessed(root, tmp_path, capsys):
    store = KnowledgeStore.for_node(_node(root))
    for ref in ("", "abc", "zzzzzz", "0" * 13):
        with pytest.raises(KnowledgeStoreError):
            store.resolve_id(ref)
    assert _kb("remove", "ffffff", "--project", "acme") == 1
    assert "no document" in capsys.readouterr().err


def test_a_damaged_document_file_is_reported(root, tmp_path, capsys):
    notes = tmp_path / "n.txt"
    notes.write_text("x\n", encoding="utf-8")
    _kb("add", str(notes), "--project", "acme")
    damaged = next((_node(root) / "knowledge" / "documents").glob("*.json"))
    damaged.write_text("{not json", encoding="utf-8")
    capsys.readouterr()
    assert _kb("list", "--project", "acme") == 0
    captured = capsys.readouterr()
    assert "damaged" in captured.err and "empty" in captured.out
    # Re-adding the source repairs it.
    assert _kb("add", str(notes), "--project", "acme") == 0
    assert "1 updated" in capsys.readouterr().out


def test_standing_is_byte_identical_after_adding_knowledge(root, tmp_path, capsys, monkeypatch):
    """B1's provenance rule: other sources sit beside the evidence, never vote."""
    context = _node(root) / "context"
    context.mkdir(parents=True)
    (context / "hypotheses.json").write_text(json.dumps([
        {"id": "h1", "statement": "they export by hand", "falsifier": "nobody exports"},
    ]), encoding="utf-8")
    (context / "facts.json").write_text(json.dumps([{
        "id": "f1", "claim": "they rebuilt the export by hand", "provenance": "evidence",
        "session_id": "S1", "seqs": [1], "quoted_text": "by hand",
        "bearings": [{"hypothesis_id": "h1", "stance": "supports"}],
    }]), encoding="utf-8")
    (_node(root) / "sessions" / "S1").mkdir(parents=True)
    before_files = {p.name: p.read_bytes() for p in context.iterdir()}
    assert main_mod.main(["standing", "--project", "acme"]) == 0
    before = capsys.readouterr().out

    email = tmp_path / "m.eml"
    email.write_bytes(b"From: a@example.com\r\nSubject: export\r\n\r\nWe export by hand, every week.\r\n")
    assert _kb("add", str(email), "--project", "acme") == 0
    capsys.readouterr()

    assert main_mod.main(["standing", "--project", "acme"]) == 0
    assert capsys.readouterr().out == before
    assert {p.name: p.read_bytes() for p in context.iterdir()} == before_files


# --- kb digest: the coach's summarised knowledge ---------------------------------


def _points(*texts):
    from app.coach.stub import tool_use_response
    from app.kb import digest_model

    return tool_use_response(digest_model.DIGEST_TOOL_NAME,
                             {"points": [{"text": t, "location": "line 3"} for t in texts]})


@pytest.fixture
def research_and_email(root, tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("# Notes\n\nThey export to spreadsheets every Friday.\n", encoding="utf-8")
    mail = tmp_path / "m.eml"
    mail.write_text("From: a@b.c\nSubject: hi\n\nCustomer words here.\n", encoding="utf-8")
    # Research is digested only when the operator typed it so.
    assert _kb("add", str(notes), "--type", "research", "--project", "acme") == 0
    assert _kb("add", str(mail), "--project", "acme") == 0
    return notes


def _stub_vendor(monkeypatch, responses):
    from app.coach import reasoning_client
    from app.coach.stub import StubAnthropicClient

    client = StubAnthropicClient(responses=responses)
    monkeypatch.setattr(reasoning_client, "build_client", lambda: client)
    return client




def test_add_names_the_digest_as_the_only_way_out(root, tmp_path, capsys):
    notes = tmp_path / "n.md"
    notes.write_text("# N\n\nSome research.\n", encoding="utf-8")
    assert _kb("add", str(notes), "--project", "acme") == 0
    out = capsys.readouterr().out
    assert "kb digest" in out and "coach model" in out


def test_digest_without_yes_lists_and_sends_nothing(research_and_email, monkeypatch, capsys):
    client = _stub_vendor(monkeypatch, [])
    capsys.readouterr()
    assert _kb("digest", "--project", "acme") == 0
    out = capsys.readouterr().out
    assert "1 document(s) to summarise" in out and "Notes" in out
    assert "1 email" in out
    assert client.calls == []


def test_digest_summarises_research_once_and_never_the_email(root, research_and_email, monkeypatch, capsys):
    from app.kb import digest

    client = _stub_vendor(monkeypatch, [_points("They export every Friday.")])
    assert _kb("digest", "--yes", "--project", "acme") == 0
    assert len(client.calls) == 1
    entries = digest.load(_node(root) / "knowledge")
    assert [p.text for e in entries for p in e.points] == ["They export every Friday."]

    capsys.readouterr()
    assert _kb("digest", "--yes", "--project", "acme") == 0, "unchanged documents cost nothing"
    assert len(client.calls) == 1
    assert "Nothing to summarise" in capsys.readouterr().out

    assert _kb("digest", "--show", "--project", "acme") == 0
    out = capsys.readouterr().out
    assert "They export every Friday." in out and "line 3" in out


def test_a_failed_document_is_reported_and_the_rest_kept(root, tmp_path, monkeypatch, capsys):
    from app.kb import digest

    for name in ("a", "b"):
        (tmp_path / f"{name}.md").write_text(f"# {name}\n\nText {name}.\n", encoding="utf-8")
    assert _kb("add", str(tmp_path / "a.md"), str(tmp_path / "b.md"), "--type", "research",
               "--project", "acme") == 0
    _stub_vendor(monkeypatch, [TimeoutError(), _points("B point.")])
    assert _kb("digest", "--yes", "--project", "acme") == 1
    assert "failed" in capsys.readouterr().err
    assert len(digest.load(_node(root) / "knowledge")) == 1


def test_digest_without_a_key_is_a_clean_error(research_and_email, monkeypatch, capsys):
    from app.coach import reasoning_client

    def no_key():
        raise reasoning_client.CoachConfigError("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(reasoning_client, "build_client", no_key)
    assert _kb("digest", "--yes", "--project", "acme") == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_an_interrupted_digest_keeps_the_documents_already_paid_for(root, tmp_path, monkeypatch):
    from app.kb import digest

    for name in ("a", "b"):
        (tmp_path / f"{name}.md").write_text(f"# {name}\n\nText {name}.\n", encoding="utf-8")
    assert _kb("add", str(tmp_path / "a.md"), str(tmp_path / "b.md"), "--type", "research",
               "--project", "acme") == 0
    _stub_vendor(monkeypatch, [_points("First point."), KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        _kb("digest", "--yes", "--project", "acme")
    assert [p.text for e in digest.load(_node(root) / "knowledge") for p in e.points] == ["First point."]


def test_add_says_how_many_were_typed_research_by_guess_and_how_to_confirm(root, tmp_path, capsys):
    notes = tmp_path / "n.md"
    notes.write_text("# N\n\nSome research.\n", encoding="utf-8")
    assert _kb("add", str(notes), "--project", "acme") == 0
    out = capsys.readouterr().out
    assert "1 document(s) typed research by guess" in out
    assert "kb add --type research" in out

    assert _kb("digest", "--project", "acme") == 0
    assert "1 research typed by guess" in capsys.readouterr().out

    # Confirming overwrites the same document: same id, now explicit.
    assert _kb("add", str(notes), "--type", "research", "--project", "acme") == 0
    out = capsys.readouterr().out
    assert "1 updated" in out and "by guess" not in out
    (stored,) = KnowledgeStore.for_node(_node(root)).all()
    assert stored.document.explicit_type is True


def test_a_secret_is_a_skip_line_that_does_not_print_it(root, tmp_path, capsys):
    key = "AKIA" + "QWERTYUIOPASDFGH"
    notes = tmp_path / "runbook.md"
    notes.write_text(f"# Runbook\n\nUse {key} to deploy.\n", encoding="utf-8")
    assert _kb("add", str(notes), "--project", "acme") == 1
    out = capsys.readouterr().out
    assert "skipped" in out and "secret" in out and key not in out
    assert KnowledgeStore.for_node(_node(root)).all() == []
