"""`python -m app demo`: load the 12 mock interviews, already extracted,
grouped and judged, so the first result costs no API call and needs no key.

The seed under `demo/claudictive-beta/seed/` is synthetic (`corpus: demo`)
and pins the models its cached judgments were made with
(`project_meta.pinned_models`), so the caches stay fresh on any machine.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

from app import config as config_mod
from app import missed_cli, project_meta
from app import projects as projects_mod
from app.projects import REPO_ROOT

DEMO_PROJECT = "claudictive-beta"
SEED_DIR = REPO_ROOT / "demo" / DEMO_PROJECT / "seed"

MOCK_LABEL = project_meta.MOCK_LABEL
LOADING_SUFFIX = ".loading"
ABSENT, LOADED, DIFFERS = "absent", "loaded", "differs"
RENAME_ATTEMPTS = 3
RENAME_WAIT_S = 0.5


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "demo",
        help=f"load the 12 mock interviews, already processed, into projects/{DEMO_PROJECT} "
             f"(no API call, no key)",
    )
    parser.add_argument("--yes", action="store_true", help="copy the project; without it, only say what it writes")
    parser.add_argument("--open", action="store_true", help="then open the hub in the browser")


def run(args: argparse.Namespace, *, repo_root: "Optional[Path]" = None,
        open_hub: "Callable[[str], int]") -> int:
    target = projects_mod.resolve(DEMO_PROJECT, repo_root=repo_root).node_dir
    shown = f"projects/{DEMO_PROJECT}"
    state = (ABSENT if not target.exists() else LOADED if _same_tree(SEED_DIR, target) else DIFFERS)
    if state == DIFFERS:
        print(f"{shown} already exists and differs from the seed: it was changed here, or a newer seed "
              f"arrived with an update. Nothing was changed. Use it as it is, or move it away and re-run "
              f"to load a fresh copy.")
        return 0 if not args.yes else 1
    if not args.yes:
        print(f"The mock interviews are already loaded in {shown}." if state == LOADED else
              f"Would copy the 12 mock interviews, already processed ({_size_kb(SEED_DIR):,} KB), into {shown}: "
              f"no API call, no key needed. Re-run with --yes to load them.")
        return 0
    if state == LOADED:
        print(f"{MOCK_LABEL} already loaded in {shown}.")
    else:
        try:
            _copy_into(target)
        except OSError as exc:
            staging = target.with_name(target.name + LOADING_SUFFIX)
            left = "" if not staging.exists() else f" A partial copy was left at {staging}; delete it."
            print(f"Could not load the demo into {shown} ({type(exc).__name__}: {exc}).{left or ' Nothing was left behind.'}")
            return 1
        print(MOCK_LABEL)
    return _show(target, open_hub, open_=args.open)


def _copy_into(target: Path) -> None:
    """Copies the seed next to `target`, then renames it into place, so a
    failed copy never leaves a half project where a whole one is expected."""
    staging = target.with_name(target.name + LOADING_SUFFIX)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        shutil.copytree(SEED_DIR, staging)
        _rename_with_retry(staging, target)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _rename_with_retry(source: Path, target: Path) -> None:
    """Windows Defender or the indexer often holds a just-written file for a
    moment, so a rename can fail with PermissionError and then succeed."""
    for attempt in range(RENAME_ATTEMPTS):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == RENAME_ATTEMPTS - 1:
                raise
            time.sleep(RENAME_WAIT_S)


def _show(target: Path, open_hub: "Callable[[str], int]", *, open_: bool) -> int:
    try:
        cached = missed_cli.cached_report(target / "context", target / "sessions")
    except Exception as exc:  # noqa: BLE001 -- a data condition; say it, never a traceback
        print(f"The demo is loaded but its report could not be read ({type(exc).__name__}: {exc}).")
        return 1
    missed_cli.print_report(cached.report, indent="  ", details=False)
    if open_:
        return open_hub(DEMO_PROJECT)
    port = config_mod.load_config().author_port
    print(f"See it in the hub: python -m app hub --project {DEMO_PROJECT} (it serves http://127.0.0.1:{port}/)")
    return 0


def _files(root: Path) -> "dict[str, Path]":
    return {path.relative_to(root).as_posix(): path for path in root.rglob("*") if path.is_file()}


def _same_tree(left: Path, right: Path) -> bool:
    """Same relative paths, then same sizes, then same bytes, cheapest first:
    a project someone recorded into has extra files and is never read whole.
    A file that cannot be read means "differs", never a traceback."""
    try:
        ours, theirs = _files(left), _files(right)
        if ours.keys() != theirs.keys():
            return False
        if any(ours[name].stat().st_size != theirs[name].stat().st_size for name in ours):
            return False
        return all(filecmp.cmp(ours[name], theirs[name], shallow=False) for name in ours)
    except OSError:
        return False


def _size_kb(root: Path) -> int:
    return round(sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) / 1024)
