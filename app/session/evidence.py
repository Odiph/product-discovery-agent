"""The after-meeting evidence side of an in-person session: file names, the
`evidence` state machine in session.json, speaker confirmation, and the gate
`extract` reads. Layout and bookkeeping only -- no vendor, no model.

A one-microphone meeting's LIVE speaker roles drive coaching only (measured:
~96% of words right with the voiceprint). Evidence needs better than that, so
the room audio is kept on this laptop until an after-meeting pass has
re-diarized it (`diarize-after`) and the operator has confirmed who is who
(`confirm-speakers`); then it is deleted.

    pending -> transcribed -> confirmed
                  (the room audio is deleted on `confirmed`)
"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from app.session.store import METADATA_FILENAME, TRANSCRIPT_FILENAME, SegmentRecord

# The whole room on one stream: both voices, never one role's audio.
ROOM_AUDIO_STEM = "room"
ROOM_AUDIO_FILENAME = f"{ROOM_AUDIO_STEM}.wav"
# The after-meeting transcript: transcript.jsonl's record shape, with roles
# from the after-meeting pass, plus `speaker_label` and `disputed`.
EVIDENCE_TRANSCRIPT_FILENAME = "evidence.jsonl"

EVIDENCE_KEY = "evidence"
EVIDENCE_PENDING = "pending"
EVIDENCE_TRANSCRIBED = "transcribed"
EVIDENCE_CONFIRMED = "confirmed"

# Set only by `accept_live_roles`: evidence is the live transcript, by the
# operator's explicit choice.
EVIDENCE_SOURCE_KEY = "evidence_source"
EVIDENCE_SOURCE_LIVE = "live-accepted"

# Which side wins a turn the voiceprint disputed.
DISPUTED_KEEP_LABEL = "label"
DISPUTED_VOICEPRINT = "voiceprint"

_ROLES = ("interviewer", "interviewee")
_SEGMENT_FIELDS = frozenset(f.name for f in dataclasses.fields(SegmentRecord))


class EvidenceStateError(Exception):
    """The session is not in a state where this step can run."""


def is_in_person(meta: "dict[str, Any]") -> bool:
    return meta.get("capture") == "in-person"


def is_imported_recording(meta: "dict[str, Any]") -> bool:
    """A recording brought in with `import` (app/session/audio_import.py): it
    takes the in-person road but was never a live meeting, so it has no live
    roles to fall back on."""
    return is_in_person(meta) and bool(meta.get("imported_from"))


def extract_refusal(meta: "dict[str, Any]") -> Optional[str]:
    """Why `extract` must not run on this session yet, or None."""
    if not is_in_person(meta) or meta.get(EVIDENCE_KEY) == EVIDENCE_CONFIRMED:
        return None
    state = meta.get(EVIDENCE_KEY) or "unknown"
    if is_imported_recording(meta):
        return (
            f"this is an imported recording (one audio file, both voices) and its speakers are not "
            f"confirmed (evidence: {state}). Run `confirm-speakers` on it first (after `diarize-after`, "
            f"if the file pass did not finish at import)."
        )
    return (
        f"this is an in-person session (one microphone) and its speakers are not confirmed "
        f"(evidence: {state}). Live roles are for coaching only; run `diarize-after` and then "
        f"`confirm-speakers` on it first (or, when no after-meeting pass is possible, "
        f"`confirm-speakers --confirm --accept-live-roles`)."
    )


def transcript_filename_for(meta: "dict[str, Any]") -> str:
    """The transcript evidence is built from: the confirmed after-meeting one
    for an in-person session, the live one otherwise (including an in-person
    session whose operator accepted the live roles)."""
    if (
        is_in_person(meta)
        and meta.get(EVIDENCE_KEY) == EVIDENCE_CONFIRMED
        and meta.get(EVIDENCE_SOURCE_KEY) != EVIDENCE_SOURCE_LIVE
    ):
        return EVIDENCE_TRANSCRIPT_FILENAME
    return TRANSCRIPT_FILENAME


def segment_fields(records: "Iterable[dict[str, Any]]") -> "list[dict[str, Any]]":
    """Evidence records minus their evidence-only fields, so they load as a
    `SegmentRecord` like any live one."""
    return [{k: v for k, v in r.items() if k in _SEGMENT_FIELDS} for r in records]


def speaker_preview(session_dir: Path, *, per_role: int = 3) -> "dict[str, list[dict]]":
    """The longest few turns of each role, and every disputed turn: enough for
    the operator to recognise their own voice's words."""
    turns = _read_evidence(Path(session_dir))
    preview: "dict[str, list[dict]]" = {}
    for role in _ROLES:
        mine = [t for t in turns if t["speaker"] == role and not t.get("disputed")]
        preview[role] = sorted(sorted(mine, key=lambda t: -len(t["text"]))[:per_role], key=lambda t: t["seq"])
    preview["disputed"] = [t for t in turns if t.get("disputed")]
    return preview


