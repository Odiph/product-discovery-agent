"""`python -m app extract --all`: every not-yet-extracted interview in a node,
each through the single-session path. The model is always the offline stub."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import main as main_mod
from app import projects as projects_mod
from app.coach import reasoning_client
from app.coach.extract import EXTRACT_TOOL_NAME
from app.coach.stub import StubAnthropicClient, tool_use_response
from app.session.store import SessionStore

SPOKEN = "we onboard a customer in three weeks"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(projects_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(tmp_path / "context"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy")
    return tmp_path


def _node(repo: Path) -> "projects_mod.ProjectPaths":
    return projects_mod.resolve("acme", repo_root=repo)


def _session(sessions_root: Path, session_id: str, text: str = SPOKEN) -> Path:
    session_dir = sessions_root / session_id
    store = SessionStore(session_dir)
    store.write_metadata({"engine": "fake"})
    store.append_segment(speaker="interviewer", text="walk me through onboarding", audio_start_s=0.0,
                         audio_end_s=1.0, ready_wall_s=1.1, detected_language="en", engine="fake")
    store.append_segment(speaker="interviewee", text=text, audio_start_s=1.0,
                         audio_end_s=3.0, ready_wall_s=3.1, detected_language="en", engine="fake")
    store.close()
    return session_dir


def _fact_response(text: str = SPOKEN):
    return tool_use_response(EXTRACT_TOOL_NAME, {"facts": [{
        "claim": "Onboarding takes three weeks.", "seqs": [1], "provenance": "evidence",
        "quoted_text": text, "bearings": [],
    }]})


def _stub(monkeypatch, responses) -> StubAnthropicClient:
    stub = StubAnthropicClient(responses=responses)
    monkeypatch.setattr(reasoning_client, "build_client", lambda: stub)
    return stub


def _facts_sessions(context_dir: Path) -> "list[str]":
    path = context_dir / "facts.json"
    if not path.is_file():
        return []
    return sorted({row["session_id"] for row in json.loads(path.read_text(encoding="utf-8"))})


def _extract_all(*extra: str) -> int:
    return main_mod.main(["extract", "--all", "--project", "acme", *extra])


def test_without_yes_it_lists_the_pending_sessions_with_an_estimate_and_calls_nothing(repo, monkeypatch, capsys):
    node = _node(repo)
    _session(node.sessions_root, "20260101T100000")
    _session(node.sessions_root, "20260102T100000")
    called = []
    monkeypatch.setattr(reasoning_client, "build_client", lambda: called.append(1))
    assert _extract_all() == 0
    assert called == []
    assert not node.context_dir.exists()
    out = capsys.readouterr().out
    assert "20260101T100000" in out and "20260102T100000" in out
    assert "input tokens" in out
    assert "--yes" in out
    assert SPOKEN not in out


def test_with_yes_it_extracts_only_the_unextracted_oldest_first(repo, monkeypatch, capsys):
    node = _node(repo)
    _session(node.sessions_root, "20260101T100000")
    _session(node.sessions_root, "20260102T100000")
    _stub(monkeypatch, [_fact_response()])
    assert main_mod.main(["extract", "20260101T100000", "--project", "acme"]) == 0

    stub = _stub(monkeypatch, [_fact_response()])
    assert _extract_all("--yes") == 0
    assert len(stub.calls) == 1, "an already-extracted session was extracted again"
    assert _facts_sessions(node.context_dir) == ["20260101T100000", "20260102T100000"]
    out = capsys.readouterr().out
    assert "1 extracted" in out


def test_a_failure_does_not_stop_the_rest_and_the_exit_code_says_so(repo, monkeypatch, capsys):
    node = _node(repo)
    _session(node.sessions_root, "20260101T100000")
    _session(node.sessions_root, "20260102T100000")
    stub = _stub(monkeypatch, [TimeoutError("simulated"), _fact_response()])
    assert _extract_all("--yes") == 1
    assert len(stub.calls) == 2
    assert _facts_sessions(node.context_dir) == ["20260102T100000"]
    out = capsys.readouterr().out
    assert "20260101T100000: failed" in out
    assert "20260102T100000: extracted" in out
    assert "1 failed" in out


def test_nothing_pending_calls_nothing(repo, monkeypatch, capsys):
    node = _node(repo)
    _session(node.sessions_root, "20260101T100000")
    _stub(monkeypatch, [_fact_response()])
    main_mod.main(["extract", "20260101T100000", "--project", "acme"])
    stub = _stub(monkeypatch, [])
    assert _extract_all("--yes") == 0
    assert stub.calls == []
    assert "Nothing to extract" in capsys.readouterr().out


def test_force_re_extracts_everything(repo, monkeypatch):
    node = _node(repo)
    _session(node.sessions_root, "20260101T100000")
    _stub(monkeypatch, [_fact_response()])
    main_mod.main(["extract", "20260101T100000", "--project", "acme"])
    stub = _stub(monkeypatch, [_fact_response()])
    assert _extract_all("--yes", "--force") == 0
    assert len(stub.calls) == 1


def test_an_unconfirmed_in_person_session_is_skipped_not_paid_for(repo, monkeypatch, capsys):
    node = _node(repo)
    session_dir = _session(node.sessions_root, "20260101T100000")
    meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    meta.update({"capture": "in-person", "evidence": "pending"})
    (session_dir / "session.json").write_text(json.dumps(meta), encoding="utf-8")
    stub = _stub(monkeypatch, [])
    assert _extract_all("--yes") == 0
    assert stub.calls == []
    assert "skipped 20260101T100000" in capsys.readouterr().err


def test_an_imported_transcript_is_extracted_by_all(repo, monkeypatch, tmp_path):
    source = tmp_path / "call.txt"
    source.write_text(f"Sam: walk me through onboarding\nDana: {SPOKEN}\nOdi: and then?\n"
                      "Dana: then we go live\n", encoding="utf-8")
    assert main_mod.main(["import", str(source), "--project", "acme", "--me", "Sam",
                          "--date", "2026-02-03", "--yes"]) == 0
    _stub(monkeypatch, [_fact_response()])
    assert _extract_all("--yes") == 0
    assert _facts_sessions(_node(repo).context_dir) == ["20260203T000000"]


@pytest.mark.parametrize("argv", [
    ["extract", "--all", "20260101T100000"],
    ["extract", "20260101T100000", "--force"],
    ["extract", "20260101T100000", "--yes"],
    ["extract"],
])
def test_bad_combinations_are_refused(repo, argv):
    assert main_mod.main(argv) == 2
