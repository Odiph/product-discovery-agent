"""The after-meeting evidence pass for an in-person session.

Re-transcribes the retained room audio with a FILE (async) diarized pass --
the more accurate kind -- and cross-checks every turn with the voiceprint:

- each turn's role comes from the after-meeting label, first voice =
  interviewer (the operator opens with the consent line);
- a turn the voiceprint assigns to the OTHER voice is marked `disputed`, not
  silently moved: the operator settles it in `confirm-speakers`.

Writes `evidence.jsonl` (the transcript.jsonl record shape, plus
`speaker_label` and `disputed`) and moves `evidence` to `transcribed`. The room
audio stays until the speakers are confirmed. Vendor-free: the transcriber is
injected (app/main.py builds the real one).
"""

from __future__ import annotations

import math
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from benchmark.engines.diarized import DiarizedSegmenter
from app.session import evidence as ev
from app.stt.roles import SAMPLE_RATE, Embedder, RoleResolver

# Turn cutting for the evidence transcript. The gap is the live default; the
# length cap is longer than live (12 s), which only exists so the coach sees
# a monologue before it ends -- evidence reads better in whole turns.
EVIDENCE_TURN_GAP_S = 0.8
EVIDENCE_TURN_MAX_S = 30.0
BYTES_PER_SAMPLE = 2

Transcribe = Callable[[Path], "list[dict]"]


class EvidencePassError(Exception):
    """The session cannot (or must not) go through the evidence pass."""


def run_evidence_pass(
    session_dir: Path,
    *,
    transcribe: Transcribe,
    embedder: Optional[Embedder],
    engine: str,
    enrol_s: float,
    min_turn_s: float = 1.0,
) -> dict:
    """Returns the `evidence_summary` written to session.json."""
    session_dir = Path(session_dir)
    try:
        meta = ev.read_meta(session_dir)
    except ev.EvidenceStateError as exc:
        raise EvidencePassError(str(exc)) from exc
    room = session_dir / ev.ROOM_AUDIO_FILENAME
    _check_eligible(meta, room)

    # Read (and format-check) the audio BEFORE uploading it: a bad file must
    # fail here, not after a paid pass.
    pcm = _read_pcm(room)
    tokens = transcribe(room)
    segmenter = DiarizedSegmenter(gap_s=EVIDENCE_TURN_GAP_S, max_s=EVIDENCE_TURN_MAX_S, idle_flush_s=math.inf)
    segments = segmenter.feed(tokens, ready_wall_s=0.0, now=0.0) + segmenter.flush(ready_wall_s=0.0)
    # Nothing is written for a pass that cannot be evidence: confirming an
    # empty or unlabelled transcript would delete the only audio there is.
    if not segments:
        raise EvidencePassError("the file pass returned no speech; nothing written, the room audio is kept")
    if all(segment.speaker_label is None for segment in segments):
        raise EvidencePassError(
            "the file pass returned no speaker labels (diarization off?); nothing written, the room audio is kept"
        )

    resolver = RoleResolver(embedder=embedder, enrol_s=enrol_s, min_turn_s=min_turn_s)
    written_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    records, labels = [], {}
    for seq, segment in enumerate(segments, start=1):
        start = segment.speech_start_s if segment.speech_start_s is not None else segment.audio_end_s
        resolution = resolver.resolve(segment, _slice(pcm, start, segment.audio_end_s))
        role = resolver.label_role(segment.speaker_label)
        labels[segment.speaker_label] = labels.get(segment.speaker_label, 0) + 1
        records.append({
            "kind": "segment", "seq": seq, "speaker": role, "text": segment.text,
            # The file pass's own role, never rewritten: confirmation is
            # recomputed from it, so a re-run can never apply a swap twice.
            "pass_speaker": role,
            # Real here (the token start), unlike the live transcript's.
            "audio_start_s": start, "audio_end_s": segment.audio_end_s,
            "ready_wall_s": segment.audio_end_s, "latency_s": 0.0,
            "detected_language": segment.detected_language, "engine": engine, "written_at": written_at,
            "speaker_label": segment.speaker_label, "disputed": resolution.overruled,
        })

    ev.write_lines_atomically(session_dir / ev.EVIDENCE_TRANSCRIPT_FILENAME, records)
    summary = {
        "turns": len(records),
        "disputed": sum(1 for r in records if r["disputed"]),
        "labels": labels,
        "voiceprint": embedder is not None,
        "engine": engine,
        # How much of the recording the transcript reaches; a low figure
        # means the pass lost audio and the operator should know before
        # confirming deletes it.
        "coverage": round(max(r["audio_end_s"] for r in records) / max(len(pcm) / (SAMPLE_RATE * BYTES_PER_SAMPLE), 1e-9), 3),
    }
    ev.update_meta(session_dir, {ev.EVIDENCE_KEY: ev.EVIDENCE_TRANSCRIBED, "evidence_summary": summary})
    return summary


def _check_eligible(meta: dict, room: Path) -> None:
    if meta.get("capture") != "in-person":
        raise EvidencePassError("not an in-person session: its roles come from two separate streams already")
    if "closed_at" not in meta:
        raise EvidencePassError("the session is still recording (or was never closed)")
    if meta.get(ev.EVIDENCE_KEY) == ev.EVIDENCE_CONFIRMED:
        raise EvidencePassError("speakers are already confirmed and the room audio was deleted")
    if not room.is_file():
        raise EvidencePassError(f"no room audio ({ev.ROOM_AUDIO_FILENAME}) in this session")


def _read_pcm(room: Path) -> bytes:
    with wave.open(str(room), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (SAMPLE_RATE, 1, BYTES_PER_SAMPLE):
            raise EvidencePassError(f"{ev.ROOM_AUDIO_FILENAME} is not 16 kHz mono 16-bit")
        return w.readframes(w.getnframes())


def _slice(pcm: bytes, start_s: float, end_s: float) -> bytes:
    first = max(0, int(start_s * SAMPLE_RATE))
    last = max(first, int(end_s * SAMPLE_RATE))
    return pcm[first * BYTES_PER_SAMPLE:last * BYTES_PER_SAMPLE]
