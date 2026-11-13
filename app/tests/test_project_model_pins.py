"""A project node can pin the models its cached judgments were made with
(`project.json` "models"), so the committed demo's caches stay fresh on any
machine. The pin beats the environment on that node only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import grouping_cli
from app.coach import reasoning_client
from app.project_meta import pinned_models

MODEL_VARS = ("EXTRACT_MODEL", "JUDGE_MODEL", "COACH_MODEL")


def _node(tmp_path: Path, meta) -> Path:
    node = tmp_path / "projects" / "demo-node"
    (node / "context").mkdir(parents=True)
    if meta is not None:
        (node / "project.json").write_text(json.dumps(meta), encoding="utf-8")
    return node


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in MODEL_VARS:
        monkeypatch.delenv(name, raising=False)


def test_a_pin_beats_the_environment(tmp_path, monkeypatch):
    node = _node(tmp_path, {"corpus": "demo", "models": {"extract": "pin/x", "judge": "pin/j"}})
    monkeypatch.setenv("EXTRACT_MODEL", "env/x")
    monkeypatch.setenv("JUDGE_MODEL", "env/j")
    assert reasoning_client.resolve_extract_model(node / "context") == "pin/x"
    assert reasoning_client.resolve_judge_model(node / "context") == "pin/j"


def test_a_judge_without_its_own_pin_follows_the_pinned_extract_model(tmp_path, monkeypatch):
    node = _node(tmp_path, {"models": {"extract": "pin/x"}})
    monkeypatch.setenv("EXTRACT_MODEL", "env/x")
    assert reasoning_client.resolve_judge_model(node / "context") == "pin/x"


def test_no_pin_keeps_todays_behaviour(tmp_path, monkeypatch):
    node = _node(tmp_path, {"corpus": "real"})
    monkeypatch.setenv("EXTRACT_MODEL", "env/x")
    assert reasoning_client.resolve_judge_model(node / "context") == "env/x"
    assert reasoning_client.resolve_extract_model() == "env/x"
    monkeypatch.setenv("JUDGE_MODEL", "env/j")
    assert reasoning_client.resolve_judge_model(node / "context") == "env/j"


@pytest.mark.parametrize("models", ["gemini", [], {"extract": ""}, {"extract": 3}, {"other": "a/b"}])
def test_a_malformed_pin_is_ignored(tmp_path, monkeypatch, models):
    node = _node(tmp_path, {"models": models})
    monkeypatch.setenv("EXTRACT_MODEL", "env/x")
    assert reasoning_client.resolve_extract_model(node / "context") == "env/x"
    assert pinned_models(node) == {}


@pytest.mark.parametrize("raw", [None, "{not json", "[1, 2]"])
def test_a_missing_or_unreadable_project_file_never_raises(tmp_path, monkeypatch, raw):
    node = _node(tmp_path, None)
    if raw is not None:
        (node / "project.json").write_text(raw, encoding="utf-8")
    monkeypatch.setenv("EXTRACT_MODEL", "env/x")
    assert reasoning_client.resolve_extract_model(node / "context") == "env/x"


def test_the_grouping_preview_names_the_pinned_model(tmp_path, monkeypatch, capsys):
    node = _node(tmp_path, {"models": {"extract": "pin/x"}})
    monkeypatch.setenv("EXTRACT_MODEL", "env/x")
    seen = []
    monkeypatch.setattr(grouping_cli.topics_mod, "assemble_request",
                        lambda lines, *, model, **_: seen.append(model) or {"model": model})
    grouping_cli.resolve(node / "context", (), mode=grouping_cli.MODEL, yes=False)
    assert seen == ["pin/x"]


def test_a_pinned_model_is_named_as_pinned_in_the_preview(tmp_path, monkeypatch):
    node = _node(tmp_path, {"models": {"extract": "pin/x"}})
    monkeypatch.setattr(grouping_cli.topics_mod, "claim_lines", lambda _: ("line",))
    monkeypatch.setattr(grouping_cli.topics_mod, "assemble_request", lambda lines, *, model, **_: {"model": model})
    resolution = grouping_cli.resolve(node / "context", (), mode=grouping_cli.MODEL, yes=False)
    assert any("pin/x" in note and reasoning_client.PIN_NOTE in note for note in resolution.notes)


def test_an_unpinned_preview_says_nothing_about_pins(tmp_path, monkeypatch):
    node = _node(tmp_path, {"corpus": "real"})
    monkeypatch.setenv("EXTRACT_MODEL", "env/x")
    monkeypatch.setattr(grouping_cli.topics_mod, "claim_lines", lambda _: ("line",))
    monkeypatch.setattr(grouping_cli.topics_mod, "assemble_request", lambda lines, *, model, **_: {"model": model})
    resolution = grouping_cli.resolve(node / "context", (), mode=grouping_cli.MODEL, yes=False)
    assert all(reasoning_client.PIN_NOTE not in note for note in resolution.notes)


def test_a_failed_call_on_a_pinned_model_says_how_to_unpin(tmp_path, monkeypatch):
    node = _node(tmp_path, {"models": {"extract": "pin/x"}})
    monkeypatch.setattr(grouping_cli.topics_mod, "claim_lines", lambda _: ("line",))
    monkeypatch.setattr(grouping_cli.topics_mod, "assemble_request", lambda lines, *, model, **_: {"model": model})

    def failing(*_, **__):
        raise grouping_cli.topics_mod.GroupingFailure(reason="exception")

    monkeypatch.setattr(reasoning_client, "build_client", lambda: object())
    monkeypatch.setattr(grouping_cli.topics_mod, "group_claims", failing)
    resolution = grouping_cli.resolve(node / "context", (), mode=grouping_cli.MODEL, yes=True)
    assert resolution.exit_code == 1
    assert reasoning_client.PIN_NOTE in resolution.headline and "project.json" in resolution.headline