def confirm_speakers(session_dir: Path, *, swap: bool, disputed: Optional[str]) -> "dict[str, Any]":
    """Crash-safe by construction: each turn's role is recomputed from its
    `pass_speaker`, which nothing ever rewrites, so re-running after a crash
    can never apply a swap twice; and a session already confirmed but still
    holding its audio (a crash before the delete) only finishes the delete."""
    session_dir = Path(session_dir)
    meta = read_meta(session_dir)
    state = meta.get(EVIDENCE_KEY)
    if state == EVIDENCE_CONFIRMED:
        if _delete_room_audio(session_dir):
            return {**meta.get("speakers_confirmed", {}), "finished_cleanup": True}
        raise EvidenceStateError("speakers are already confirmed")
    if state != EVIDENCE_TRANSCRIBED:
        raise EvidenceStateError(f"run `diarize-after` on this session first (evidence: {state or 'unknown'})")
    turns = _read_evidence(session_dir)
    if not turns:
        raise EvidenceStateError("the after-meeting transcript is empty: nothing to confirm (the audio was kept)")
    n_disputed = sum(1 for t in turns if t.get("disputed"))
    if n_disputed and disputed not in (DISPUTED_KEEP_LABEL, DISPUTED_VOICEPRINT):
        raise EvidenceStateError(
            f"{n_disputed} disputed turn(s): choose --disputed {DISPUTED_KEEP_LABEL} "
            f"or --disputed {DISPUTED_VOICEPRINT}"
        )

    confirmed = []
    for turn in turns:
        role = turn.get("pass_speaker", turn["speaker"])
        if turn.get("disputed") and disputed == DISPUTED_VOICEPRINT:
            role = _other(role)
        if swap:
            role = _other(role)
        confirmed.append({**turn, "speaker": role})
    write_lines_atomically(session_dir / EVIDENCE_TRANSCRIPT_FILENAME, confirmed)

    decision = {"swapped": swap, "disputed": disputed or DISPUTED_KEEP_LABEL, "disputed_turns": n_disputed}
    update_meta(session_dir, {
        EVIDENCE_KEY: EVIDENCE_CONFIRMED,
        "speakers_confirmed": decision,
        "speakers_confirmed_at": _now(),
    })
    _delete_room_audio(session_dir)
    return decision


def accept_live_roles(session_dir: Path) -> None:
    """The escape hatch, and an explicit operator act: build evidence from the
    LIVE roles (~96% of words right, measured) for an in-person session that
    cannot go through `diarize-after` -- one recorded before the room audio
    was kept, one that crashed, or one whose audio writer failed."""
    session_dir = Path(session_dir)
    meta = read_meta(session_dir)
    if not is_in_person(meta):
        raise EvidenceStateError("not an in-person session: nothing to accept")
    if meta.get(EVIDENCE_KEY) == EVIDENCE_CONFIRMED:
        raise EvidenceStateError("speakers are already confirmed")
    update_meta(session_dir, {
        EVIDENCE_KEY: EVIDENCE_CONFIRMED,
        EVIDENCE_SOURCE_KEY: EVIDENCE_SOURCE_LIVE,
        "speakers_confirmed_at": _now(),
    })
    _delete_room_audio(session_dir)


def _delete_room_audio(session_dir: Path) -> bool:
    """True if there was audio to delete. The only reason it was kept is gone."""
    room = session_dir / ROOM_AUDIO_FILENAME
    existed = room.exists()
    if existed:
        room.unlink()
    update_meta(session_dir, {"audio_retained": False})
    return existed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _other(role: str) -> str:
    return _ROLES[1] if role == _ROLES[0] else _ROLES[0]


def _read_evidence(session_dir: Path) -> "list[dict]":
    path = session_dir / EVIDENCE_TRANSCRIPT_FILENAME
    if not path.is_file():
        raise EvidenceStateError(f"no {EVIDENCE_TRANSCRIPT_FILENAME}: run `diarize-after` on this session first")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_meta(session_dir: Path) -> "dict[str, Any]":
    path = session_dir / METADATA_FILENAME
    if not path.is_file():
        raise EvidenceStateError(f"no {METADATA_FILENAME} in {session_dir}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise EvidenceStateError(f"{METADATA_FILENAME} in {session_dir} is not valid JSON") from exc


def update_meta(session_dir: Path, patch: "dict[str, Any]") -> None:
    path = session_dir / METADATA_FILENAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({**read_meta(session_dir), **patch}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def write_lines_atomically(path: Path, records: "list[dict]") -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    os.replace(tmp, path)
