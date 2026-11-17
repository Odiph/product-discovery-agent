"""`python -m app themes --project <node>`: what keeps coming up across
interviews that no hypothesis predicted. Reads the extracted claims only (never
the quotes). No model call and nothing written, unless `--group model --yes`
(`grouping_cli`), which shares `missed`'s grouping and its cache.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from app import config as config_mod
from app import grouping_cli
from app.coach import themes as themes_mod
from app.coach.corpus import CorpusValidationError


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    themes = subparsers.add_parser(
        "themes",
        help="Claims that bear on NO hypothesis and recur in two or more interviews: the patterns "
             "nobody predicted (no model call unless --group model --yes)",
    )
    add_project_argument(themes)
    grouping_cli.add_arguments(themes, command="themes")


def run(args: argparse.Namespace, apply_project, read_corpus_refs) -> int:
    from benchmark.console import use_utf8_console

    use_utf8_console()
    cfg = apply_project(config_mod.load_config(), args)
    try:
        _, refs, corpus_exists = read_corpus_refs(cfg, project_label=getattr(args, "project", None) or "")
    except CorpusValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not corpus_exists:
        print("No extracted claims yet: run `python -m app extract <session>` on your interviews first.")
        return 0
    resolution = grouping_cli.resolve(cfg.context_dir, refs, mode=args.group, yes=args.yes)
    grouping_cli.describe(resolution)
    if resolution.exit_code is not None:
        return resolution.exit_code
    unbound = sum(1 for ref in refs if not ref.bearings)
    sessions = len({ref.session_id for ref in refs})
    found = (themes_mod.unbound_themes(refs) if resolution.groups is None else themes_mod.from_groups(
        refs, resolution.groups, include=lambda ref: not ref.bearings, min_interviews=themes_mod.MIN_INTERVIEWS))
    print(f"{unbound} of {len(refs)} claims, from {sessions} interview(s), bear on no hypothesis.")
    if not found:
        print("None of them recurs across two interviews yet -- no unpredicted theme.")
        return 0
    print(f"{len(found)} recur across interviews:\n")
    for number, theme in enumerate(found, start=1):
        label = ", ".join(theme.label) or "(no shared words)"
        print(f"{number}. {label} -- in {len(theme.sessions)} interviews, {len(theme.fact_ids)} claims")
        for fact_id, claim in zip(theme.fact_ids, theme.claims):
            print(f"     [{fact_id}] {claim}")
        print()
    print("Each is a candidate hypothesis nobody wrote. Draft one in `python -m app author` if it deserves a test.")
    return 0
