"""The committed demo seed: the 12 mock interviews already extracted, grouped
and judged, so a fresh clone shows the `missed` headline with no API call.

The last test is the drift alarm: a prompt or key change that stales any of
the seeded caches fails here before a fresh clone falls back to word match."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from app import missed_cli
from app.coach import context as coach_context
from app.coach import prep_load, reasoning_client
from app.demo_cli import DEMO_PROJECT, SEED_DIR
from app.projects import REPO_ROOT

# No machine path. Real names are checked by the public-sync names grep, so
# they are not spelled out here, in a file that ships publicly.
NOT_IN_THE_SEED = re.compile(r"[A-Z]:[\\/]+Users[\\/]", re.IGNORECASE)


def test_the_seed_is_declared_synthetic():
    meta = json.loads((SEED_DIR / "project.json").read_text(encoding="utf-8"))
    assert meta["corpus"] == "demo"


def test_the_seed_holds_no_machine_path():
    files = [path for path in SEED_DIR.rglob("*") if path.is_file()]
    assert files
    assert [str(path) for path in files if NOT_IN_THE_SEED.search(path.read_text(encoding="utf-8"))] == []


@pytest.fixture
def loaded(tmp_path, monkeypatch):
    # Other models configured on purpose: the seed's pins must win over them.
    monkeypatch.setenv("EXTRACT_MODEL", "other/x")
    monkeypatch.setenv("JUDGE_MODEL", "other/j")
    for name in ("COACH_MODEL", "COACH_BASE_URL"):
        monkeypatch.delenv(name, raising=False)

    def no_call(*_, **__):
        raise AssertionError("the seeded demo must not call a model")

    monkeypatch.setattr(reasoning_client, "build_client", no_call)
    node = tmp_path / "projects" / DEMO_PROJECT
    shutil.copytree(SEED_DIR, node)
    return node


def test_the_seeded_headline_needs_no_call_and_every_cache_is_fresh(loaded):
    cached = missed_cli.cached_report(loaded / "context", loaded / "sessions")
    assert "cached in" in cached.grouping
    assert "by the model's reading" in cached.prompted and "cached in" in cached.prompted
    assert "by the model's reading" in cached.followed and "cached in" in cached.followed
    headlines = [missed_cli.headline(topic, cached.report.interviews) for topic in cached.report.topics]
    assert any(line.startswith("In 9 of 12 interviews") and line.endswith("You followed up in 1.")
               for line in headlines), headlines


def _ignored(relative_path: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", relative_path], cwd=str(REPO_ROOT)).returncode == 0


def test_only_the_seed_sessions_are_re_admitted_to_git():
    assert not _ignored("demo/claudictive-beta/seed/sessions/20260615T000000/transcript.jsonl")
    for still_private in ("sessions/x/transcript.jsonl", "demo/other/sessions/x/transcript.jsonl",
                          "demo/claudictive-beta/sessions/x/transcript.jsonl",
                          "demo/claudictive-beta/seed/sessions/x/interviewee.wav",
                          "projects/claudictive-beta/sessions/x/transcript.jsonl"):
        assert _ignored(still_private), still_private


def test_the_seeded_coverage_reading_is_fresh_too(loaded):
    reading = prep_load.model_reading(loaded / "context", loaded / "sessions",
                                      coach_context.load_survey(loaded / "context"))
    assert reading.asked is not None, getattr(reading, "note", reading)
