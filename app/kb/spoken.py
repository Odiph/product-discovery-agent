"""Adapters for sources with speaker turns: this tool's own sessions, and
transcripts recorded elsewhere (WebVTT, SRT, and plain `Name: text` exports
such as Otter's, Granola's or a pasted Meet transcript).

A turn's location is its ordinal plus, where the source has one, the time it
ENDED. Sessions use `audio_end_s` only: `audio_start_s` is fabricated by the
live engines, and a timeline built from it is wrong without raising.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from app.kb.document import CONVERSATION, INTERVIEW, Document, Section
from app.session import evidence as ev
from app.session.participant import PARTICIPANT_KEY
from app.session.reader import read_session
from app.session.store import METADATA_FILENAME

_CUE_TIME = re.compile(
    r"(?P<start>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*(?P<end>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)
_VOICE_TAG = re.compile(r"<v(?:\.[^ >]*)?\s+([^>]+)>")
_ANY_TAG = re.compile(r"</?[^>]+>")
# `Name: text` -- a speaker label is short and starts the line. Times in the
# label (`Dana 00:03:12`, `[00:03] Dana`) are tolerated and dropped.
_SPEAKER_LINE = re.compile(
    r"^\s*(?:\[?\(?\d{1,2}:\d{2}(?::\d{2})?\]?\)?\s+)?"
    r"(?P<name>[^\W\d][\w .'\-]{0,38}?)"
    r"(?:\s+\(?\d{1,2}:\d{2}(?::\d{2})?\)?)?\s*:\s+(?P<text>\S.*)$"
)
MIN_SPEAKER_LINES = 3
MAX_SPEAKERS = 12
MAX_ONE_TURN_LABEL_WORDS = 2


class NotASessionError(ValueError):
    pass


def is_session_dir(path: Path) -> bool:
    return path.is_dir() and (path / METADATA_FILENAME).is_file()


def from_session(session_dir: Path) -> Document:
    """One of this tool's interviews. An in-person session is indexed only
    once its speakers are confirmed: before that, its roles are the live
    guesses the evidence pass exists to correct."""
    session_dir = Path(session_dir)
    if not is_session_dir(session_dir):
        raise NotASessionError(f"{session_dir} is not a session directory (no {METADATA_FILENAME})")
    meta = ev.read_meta(session_dir)
    refusal = ev.extract_refusal(meta)
    if refusal is not None:
        raise NotASessionError(f"{session_dir.name}: {refusal}")
    result = read_session(session_dir, transcript_filename=ev.transcript_filename_for(meta))
    turns: "list[tuple[str, str, Optional[float]]]" = []
    for record in result.records_of_kind("segment"):
        text = (record.get("text") or "").strip()
        speaker = record.get("speaker")
        if not text or not speaker:
            continue
        end_s = record.get("audio_end_s")
        if turns and turns[-1][0] == speaker:
            previous = turns[-1]
            turns[-1] = (speaker, f"{previous[1]} {text}", end_s if end_s is not None else previous[2])
        else:
            turns.append((speaker, text, end_s))
    participant = meta.get(PARTICIPANT_KEY)
    date = (meta.get("started_at") or "")[:10] or None
    title = f"Interview with {participant}" if participant else f"Interview {session_dir.name}"
    return Document(
        source_type=INTERVIEW,
        origin=f"session:{session_dir.name}",
        title=title,
        date=date,
        participants=(participant,) if participant else (),
        sections=tuple(
            Section(text=text, location=_turn_location(index, end_s), speaker=speaker)
            for index, (speaker, text, end_s) in enumerate(turns, start=1)
        ),
    )


def from_subtitles(path: Path, text: str) -> Document:
    """WebVTT or SRT. A cue with several `<v>` voices (Teams, Zoom) is split
    per voice; consecutive pieces by the same speaker become one turn. A
    `Name: text` cue is labelled when the label names a person (see
    `_speaker_labels`)."""
    pieces: "list[tuple[Optional[str], str, Optional[float]]]" = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [line for line in block.split("\n") if line.strip()]
        timing = next((i for i, line in enumerate(lines) if _CUE_TIME.search(line)), None)
        if timing is None:
            continue
        end_s = _seconds(_CUE_TIME.search(lines[timing]).group("end"))
        cue = " ".join(lines[timing + 1:]).strip()
        voices = list(_VOICE_TAG.finditer(cue))
        if voices:
            for current, following in zip(voices, voices[1:] + [None]):
                said = cue[current.end():following.start() if following else len(cue)]
                pieces.append((current.group(1).strip(), _ANY_TAG.sub("", said).strip(), end_s))
        else:
            pieces.append((None, _ANY_TAG.sub("", cue).strip(), end_s))
    speakers = _speaker_labels(said for speaker, said, _ in pieces if speaker is None)
    turns: "list[tuple[Optional[str], str, Optional[float]]]" = []
    for speaker, said, end_s in pieces:
        if speaker is None:
            labelled = _SPEAKER_LINE.match(said)
            if labelled and labelled.group("name").strip() in speakers:
                speaker, said = labelled.group("name").strip(), labelled.group("text").strip()
        if not said:
            continue
        if turns and turns[-1][0] == speaker:
            turns[-1] = (speaker, f"{turns[-1][1]} {said}", end_s)
        else:
            turns.append((speaker, said, end_s))
    return _conversation(path, turns)


def _speaker_labels(lines: Iterable[str]) -> "set[str]":
    """The labels that name a PERSON. One that opens several lines does; in a
    file where most lines are labelled, so does any short one-or-two-word
    label (the guest who spoke once). A wrapped `It really is: expensive`
    is neither -- three words, said once -- and stays text."""
    lines = [line for line in lines if line.strip()]
    matches = [m for m in (_SPEAKER_LINE.match(line) for line in lines) if m]
    counts = Counter(m.group("name").strip() for m in matches)
    mostly_labelled = bool(lines) and len(matches) * 2 >= len(lines)
    return {
        name for name, n in counts.items()
        if n >= 2 or (mostly_labelled and len(name.split()) <= MAX_ONE_TURN_LABEL_WORDS)
    }


def looks_like_speaker_transcript(text: str) -> bool:
    """Most lines open with a short label, and the labels RECUR: a few people
    taking turns. Notes full of `Pricing: ...` lines have labels too, but
    each one appears once."""
    lines = [line for line in text.splitlines() if line.strip()][:200]
    labelled = [m for m in (_SPEAKER_LINE.match(line) for line in lines) if m]
    if len(labelled) < MIN_SPEAKER_LINES or len(labelled) * 2 < len(lines):
        return False
    names = Counter(m.group("name").strip().lower() for m in labelled)
    recurring = sum(n for n in names.values() if n >= 2)
    return len(names) <= MAX_SPEAKERS and recurring * 2 >= len(labelled)


def from_speaker_text(path: Path, text: str) -> Document:
    """`Name: text` lines; an unlabelled line continues the previous turn."""
    speakers = _speaker_labels(text.splitlines())
    turns: "list[tuple[Optional[str], str, Optional[float]]]" = []
    for line in text.splitlines():
        if not line.strip():
            continue
        labelled = _SPEAKER_LINE.match(line)
        if labelled and labelled.group("name").strip() in speakers:
            speaker, said = labelled.group("name").strip(), labelled.group("text").strip()
            if turns and turns[-1][0] == speaker:
                turns[-1] = (speaker, f"{turns[-1][1]} {said}", None)
            else:
                turns.append((speaker, said, None))
        elif turns:
            turns[-1] = (turns[-1][0], f"{turns[-1][1]} {line.strip()}", None)
        else:
            turns.append((None, line.strip(), None))
    return _conversation(path, turns)


def _conversation(path: Path, turns: "list[tuple[Optional[str], str, Optional[float]]]") -> Document:
    speakers = []
    for speaker, _, _ in turns:
        if speaker and speaker not in speakers:
            speakers.append(speaker)
    return Document(
        source_type=CONVERSATION,
        origin=str(Path(path).resolve()),
        title=Path(path).stem,
        participants=tuple(speakers),
        sections=tuple(
            Section(text=text, location=_turn_location(index, end_s), speaker=speaker)
            for index, (speaker, text, end_s) in enumerate(turns, start=1)
        ),
    )


def _turn_location(index: int, end_s: Optional[float]) -> str:
    if end_s is None:
        return f"turn {index}"
    minutes, seconds = divmod(int(end_s), 60)
    return f"turn {index} ({minutes:02d}:{seconds:02d})"


def _seconds(stamp: str) -> float:
    parts = stamp.replace(",", ".").split(":")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return total
