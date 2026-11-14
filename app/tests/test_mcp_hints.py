"""MCP `list_projects` says the one next step for each gap, so a coding agent
never answers a new user with a raw error; and the demo walkthrough rule
allows labelled demo results while keeping the refusal of them as findings."""

from __future__ import annotations

import json

from app.mcp import tools


def _node(repo, name, *, sessions=0, facts=None):
    node = repo / "projects" / name
    (node / "context").mkdir(parents=True)
    for n in range(sessions):
        session = node / "sessions" / f"2026061{n}T000000"
        session.mkdir(parents=True)
        (session / "session.json").write_text("{}", encoding="utf-8")
    if facts is not None:
        (node / "context" / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    return node


def _by_path(result):
    return {entry["path"]: entry for entry in result["projects"]}


def test_no_project_says_load_the_demo(tmp_path):
    (tmp_path / "projects").mkdir()
    result = tools.list_projects({}, repo_root=tmp_path)
    assert result["projects"] == []
    assert result["hint"] == tools.HINT_NO_PROJECT
    assert "python -m app demo --yes" in result["hint"]


def test_a_node_with_no_interviews_says_record_or_import(tmp_path):
    _node(tmp_path, "acme")
    result = tools.list_projects({}, repo_root=tmp_path)
    assert result["hint"] is None
    assert _by_path(result)["acme"]["hint"] == tools.HINT_NO_INTERVIEWS.format(path="acme")


def test_interviews_without_claims_say_extract(tmp_path):
    _node(tmp_path, "acme", sessions=2)
    _node(tmp_path, "beta", sessions=1, facts=[])
    hints = {path: entry["hint"] for path, entry in _by_path(tools.list_projects({}, repo_root=tmp_path)).items()}
    assert hints["acme"] == tools.HINT_NOT_EXTRACTED.format(path="acme")
    assert hints["beta"] == tools.HINT_NOT_EXTRACTED.format(path="beta")


def test_a_node_with_claims_needs_no_hint(tmp_path):
    _node(tmp_path, "acme", sessions=1, facts=[{"id": "f1"}])
    assert _by_path(tools.list_projects({}, repo_root=tmp_path))["acme"]["hint"] is None


def test_the_walkthrough_rule_keeps_the_refusal():
    for description in (_description("get_facts"), _description("get_standing")):
        assert "Never report a demo claim as a finding" in description
        assert "In a walkthrough of a demo node you may show its results" in description
        assert "mock interviews" in description


def _description(name):
    return next(description for tool, description, *_ in tools._TOOL_ORDER if tool == name)


def test_a_junction_out_of_projects_never_breaks_the_listing(tmp_path):
    import subprocess

    import pytest

    _node(tmp_path, "acme", sessions=1, facts=[{"id": "f1"}])
    outside = tmp_path / "outside"
    (outside / "context").mkdir(parents=True)
    link = tmp_path / "projects" / "elsewhere"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, text=True)
    if made.returncode != 0 or not link.exists():
        pytest.skip("cannot create a junction here")
    try:
        result = tools.list_projects({}, repo_root=tmp_path)
    finally:
        link.rmdir()
    assert _by_path(result)["acme"]["hint"] is None
    escaped = _by_path(result).get("elsewhere")
    assert escaped is None or escaped["hint"] == tools.HINT_OUTSIDE_PROJECTS


def test_an_unreadable_facts_file_says_so_rather_than_send_the_user_to_extract(tmp_path):
    node = _node(tmp_path, "acme", sessions=1)
    (node / "context" / "facts.json").write_text("{not json", encoding="utf-8")
    assert _by_path(tools.list_projects({}, repo_root=tmp_path))["acme"]["hint"] == \
        tools.HINT_FACTS_UNREADABLE.format(path="acme")
