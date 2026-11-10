"""`python -m app process init --project <node>`: lay down the starter
`context/process.md` -- your own rules, added on top of the Mom Test the coach
and the critique already apply. Never overwrites; calls no model.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from app import config as config_mod
from app.coach import process as process_mod


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    process = subparsers.add_parser(
        "process",
        help="Your own interviewing rules, added on top of the Mom Test in the coach and the critique",
    )
    actions = process.add_subparsers(dest="process_command", required=True)
    init = actions.add_parser(
        "init",
        help=f"Write a commented starter {process_mod.PROCESS_FILENAME} into the project's context "
             "(never overwrites; an untouched starter changes nothing)",
    )
    add_project_argument(init)


def run(args: argparse.Namespace, apply_project) -> int:
    cfg = apply_project(config_mod.load_config(), args)
    try:
        path = process_mod.write_template(cfg.context_dir)
    except FileExistsError:
        print(
            f"ERROR: {cfg.context_dir / process_mod.PROCESS_FILENAME} already exists -- edit it "
            "rather than starting over.",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(f"ERROR: cannot write {cfg.context_dir / process_mod.PROCESS_FILENAME}: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {path}. Add your own rules below the comment, one '## heading' per rule.")
    return 0
