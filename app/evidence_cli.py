"""`diarize-after` and `confirm-speakers`: the after-meeting steps of an
in-person session, between `start --in-person` and `extract`.

    start --in-person   live roles, coaching only; room.wav kept
    diarize-after       file pass + voiceprint cross-check -> evidence.jsonl
    confirm-speakers    the operator says who is who; room.wav deleted
    extract             refuses until confirmed, then reads evidence.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from app.session import evidence as ev

ASYNC_ENGINE_NAME = "soniox-async-diarized"
PREVIEW_PER_ROLE = 4
PREVIEW_TEXT_CHARS = 110
LOW_COVERAGE = 0.8


def add_parsers(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    diarize = subparsers.add_parser(
        "diarize-after",
        help=(
            "In-person sessions: re-transcribe the kept room audio with the slower, more "
            "accurate file pass and cross-check every turn with the voiceprint (needs "
            "SONIOX_API_KEY; the uploaded copy is deleted from the vendor afterwards)"
        ),
    )
    diarize.add_argument("session", help="Session id or a full path to a session directory")
    add_project_argument(diarize)

    confirm = subparsers.add_parser(
        "confirm-speakers",
        help=(
            "In-person sessions: show who said what after `diarize-after`, and confirm it "
            "(deletes the room audio). Without --confirm it only shows."
        ),
    )
    confirm.add_argument("session", help="Session id or a full path to a session directory")
    confirm.add_argument("--confirm", action="store_true", help="record the confirmation (otherwise only show)")
    confirm.add_argument("--swap", action="store_true",
                         help="the first voice was NOT you: exchange interviewer and interviewee everywhere")
    confirm.add_argument("--accept-live-roles", action="store_true",
                         help="no after-meeting pass is possible (an older, crashed, or audio-less session): "
                              "build evidence from the LIVE roles (about 96%% of words right) and delete any room audio")
    confirm.add_argument("--disputed", choices=(ev.DISPUTED_KEEP_LABEL, ev.DISPUTED_VOICEPRINT),
                         help="for turns the voiceprint disputed: keep the file pass's label, or side with the voiceprint")
    add_project_argument(confirm)


def run_diarize_after(session_dir: Path, *, client_factory=None, embedder_loader=None, enrol_s=None) -> int:
    from app.stt import evidence_pass, voiceprint
    from app.main import IN_PERSON_ENROL_S, IN_PERSON_MIN_TURN_S
    from benchmark.engines import soniox_async

    client_factory = client_factory or soniox_async.SonioxAsyncClient.from_env
    embedder_loader = embedder_loader or voiceprint.load_embedder
    try:
        client = client_factory()
    except soniox_async.SonioxAsyncConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    embedder, reason = embedder_loader()
    if embedder is None:
        print(f"WARNING: voiceprint check off ({reason}); no turn can be flagged as disputed.", file=sys.stderr)

    print("Uploading the room audio for the file pass (the vendor copy is deleted afterwards)...")
    try:
        summary = evidence_pass.run_evidence_pass(
            session_dir, transcribe=client.transcribe_file, embedder=embedder,
            engine=ASYNC_ENGINE_NAME, enrol_s=enrol_s if enrol_s is not None else IN_PERSON_ENROL_S, min_turn_s=IN_PERSON_MIN_TURN_S,
        )
    except (evidence_pass.EvidencePassError, soniox_async.SonioxAsyncError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"Evidence transcript written: {summary['turns']} turns, "
        f"{summary['disputed']} disputed by the voiceprint."
    )
    failures = getattr(client, "cleanup_failures", [])
    if failures:
        print(
            "WARNING: the vendor did not confirm deleting: " + ", ".join(failures)
            + ". Delete them from the Soniox console.",
            file=sys.stderr,
        )
    if summary.get("coverage", 1.0) < LOW_COVERAGE:
        print(
            f"WARNING: the transcript reaches only {summary['coverage']:.0%} of the recording. Check it in "
            "`confirm-speakers` before confirming: confirming deletes the audio.",
            file=sys.stderr,
        )
    print(f"Next: python -m app confirm-speakers {session_dir.name}")
    return 0


def run_confirm_speakers(session_dir: Path, args: argparse.Namespace) -> int:
    if args.accept_live_roles:
        if not args.confirm:
            print("ERROR: --accept-live-roles changes the session; add --confirm to do it.", file=sys.stderr)
            return 1
        try:
            ev.accept_live_roles(session_dir)
        except ev.EvidenceStateError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print("Live roles accepted as evidence (about 96% of words right). Any room audio was deleted.")
        print(f"Next: python -m app extract {session_dir.name}")
        return 0
    try:
        preview = ev.speaker_preview(session_dir, per_role=PREVIEW_PER_ROLE)
    except ev.EvidenceStateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not args.confirm:
        _print_preview(preview)
        print("\nNothing changed. If the first voice was you (the consent line), confirm with:")
        flags = f" --disputed {ev.DISPUTED_KEEP_LABEL}|{ev.DISPUTED_VOICEPRINT}" if preview["disputed"] else ""
        print(f"  python -m app confirm-speakers {session_dir.name} --confirm{flags}")
        print("If it was the other person, add --swap.")
        return 0
    try:
        decision = ev.confirm_speakers(session_dir, swap=args.swap, disputed=args.disputed)
    except ev.EvidenceStateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if decision.get("finished_cleanup"):
        print("Speakers were already confirmed; the room audio left by an interrupted run is now deleted.")
        return 0
    print(
        f"Speakers confirmed (swapped: {'yes' if decision['swapped'] else 'no'}; "
        f"{decision['disputed_turns']} disputed turn(s) went to the {decision['disputed']} side). "
        f"Room audio deleted."
    )
    print(f"Next: python -m app extract {session_dir.name}")
    return 0


def _print_preview(preview: "dict[str, list[dict]]") -> None:
    for role in ("interviewer", "interviewee"):
        label = "INTERVIEWER (should be you)" if role == "interviewer" else "INTERVIEWEE"
        print(f"\n{label}:")
        for turn in preview[role]:
            print(_line(turn))
    if preview["disputed"]:
        print(f"\nDISPUTED by the voiceprint ({len(preview['disputed'])}), shown with the file pass's role:")
        for turn in preview["disputed"]:
            print(f"{_line(turn)}   [{turn['speaker']}]")


def _line(turn: dict) -> str:
    minutes, seconds = divmod(int(turn["audio_end_s"]), 60)
    text = turn["text"] if len(turn["text"]) <= PREVIEW_TEXT_CHARS else turn["text"][:PREVIEW_TEXT_CHARS - 1] + "…"
    return f"  [{minutes:02d}:{seconds:02d}] {text}"
