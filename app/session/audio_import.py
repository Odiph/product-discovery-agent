"""A past interview's RECORDING, written as a session that awaits the file pass.

A recording is one stream with both voices on it -- the same thing an
in-person meeting leaves behind -- so it takes the same road instead of a
second one: the session is written holding a copy of the audio under the room
audio's name, with `evidence: pending`, and the existing after-meeting steps
(`diarize-after`, then `confirm-speakers`) do the rest. Nothing here
transcribes, and nothing here decides who spoke: the file pass proposes roles
and the operator confirms them, exactly as for a meeting.

Rules, each a decision:

- **Planned, then written.** `plan_audio` only reads; `write_session` writes.
- **One format, checked here.** The file pass reads 16 kHz mono 16-bit WAV
  (app/stt/evidence_pass.py). Anything else is refused BEFORE a session
  exists, with the conversion command, rather than converted by a decoder this
  project does not ship.
- **A copy, never a move.** The operator's file is not touched. The copy is
  deleted when speakers are confirmed, like any room audio.
- **One import per content, the file's NAME only, whole-session atomic** --
  app/session/transcript_import.py's rules, through its writer.
"""

from __future__ import annotations

import hashlib
import shutil
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from app.session import evidence as ev
from app.session import transcript_import as ti
from app.session.participant import PARTICIPANT_KEY

WAV_SUFFIX = ".wav"
# What the file pass reads. app/tests/test_audio_import.py runs an accepted
# file through the real pass, so these cannot drift from it silently.
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
CONVERT_HINT = (
    f"convert it first, for example: ffmpeg -i <recording> -ar {SAMPLE_RATE} -ac {CHANNELS} "
    f"-c:a pcm_s16le <recording>.wav"
)
_HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class AudioPlan:
    file_name: str
    sha256: str
    mtime: float
    size_bytes: int
    duration_s: float


def plan_audio(path: Path) -> AudioPlan:
    """Check one recording and measure it. Raises `ti.ImportRefused`; writes
    nothing and sends nothing."""
    path = Path(path)
    if path.suffix.lower() != WAV_SUFFIX:
        raise ti.ImportRefused(
            f"is a {path.suffix.lower()} recording; only 16 kHz mono 16-bit WAV is read -- {CONVERT_HINT}"
        )
    try:
        with wave.open(str(path), "rb") as audio:
            shape = (audio.getframerate(), audio.getnchannels(), audio.getsampwidth())
            frames = audio.getnframes()
    except (wave.Error, EOFError) as exc:
        raise ti.ImportRefused(f"is not a readable PCM WAV file -- {CONVERT_HINT}") from exc
    except OSError as exc:
        raise ti.ImportRefused(f"cannot be read ({type(exc).__name__})") from exc
    if shape != (SAMPLE_RATE, CHANNELS, SAMPLE_WIDTH_BYTES):
        rate, channels, width = shape
        raise ti.ImportRefused(
            f"is {rate} Hz, {channels} channel(s), {width * 8}-bit; only 16 kHz mono 16-bit WAV is read -- "
            f"{CONVERT_HINT}"
        )
    if frames == 0:
        raise ti.ImportRefused("holds no audio")
    try:
        stat = path.stat()
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ti.ImportRefused(f"cannot be read ({type(exc).__name__})") from exc
    return AudioPlan(
        file_name=path.name,
        sha256=digest.hexdigest(),
        mtime=stat.st_mtime,
        size_bytes=stat.st_size,
        duration_s=frames / float(SAMPLE_RATE),
    )


def session_metadata(
    plan: AudioPlan,
    *,
    started: datetime,
    started_at_source: str,
    participant: Optional[str],
) -> "dict[str, Any]":
    metadata: "dict[str, Any]" = {
        "engine": ti.IMPORT_ENGINE,
        "source": "file-import (audio: wav)",
        "imported_from": plan.file_name,
        ti.HASH_KEY: plan.sha256,
        "imported_at": ti.iso(datetime.now()),
        "started_at": ti.iso(started),
        "started_at_source": started_at_source,
        "closed_at": ti.iso(started + timedelta(seconds=plan.duration_s)),
        # The key the after-meeting steps read: one stream, both voices, roles
        # unconfirmed. A recorded call is that just as a meeting is.
        "capture": "in-person",
        "speaker_source": "diarization-file",
        ev.EVIDENCE_KEY: ev.EVIDENCE_PENDING,
        "audio_retained": True,
        "coach_enabled": False,
    }
    if participant is not None:
        metadata[PARTICIPANT_KEY] = participant
    return metadata


def write_session(
    sessions_root: Path, source: Path, metadata: "dict[str, Any]", *, started: datetime
) -> Path:
    """Write the session (an empty live transcript, the metadata, a copy of
    the recording) and return its directory."""
    return ti.write_session_dir(
        sessions_root,
        metadata,
        started=started,
        # No live pipeline ran: there is no live transcript, and saying so
        # with an empty file is what every reader already tolerates.
        transcript="",
        add_files=lambda directory: shutil.copyfile(source, directory / ev.ROOM_AUDIO_FILENAME),
    )
