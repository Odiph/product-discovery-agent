"""`python -m app import <file-or-folder>`: bring past interviews in, one
session per file -- from a transcript export
(app/session/transcript_import.py) or from a recording
(app/session/audio_import.py).

Without `--yes` it prints what it would do and does nothing. For a transcript:
file, speakers, turn counts, who becomes the interviewer. For a recording:
file, length, size, and the vendor it would be uploaded to -- that upload is
the only paid step, and it never happens without `--yes`. It never prints a
word anyone said: names and counts only.

A recording is not transcribed here. It is written as a session holding a
copy of the audio and handed to the SAME file pass an in-person meeting uses
(app/evidence_cli.py `diarize-after`); who spoke is then confirmed with the
same `confirm-speakers`, not by a rule of this command's own.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from app import config as config_mod
from app import evidence_cli
from app.session import audio_import as ai
from app.session import evidence as ev
from app.session import transcript_import as ti
from app.session.participant import normalize_participant

FILE_PASS_VENDOR = "Soniox"
FILE_PASS_KEY = "SONIOX_API_KEY"


def _date_arg(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not a date in YYYY-MM-DD form") from exc


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    parser = subparsers.add_parser(
        "import",
        help="Bring past interviews in from transcript exports (.vtt, .srt, `Name: text` .txt/.md) or "
             f"recordings (16 kHz mono .wav; uploaded to {FILE_PASS_VENDOR} for transcription, needs "
             f"{FILE_PASS_KEY}), one session per file. Without --yes it only shows what it would do",
    )
    parser.add_argument("source", type=Path, help="a transcript or recording, or a folder of them (not recursive)")
    parser.add_argument("--me", default=None, metavar="NAME",
                        help="transcripts only, and required for them: your speaker name as the file spells "
                             "it; your turns become the interviewer's")
    parser.add_argument("--participant", default=None, metavar="NAME",
                        help="who was interviewed (default for a transcript: the other speaker, when there "
                             "is exactly one)")
    parser.add_argument("--date", type=_date_arg, default=None, metavar="YYYY-MM-DD",
                        help="when the interview happened (default: the file's modified time, flagged as such)")
    parser.add_argument("--yes", action="store_true",
                        help="write the sessions and upload any recording; without it nothing is written or sent")
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


def _describe_audio(plan: ai.AudioPlan, participant: Optional[str], date_note: str) -> None:
    print(f"{plan.file_name} (recording): {plan.duration_s / 60:.1f} min, {plan.size_bytes / 1_000_000:.1f} MB")
    print(f"  upload: the whole file goes to {FILE_PASS_VENDOR} (speech-to-text) for the file pass, billed "
          f"by them to your {FILE_PASS_KEY}; their copy is deleted afterwards.")
    print(f"  kept here: a copy in the session ({ev.ROOM_AUDIO_FILENAME}) until you confirm the speakers; "
          f"your file is not touched.")
    print("  speakers: the first voice is taken as the interviewer until you check it with "
          "`confirm-speakers` (add --swap if it was the other person). `extract` waits for that.")
    print(f"  participant: {participant or '(none named)'}; date: {date_note}")


def _started(args: argparse.Namespace, mtime: float) -> "tuple[datetime, str, str]":
    """(when, where that came from, the line shown to the operator)."""
    if args.date is not None:
        return args.date, "operator --date", args.date.strftime("%Y-%m-%d")
    started = datetime.fromtimestamp(mtime)
    return started, "file-mtime", (
        f"{started:%Y-%m-%d} (the file's modified time -- pass --date if that is not the interview's)"
    )


def _plan_audio(path: Path) -> ai.AudioPlan:
    from benchmark.engines import soniox_async

    plan = ai.plan_audio(path)
    limit_s = soniox_async.MAX_FILE_DURATION_S
    if plan.duration_s > limit_s:
        raise ti.ImportRefused(
            f"is {plan.duration_s / 60:.0f} minutes; the file pass accepts at most {limit_s / 60:.0f} "
            "minutes per file -- split it and import the parts"
        )
    return plan


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
        print(f"ERROR: {source} holds no transcript files ({', '.join(sorted(ti.SUPPORTED_SUFFIXES))}) "
              f"and no recordings ({ai.WAV_SUFFIX})", file=sys.stderr)
        return 1
    if participant is not None and len(candidates) > 1:
        print("ERROR: --participant names ONE person and this folder holds several interviews -- "
              "import those files one at a time to name each participant.", file=sys.stderr)
        return 2
    if args.me is None and any(ti.classify(path) != "audio" for path in candidates):
        print("ERROR: --me is required to import a transcript: your speaker name as the file spells it.",
              file=sys.stderr)
        return 2

    cfg = apply_project(config_mod.load_config(), args)
    refused = 0
    ready: "list[tuple[ti.FilePlan, dict, datetime]]" = []
    recordings: "list[tuple[Path, ai.AudioPlan, dict, datetime]]" = []
    seen: "dict[str, str]" = {}
    for path in candidates:
        is_audio = ti.classify(path) == "audio"
        try:
            plan = _plan_audio(path) if is_audio else ti.plan_file(path, me=args.me)
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
        started, date_source, date_note = _started(args, plan.mtime)
        if is_audio:
            _describe_audio(plan, participant, date_note)
            metadata = ai.session_metadata(
                plan, started=started, started_at_source=date_source, participant=participant
            )
            recordings.append((path, plan, metadata, started))
            continue
        who = participant
        if who is None and len(plan.others) == 1:
            who, _ = normalize_participant(plan.others[0])
        _describe(plan, who, date_note)
        metadata = ti.session_metadata(plan, started=started, started_at_source=date_source, participant=who)
        ready.append((plan, metadata, started))

    total = len(ready) + len(recordings)
    if not args.yes:
        if total:
            sent = ", nothing uploaded" if recordings else ""
            uploads = f" and upload {len(recordings)} recording(s)" if recordings else ""
            print(f"\nNothing written{sent}. Re-run with --yes to import {total} interview(s) "
                  f"into {cfg.sessions_root}{uploads}.")
        return 1 if refused else 0

    project = f" --project {args.project}" if getattr(args, "project", None) else ""
    for plan, metadata, started in ready:
        try:
            session_dir = ti.write_session(cfg.sessions_root, plan, metadata, started=started)
        except OSError as exc:
            print(f"ERROR {plan.file_name}: could not be written ({type(exc).__name__}: {exc})", file=sys.stderr)
            refused += 1
            continue
        print(f"Imported {plan.file_name} as session {session_dir.name} ({len(plan.turns)} turns).")
    if ready:
        print(f"Next: python -m app extract --all{project}")
    if recordings:
        refused += _import_recordings(cfg.sessions_root, recordings, project)
    return 1 if refused else 0


def _import_recordings(sessions_root: Path, recordings: list, project: str) -> int:
    """Write each recording's session and run the file pass on it. Returns how
    many did not get all the way to a transcript."""
    from benchmark.engines import soniox_async

    # The key is checked BEFORE any session is written: a missing one must
    # not leave sessions behind that hold audio and nothing else.
    try:
        client = soniox_async.SonioxAsyncClient.from_env()
    except soniox_async.SonioxAsyncConfigError as exc:
        print(f"ERROR: {exc} No recording was imported.", file=sys.stderr)
        return len(recordings)
    failed = 0
    for path, plan, metadata, started in recordings:
        try:
            session_dir = ai.write_session(sessions_root, path, metadata, started=started)
        except OSError as exc:
            print(f"ERROR {plan.file_name}: could not be written ({type(exc).__name__}: {exc})", file=sys.stderr)
            failed += 1
            continue
        print(f"Imported {plan.file_name} as session {session_dir.name}; running the file pass.")
        if evidence_cli.run_diarize_after(session_dir, client_factory=lambda: client) != 0:
            print(f"The file pass did not finish for {plan.file_name}. Its audio is kept in session "
                  f"{session_dir.name}: retry with `python -m app diarize-after {session_dir.name}{project}`, "
                  f"or drop it with `python -m app forget {session_dir.name}{project}`.", file=sys.stderr)
            failed += 1
            continue
        print(f"Check who is who: python -m app confirm-speakers {session_dir.name}{project} -- then: "
              f"python -m app extract --all{project}")
    return failed
