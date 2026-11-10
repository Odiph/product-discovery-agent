"""`python -m app import <file-or-folder> --me <speaker>`: bring past interviews
in from their transcript exports, one session per file
(app/session/transcript_import.py).

Without `--yes` it prints what it would import -- file, speakers, turn counts,
who becomes the interviewer -- and writes nothing. It never prints a word
anyone said: names and counts only.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from app import config as config_mod
from app.session import transcript_import as ti
from app.session.participant import normalize_participant


def _date_arg(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not a date in YYYY-MM-DD form") from exc


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    parser = subparsers.add_parser(
        "import",
        help="Bring past interviews in from transcript exports (.vtt, .srt, `Name: text` .txt/.md), "
             "one session per file. Without --yes it only shows what it would import",
    )
    parser.add_argument("source", type=Path, help="a transcript file, or a folder of them (not recursive)")
    parser.add_argument("--me", required=True, metavar="NAME",
                        help="your speaker name as the file spells it; your turns become the interviewer's")
    parser.add_argument("--participant", default=None, metavar="NAME",
                        help="who was interviewed (default: the other speaker, when there is exactly one)")
    parser.add_argument("--date", type=_date_arg, default=None, metavar="YYYY-MM-DD",
                        help="when the interview happened (default: the file's modified time, flagged as such)")
    parser.add_argument("--yes", action="store_true", help="write the sessions; without it nothing is written")
    add_project_argument(parser)


def _candidates(source: Path) -> "list[Path]":
    if source.is_dir():
        return sorted(p for p in source.iterdir() if p.is_file() and ti.classify(p) != "other")
    return [source]


def _describe(plan: ti.FilePlan, participant: Optional[str], date_note: str) -> None:
    roles = "; ".join(
        f"{name} {count} turn{'s' if count != 1 else ''} -> "
        f"{ti.INTERVIEWER if name == plan.me else ti.INTERVIEWEE}"
        for name, count in plan.speaker_turns
    )
    print(f"{plan.file_name} ({plan.format}): {len(plan.speaker_turns)} speakers -- {roles}")
    if len(plan.others) > 1:
        print(f"  NOTE: {len(plan.speaker_turns)} speakers -- everyone except {plan.me} is recorded "
              f"as the interviewee, so their turns are not told apart.")
    print(f"  participant: {participant or '(none named)'}; date: {date_note}; times: "
          f"{'synthetic (the file has none)' if plan.times_synthetic else 'from the file'}")
    if plan.unlabelled_dropped:
        print(f"  {plan.unlabelled_dropped} unlabelled passage(s) dropped -- no speaker to give them to.")


def run(args: argparse.Namespace, apply_project) -> int:
    source: Path = args.source
    if not source.exists():
        print(f"ERROR: {source} does not exist", file=sys.stderr)
        return 1
    participant, error = normalize_participant(args.participant)
    if error is not None:
        print(f"ERROR: --participant: {error}", file=sys.stderr)
        return 2
    candidates = _candidates(source)
    if not candidates:
        print(f"ERROR: {source} holds no transcript files ({', '.join(sorted(ti.SUPPORTED_SUFFIXES))})",
              file=sys.stderr)
        return 1
    if participant is not None and len(candidates) > 1:
        print("ERROR: --participant names ONE person and this folder holds several interviews -- "
              "import those files one at a time to name each participant.", file=sys.stderr)
        return 2

    cfg = apply_project(config_mod.load_config(), args)
    refused = 0
    ready: "list[tuple[ti.FilePlan, dict, datetime]]" = []
    seen: "dict[str, str]" = {}
    for path in candidates:
        try:
            plan = ti.plan_file(path, me=args.me)
        except ti.ImportRefused as exc:
            print(f"REFUSED {path.name}: {exc}", file=sys.stderr)
            refused += 1
            continue
        existing = ti.find_duplicate(cfg.sessions_root, plan.sha256) or seen.get(plan.sha256)
        if existing is not None:
            print(f"REFUSED {path.name}: already imported here, as {existing} -- `forget` it first "
                  "to import it again.", file=sys.stderr)
            refused += 1
            continue
        seen[plan.sha256] = f"{path.name} (earlier in this run)"
        who = participant
        if who is None and len(plan.others) == 1:
            who, _ = normalize_participant(plan.others[0])
        if args.date is not None:
            started, date_source, date_note = args.date, "operator --date", args.date.strftime("%Y-%m-%d")
        else:
            started = datetime.fromtimestamp(plan.mtime)
            date_source = "file-mtime"
            date_note = f"{started:%Y-%m-%d} (the file's modified time -- pass --date if that is not the interview's)"
        _describe(plan, who, date_note)
        metadata = ti.session_metadata(plan, started=started, started_at_source=date_source, participant=who)
        ready.append((plan, metadata, started))

    if not args.yes:
        if ready:
            print(f"\nNothing written. Re-run with --yes to import {len(ready)} interview(s) "
                  f"into {cfg.sessions_root}.")
        return 1 if refused else 0

    for plan, metadata, started in ready:
        try:
            session_dir = ti.write_session(cfg.sessions_root, plan, metadata, started=started)
        except OSError as exc:
            print(f"ERROR {plan.file_name}: could not be written ({type(exc).__name__}: {exc})", file=sys.stderr)
            refused += 1
            continue
        print(f"Imported {plan.file_name} as session {session_dir.name} ({len(plan.turns)} turns).")
    if ready:
        project = f" --project {args.project}" if getattr(args, "project", None) else ""
        print(f"Next: python -m app extract --all{project}")
    return 1 if refused else 0
