"""`search_knowledge` over MCP: cited hits, and no customer speech on the wire.

The sentinel is planted in EVERY source type, then searched for. Speech types
(interview, conversation, email) must come back as citations without it;
research and code must come back WITH it -- which is what proves the search
reached the planted text at all, so the privacy assertion is not vacuous.
"""

from __future__ import annotations

import json

import pytest

from app.kb.document import CODE, CONVERSATION, EMAIL, INTERVIEW, RESEARCH, Document, Section
from app.kb.store import KnowledgeStore
from app.mcp import tools as mcp_tools

SENTINEL = "kbsentinelword"
SPEECH = f"we rebuilt the {SENTINEL} by hand every friday"


def _doc(source_type, origin, *, speaker=None, title="t", explicit_type=True):
    return Document(
        source_type=source_type, origin=origin, title=title, date="2026-10-01",
        participants=("dana@example.com",), explicit_type=explicit_type,
        sections=(Section(text=SPEECH, location="turn 1", speaker=speaker),),
    )


@pytest.fixture
def repo(tmp_path):
    node = tmp_path / "projects" / "acme"
    (node / "context").mkdir(parents=True)
    store = KnowledgeStore.for_node(node)
    store.put(_doc(INTERVIEW, "session:S1", speaker="interviewee", title="Interview with Dana Cohen"))
    store.put(_doc(CONVERSATION, "/x/call.vtt", speaker="Dana Cohen", title="call with Dana Cohen"))
    store.put(_doc(EMAIL, "/x/m.eml", title=f"Re: the {SENTINEL} subject"))
    store.put(_doc(RESEARCH, "/x/notes.md", title="Notes"))
    store.put(_doc(CODE, "/x/repo", title="Repository repo"))
    return tmp_path


def _call(arguments, repo):
    return mcp_tools.call_tool("search_knowledge", arguments, repo_root=repo)


def test_speech_never_crosses_and_own_material_does(repo):
    payload = _call({"project": "acme", "query": SENTINEL}, repo)
    by_type = {hit["source_type"]: hit for hit in payload["hits"]}
    assert set(by_type) == {INTERVIEW, CONVERSATION, EMAIL, RESEARCH, CODE}
    for speech_type in (INTERVIEW, CONVERSATION, EMAIL):
        blob = json.dumps(by_type[speech_type])
        assert SENTINEL not in blob, f"{speech_type} text crossed the wire"
        assert by_type[speech_type]["location"] == "turn 1"
    assert SENTINEL in by_type[RESEARCH]["text"]
    assert SENTINEL in by_type[CODE]["text"]
    blob = json.dumps(payload)
    assert "Dana Cohen" not in blob and "dana@example.com" not in blob
    assert by_type[INTERVIEW]["role"] == "interviewee"
    assert payload["documents"] == {INTERVIEW: 1, CONVERSATION: 1, EMAIL: 1, RESEARCH: 1, CODE: 1}


def test_source_type_filter_and_limit(repo):
    payload = _call({"project": "acme", "query": SENTINEL, "source_types": [RESEARCH], "limit": 1}, repo)
    assert [hit["source_type"] for hit in payload["hits"]] == [RESEARCH]


@pytest.mark.parametrize("arguments", [
    {"project": "acme"},
    {"project": "acme", "query": ""},
    {"project": "acme", "query": "x" * 501},
    {"project": "acme", "query": "x", "limit": 0},
    {"project": "acme", "query": "x", "limit": True},
    {"project": "acme", "query": "x", "source_types": ["nope"]},
    {"project": "acme", "query": "x", "source_types": []},
    {"project": "acme", "query": "x", "scope": "subtree"},
    {"project": "../etc", "query": "x"},
])
def test_bad_arguments_are_the_callers_error(repo, arguments):
    with pytest.raises(mcp_tools.ToolArgumentError):
        _call(arguments, repo)


def test_an_empty_knowledge_base_says_so(tmp_path):
    (tmp_path / "projects" / "empty").mkdir(parents=True)
    payload = _call({"project": "empty", "query": "anything"}, tmp_path)
    assert payload == {"project": "empty", "documents": {}, "hits": [], "damaged_documents": 0, "error": None}


def test_a_damaged_store_reports_the_failure_class_not_its_content(repo):
    damaged = next((repo / "projects" / "acme" / "knowledge" / "documents").glob("*.json"))
    damaged.write_text('{"text": "' + SENTINEL + '", BROKEN', encoding="utf-8")
    payload = _call({"project": "acme", "query": SENTINEL}, repo)
    assert payload["damaged_documents"] == 1
    assert len(payload["documents"]) == 4, "the other documents must still be searched"
    blob = json.dumps({k: v for k, v in payload.items() if k != "hits"})
    assert SENTINEL not in blob


def test_no_title_crosses_for_any_speech_type(repo):
    """An interview's title is "Interview with <participant>" and a
    conversation's is its file stem ("call with Dana"): names, both."""
    payload = _call({"project": "acme", "query": SENTINEL}, repo)
    by_type = {hit["source_type"]: hit for hit in payload["hits"]}
    for speech_type in (INTERVIEW, CONVERSATION, EMAIL):
        assert by_type[speech_type]["title"] is None
        assert by_type[speech_type]["date"] == "2026-10-01"
    assert by_type[RESEARCH]["title"] == "Notes"


def test_research_typed_by_guess_crosses_as_a_citation_only(tmp_path):
    """A PDF or a `.md` is research by guess: it may be a call transcript.
    Its text crosses only once the operator has said `--type research`."""
    node = tmp_path / "projects" / "acme"
    (node / "context").mkdir(parents=True)
    store = KnowledgeStore.for_node(node)
    store.put(_doc(RESEARCH, "/x/guessed.pdf", explicit_type=False))
    store.put(_doc(CODE, "/x/repo", explicit_type=False))
    payload = _call({"project": "acme", "query": SENTINEL}, tmp_path)
    by_type = {hit["source_type"]: hit for hit in payload["hits"]}
    assert by_type[RESEARCH]["text"] is None and by_type[RESEARCH]["location"] == "turn 1"
    assert SENTINEL not in json.dumps(by_type[RESEARCH])
    # Code is a repository's own prose, typed by what the folder is: unchanged.
    assert SENTINEL in by_type[CODE]["text"]


def test_the_real_kb_add_decides_what_crosses_not_a_hand_built_document(tmp_path, monkeypatch):
    """The seam test: every other case here builds its Document by hand, so a
    `kb add` that stopped passing `--type` through to the loader would leave
    them all green. Real CLI in, real MCP tool out, same file both times."""
    from app import main as main_mod
    from app import projects as projects_mod

    monkeypatch.setattr(projects_mod, "REPO_ROOT", tmp_path)
    notes = tmp_path / "notes.md"
    notes.write_text(f"# Notes\n\nThey said the {SENTINEL} was rebuilt by hand.\n", encoding="utf-8")

    assert main_mod.main(["kb", "add", str(notes), "--project", "acme"]) == 0
    hits = _call({"project": "acme", "query": SENTINEL}, tmp_path)["hits"]
    assert [h["text"] for h in hits] == [None], "a guessed type must cross as a citation only"

    assert main_mod.main(["kb", "add", str(notes), "--type", "research", "--project", "acme"]) == 0
    hits = _call({"project": "acme", "query": SENTINEL}, tmp_path)["hits"]
    assert len(hits) == 1, "confirming must update the same document, not add a second"
    assert SENTINEL in hits[0]["text"]
