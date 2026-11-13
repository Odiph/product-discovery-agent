"""`python -m app setup`: what a fresh clone needs, checked, then the two
ways in: the mock interviews (free, no key) or your own project.

Keys are reported as present or missing, never by value. There is no live
key check: one would cost money on every run, so it waits for a decision
(BACKLOG B7). Audio devices are `python -m app precheck`'s job; this only
points there.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Mapping, Optional

from app import config as config_mod
from app import projects as projects_mod
from app.demo_cli import DEMO_PROJECT

MIN_PYTHON = (3, 12)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    next_step: str = ""


def add_parser(subparsers) -> None:
    subparsers.add_parser("setup", help="check this machine for a first run, then say what to try first")


def checks(env: Mapping[str, str], *, python: "tuple[int, int]", in_venv: bool, seeded: bool) -> "tuple[Check, ...]":
    wanted = ".".join(map(str, MIN_PYTHON))
    has_model = bool(env.get("ANTHROPIC_API_KEY") or env.get("COACH_BASE_URL"))
    return (
        Check(f"Python {python[0]}.{python[1]}", tuple(python) >= MIN_PYTHON,
              f"install Python {wanted} or newer"),
        Check("Inside the project's venv", in_venv,
              "run the VS Code task 'Setup: create venv and install' (README, Setup), then use .venv's python"),
        Check("Model access: ANTHROPIC_API_KEY (or COACH_BASE_URL)", has_model,
              "add ANTHROPIC_API_KEY to .env (see .env.example) to extract and judge your own interviews; "
              "the demo needs no key"),
        Check("Recording transcription: SONIOX_API_KEY", bool(env.get("SONIOX_API_KEY")),
              "add SONIOX_API_KEY to .env for recordings; transcripts and the demo need none"),
        Check(f"Mock interviews loaded (projects/{DEMO_PROJECT})", seeded,
              "python -m app demo --yes"),
    )


def render(results: "tuple[Check, ...]") -> "list[str]":
    lines = [f"  {'ok  ' if check.ok else 'todo'}  {check.name}" + ("" if check.ok else f": {check.next_step}")
             for check in results]
    seeded = results[-1].ok
    first = (f"python -m app hub --project {DEMO_PROJECT} (the mock interviews are loaded; or "
             f"python -m app missed --project {DEMO_PROJECT} --group model)" if seeded else
             "python -m app demo --yes (12 mock interviews, already processed: no API call, no key)")
    return ["First-run check:", *lines, "", "Try it on the mock interviews:", f"  1. {first}",
            "  2. Or start your own: python -m app author --project <name>"]


def run(args: argparse.Namespace, *, repo_root: "Optional[str]" = None) -> int:
    config_mod.load_config()
    seeded = projects_mod.resolve(DEMO_PROJECT, repo_root=repo_root).node_dir.is_dir()
    results = checks(os.environ, python=sys.version_info[:2], in_venv=sys.prefix != sys.base_prefix,
                     seeded=seeded)
    print("\n".join(render(results)))
    return 0
