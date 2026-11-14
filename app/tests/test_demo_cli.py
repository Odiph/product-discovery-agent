"""`python -m app demo`: load the seeded mock project, never overwrite a
changed one, label every result as mock, call no model, and open the hub
only when asked."""

from __future__ import annotations

import argparse

import pytest

from app import config as config_mod
from app import demo_cli
from app.coach import reasoning_client
from app.demo_cli import DEMO_PROJECT

MODEL_VARS = ("EXTRACT_MODEL", "JUDGE_MODEL", "COACH_MODEL", "COACH_BASE_URL")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for name in MODEL_VARS:
        monkeypatch.delenv(name, raising=False)

    def no_call(*_, **__):
        raise AssertionError("the demo must not call a model")

    monkeypatch.setattr(reasoning_client, "build_client", no_call)
    (tmp_path / "projects").mkdir()
    return tmp_path


def _run(repo, *, yes=True, open_=False, opened=None):
    args = argparse.Namespace(yes=yes, open=open_)
    calls = opened if opened is not None else []
    return demo_cli.run(args, repo_root=repo, open_hub=lambda project: calls.append(project) or 0)


def test_preview_writes_nothing(repo, capsys):
    assert _run(repo, yes=False) == 0
    out = capsys.readouterr().out
    assert not (repo / "projects" / DEMO_PROJECT).exists()
    assert "no API call" in out and "--yes" in out and f"projects/{DEMO_PROJECT}" in out


def test_yes_loads_and_prints_the_labelled_headline(repo, capsys):
    assert _run(repo) == 0
    lines = capsys.readouterr().out.splitlines()
    assert (repo / "projects" / DEMO_PROJECT / "context" / "facts.json").is_file()
    assert lines[0] == demo_cli.MOCK_LABEL
    assert any(line.strip().startswith("In 9 of 12 interviews") and line.endswith("You followed up in 1.")
               for line in lines), lines
    port = config_mod.load_config().author_port
    assert lines[-1] == (f"See it in the hub: python -m app hub --project {DEMO_PROJECT} "
                         f"(it serves http://127.0.0.1:{port}/)")


def test_a_second_run_says_already_loaded(repo, capsys):
    _run(repo)
    capsys.readouterr()
    assert _run(repo) == 0
    out = capsys.readouterr().out
    assert "already loaded" in out and demo_cli.MOCK_LABEL in out


def test_a_changed_project_is_never_overwritten(repo, capsys):
    _run(repo)
    changed = repo / "projects" / DEMO_PROJECT / "context" / "brief.json"
    changed.write_text('{"edited": true}', encoding="utf-8")
    capsys.readouterr()
    assert _run(repo) == 1
    assert changed.read_text(encoding="utf-8") == '{"edited": true}'
    out = capsys.readouterr().out
    assert f"projects/{DEMO_PROJECT}" in out and "nothing was changed" in out.lower()
    assert "differs from the seed" in out and "newer seed" in out
    assert "changed since" not in out, "the refusal must not blame the user: a git pull can update the seed"


def test_open_calls_the_hub_and_nothing_opens_without_it(repo, capsys):
    opened = []
    _run(repo, opened=opened)
    assert opened == []
    _run(repo, open_=True, opened=opened)
    assert opened == [DEMO_PROJECT]
    assert "See it in the hub" not in capsys.readouterr().out.splitlines()[-1]


def test_a_failed_copy_leaves_no_half_project(repo, monkeypatch):
    def broken(src, dst, **_):
        (dst / "partial").mkdir(parents=True)
        raise OSError("disk full")

    monkeypatch.setattr(demo_cli.shutil, "copytree", broken)
    assert _run(repo) == 1
    assert not (repo / "projects" / DEMO_PROJECT).exists()
    assert [p.name for p in (repo / "projects").iterdir()] == []


def test_the_preview_tells_the_truth_once_loaded(repo, capsys):
    _run(repo)
    capsys.readouterr()
    assert _run(repo, yes=False) == 0
    out = capsys.readouterr().out
    assert "already loaded" in out and "Would copy" not in out
    (repo / "projects" / DEMO_PROJECT / "context" / "brief.json").write_text("{}", encoding="utf-8")
    assert _run(repo, yes=False) == 0
    out = capsys.readouterr().out
    assert "differs from the seed" in out and "Would copy" not in out
    assert (repo / "projects" / DEMO_PROJECT / "context" / "brief.json").read_text(encoding="utf-8") == "{}"


def test_an_extra_file_reads_as_differs_without_reading_it(repo, monkeypatch):
    _run(repo)
    extra = repo / "projects" / DEMO_PROJECT / "sessions" / "big.wav"
    extra.write_bytes(b"\0" * 1024)
    real_read = demo_cli.Path.read_bytes

    def guarded(path):
        assert path != extra, "a file only one side has must not be read to know they differ"
        return real_read(path)

    monkeypatch.setattr(demo_cli.Path, "read_bytes", guarded)
    assert demo_cli._same_tree(demo_cli.SEED_DIR, repo / "projects" / DEMO_PROJECT) is False


def test_a_locked_file_reads_as_differs_never_a_traceback(repo, monkeypatch):
    _run(repo)

    def locked(*_, **__):
        raise PermissionError("locked")

    monkeypatch.setattr(demo_cli.filecmp, "cmp", locked)
    assert demo_cli._same_tree(demo_cli.SEED_DIR, repo / "projects" / DEMO_PROJECT) is False


def test_a_briefly_locked_rename_is_retried(repo, monkeypatch):
    calls = []
    real_rename = demo_cli.Path.rename

    def flaky(self, target):
        calls.append(target)
        if len(calls) < 3:
            raise PermissionError("[WinError 5] held by the indexer")
        return real_rename(self, target)

    monkeypatch.setattr(demo_cli.Path, "rename", flaky)
    monkeypatch.setattr(demo_cli, "RENAME_WAIT_S", 0)
    assert _run(repo) == 0
    assert (repo / "projects" / DEMO_PROJECT / "context" / "facts.json").is_file()
    assert len(calls) == 3
