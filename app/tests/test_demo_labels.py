"""Every surface a first-time user is sent to after `demo` labels the demo's
results as mock: `missed`, `mirror` and the hub page. A real project gets no
label."""

from __future__ import annotations

import argparse
import shutil

import pytest
from fastapi.testclient import TestClient

from app import main as main_mod
from app import mirror_cli, missed_cli
from app.coach import reasoning_client
from app.demo_cli import DEMO_PROJECT, SEED_DIR
from app.project_meta import MOCK_LABEL
from app.web import review as web_review

MODEL_VARS = ("EXTRACT_MODEL", "JUDGE_MODEL", "COACH_MODEL", "COACH_BASE_URL")


@pytest.fixture
def demo_node(tmp_path, monkeypatch):
    for name in MODEL_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(reasoning_client, "build_client", lambda *_, **__: (_ for _ in ()).throw(AssertionError))
    node = tmp_path / "projects" / DEMO_PROJECT
    shutil.copytree(SEED_DIR, node)
    return node


def _replace(cfg, node):
    from dataclasses import replace
    return replace(cfg, context_dir=node / "context", sessions_root=node / "sessions")


def _first_line(capsys):
    return capsys.readouterr().out.splitlines()[0]


def test_missed_on_the_demo_says_mock_first(demo_node, capsys):
    args = argparse.Namespace(project=DEMO_PROJECT, group="auto", yes=False)
    missed_cli.run(args, lambda cfg, _: _replace(cfg, demo_node))
    assert _first_line(capsys) == MOCK_LABEL


def test_mirror_on_the_demo_says_mock_first(demo_node, capsys):
    args = argparse.Namespace(project=DEMO_PROJECT, show=False)
    mirror_cli.run(args, lambda cfg, _: _replace(cfg, demo_node))
    assert _first_line(capsys) == MOCK_LABEL


def test_a_real_project_gets_no_label(demo_node, capsys):
    (demo_node / "project.json").write_text('{"corpus": "real"}', encoding="utf-8")
    args = argparse.Namespace(project=DEMO_PROJECT, group="auto", yes=False)
    missed_cli.run(args, lambda cfg, _: _replace(cfg, demo_node))
    assert MOCK_LABEL not in capsys.readouterr().out


@pytest.mark.parametrize("corpus, labelled", [("demo", True), ("real", False)])
def test_the_hub_page_carries_the_banner_only_for_a_demo(tmp_path, corpus, labelled):
    node = tmp_path / "projects" / "node"
    (node / "context").mkdir(parents=True)
    (node / "project.json").write_text(f'{{"corpus": "{corpus}"}}', encoding="utf-8")
    app = web_review.create_review_app(static_dir=main_mod.STATIC_REVIEW_DIR, project="node",
                                       session_id=None, repo_root=tmp_path)
    page = TestClient(app, base_url="http://127.0.0.1").get("/").text
    assert (MOCK_LABEL in page) is labelled


def test_the_missed_command_we_point_users_to_reads_the_model_judgments_for_free(demo_node, capsys):
    from app import setup_cli
    pointed = "-m app missed --project claudictive-beta --group model"
    readme = (main_mod.Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
    start = (main_mod.Path(__file__).resolve().parents[2] / "integrations" / "claude-code" / "discovery"
             / "commands" / "start.md").read_text(encoding="utf-8")
    shown = "\n".join(setup_cli.render(setup_cli.checks({}, python=(3, 12), in_venv=True, seeded=True)))
    for where, text in (("setup", shown), ("README", readme), ("/start", start)):
        assert pointed in text, f"{where} points at a missed command that falls back to word match"
    args = argparse.Namespace(project=DEMO_PROJECT, group="model", yes=False)
    assert missed_cli.run(args, lambda cfg, _: _replace(cfg, demo_node)) == 0
    out = capsys.readouterr().out
    assert out.count("by the model's reading") == 2 and "Nothing called" not in out
