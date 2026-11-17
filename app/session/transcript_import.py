"""A past interview's transcript export, written as a session.

The user's earlier interviews exist only as exports (Zoom/Teams `.vtt`, `.srt`,
an Otter/Granola/Meet `Name: text` file), and every post-interview command --
`extract`, `standing`, `themes`, `mirror`, `critique-questions`, `forget` --
reads sessions. This is the bridge, and it is deliberately a WRITER of the
same two files the live store writes, in the same shape, so none of those
commands needs to know an interview was imported.

Rules, each a decision:

- **Parsing is `app/kb/spoken.py`'s**, not a second parser. The knowledge base
  already decides what a speaker label is; two answers would disagree on the
  same file.
- **Planned, then written.** `plan_file` only reads; `write_session` writes.
  The CLI prints the plan (names and counts, never a word anyone said) and
  writes only on `--yes`.
- **Times are honest.** A subtitle cue's times are real, so `audio_start_s` is
  real here too, unlike the live engines'. A text file with no stamps gets
  monotonic synthetic times and `times_synthetic: true` in session.json --
  nothing downstream may read them as when anything was said.
- **One import per content.** The file's SHA-256 is stored; the same bytes
  into the same node again is refused with the existing id. Renaming a file
  does not make it a second interview.
- **The file's NAME only.** Its directory is often a person's or a client's
  name, and the path is not needed to find a duplicate -- the hash is.
- **Whole-session atomic.** Both files are written into a hidden temporary
  directory and renamed into place, so a crash leaves no half-session for
  `extract --all` to pay for.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from app.coach.language import LANGUAGE_ENGLISH, LANGUAGE_HEBREW
from app.kb import spoken
from app.session.participant import PARTICIPANT_KEY
from app.session.store import (
    METADATA_FILENAME,
    TRANSCRIPT_FILENAME,
    SegmentRecord,
    create_session_dir,
)

IMPORT_ENGINE = "import"
INTERVIEWER = "interviewer"
INTERVIEWEE = "interviewee"
SUBTITLE_FORMATS = {".vtt": "vtt", ".srt": "srt"}
TEXT_SUFFIXES = frozenset({".txt", ".md"})
SUPPORTED_SUFFIXES = frozenset(SUBTITLE_FORMATS) | TEXT_SUFFIXES
AUDIO_SUFFIXES = frozenset({
    ".wav", ".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".opus", ".flac", ".webm", ".wma", ".mov",
})
# The same ceiling `kb add` applies: a transcript this size is not a transcript.
MAX_FILE_BYTES = 20_000_000
HASH_KEY = "import_sha256"
_TEMP_PREFIX = ".import-"
_HEBREW_LETTER = re.compile(r"[֐-׿]")
# Synthetic clock: ~150 words a minute, a short gap between turns. Only the
# ORDER is meant to survive; the values are flagged as invented.
_WORDS_PER_SECOND = 2.5
_MIN_TURN_S = 1.0
_TURN_GAP_S = 0.5


class ImportRefused(ValueError):
    """A file this command will not import, with the operator-facing reason.
    Never quotes the file's content."""


@dataclass(frozen=True)
class ImportedTurn:
    speaker_name: str
    role: str
    text: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class FilePlan:
    file_name: str
    format: str
    sha256: str
    mtime: float
    me: str
    """`--me` as the FILE spells it."""
    speaker_turns: "tuple[tuple[str, int], ...]"
    """(name, turns) in order of first appearance."""
    turns: "tuple[ImportedTurn, ...]"
    times_synthetic: bool
    unlabelled_dropped: int

    @property
    def others(self) -> "tuple[str, ...]":
        return tuple(name for name, _ in self.speaker_turns if name != self.me)


def classify(path: Path) -> str:
    """`transcript`, `audio` or `other`, by suffix."""
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_SUFFIXES:
        return "transcript"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    return "other"


def plan_file(path: Path, *, me: str) -> FilePlan:
    """Read and parse one file into the turns it would become. Raises
    `ImportRefused`; writes nothing."""
    path = Path(path)
    kind = classify(path)
    if kind == "audio":
        # The `import` command routes a recording to app/session/audio_import.py
        # before it gets here; this is the answer for any other caller.
        raise ImportRefused("is an audio file, not a transcript export")
    if kind != "transcript":
        raise ImportRefused(
            f"unsupported file type {path.suffix or '(none)'}; supported: "
            f"{', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ImportRefused(f"is larger than {MAX_FILE_BYTES // 1_000_000} MB")
        raw = path.read_bytes()
        mtime = path.stat().st_mtime
    except OSError as exc:
        raise ImportRefused(f"cannot be read ({type(exc).__name__})") from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportRefused("is not UTF-8 text") from exc

    suffix = path.suffix.lower()
    if suffix in SUBTITLE_FORMATS:
        file_format = SUBTITLE_FORMATS[suffix]
        parsed = spoken.subtitle_turns(text)
    else:
        file_format = "text"
        if not spoken.looks_like_speaker_transcript(text):
            raise ImportRefused(
                "does not look like a speaker transcript (most lines should start `Name: ...`, "
                "with the names recurring)"
            )
        parsed = spoken.speaker_text_turns(text)

    labelled = [turn for turn in parsed if turn.speaker]
    if not labelled:
        raise ImportRefused("names no speakers -- there is no way to tell your turns from theirs")
    counts: "dict[str, int]" = {}
    for turn in labelled:
        counts[turn.speaker] = counts.get(turn.speaker, 0) + 1
    me_in_file = _match_speaker(me, counts)
    if me_in_file is None:
        raise ImportRefused(
            f"has no speaker called {me!r} (--me); speakers found: {', '.join(counts)}"
        )
    times, synthetic = _times(labelled, file_format)
    turns = tuple(
        ImportedTurn(
            speaker_name=turn.speaker,
            role=INTERVIEWER if turn.speaker == me_in_file else INTERVIEWEE,
            text=turn.text,
            start_s=start,
            end_s=end,
        )
        for turn, (start, end) in zip(labelled, times)
    )
    return FilePlan(
        file_name=path.name,
        format=file_format,
        sha256=hashlib.sha256(raw).hexdigest(),
        mtime=mtime,
        me=me_in_file,
        speaker_turns=tuple(counts.items()),
        turns=turns,
        times_synthetic=synthetic,
        unlabelled_dropped=len(parsed) - len(labelled),
    )


def _match_speaker(me: str, counts: "dict[str, int]") -> Optional[str]:
    """Case- and space-insensitive: `sam` names `Sam`. Two labels differing
    only in case would be ambiguous, and the FIRST is taken -- in practice the
    exports this reads spell a person one way."""
    wanted = " ".join(me.split()).casefold()
    return next((name for name in counts if " ".join(name.split()).casefold() == wanted), None)


def _times(turns: "list[spoken.Turn]", file_format: str) -> "tuple[list[tuple[float, float]], bool]":
    """(start, end) per turn, and whether they were invented. A file's own
    times are used only when EVERY turn has one and they never run
    backwards; a half-stamped file is synthesized whole rather than mixed,
    because a mix would look measured everywhere and be measured nowhere."""
    if file_format in ("vtt", "srt"):
        spans = [(turn.start_s, turn.end_s) for turn in turns]
        if all(s is not None and e is not None and e >= s for s, e in spans) and _monotonic(
            [s for s, _ in spans]
        ):
            return [(float(s), float(e)) for s, e in spans], False
    else:
        starts = [turn.start_s for turn in turns]
        if all(s is not None for s in starts) and _monotonic(starts):
            spans = []
            for index, (turn, start) in enumerate(zip(turns, starts)):
                following = starts[index + 1] if index + 1 < len(starts) else None
                end = following if following is not None and following > start else start + _duration(turn.text)
                spans.append((float(start), float(end)))
            return spans, False
    spans, cursor = [], 0.0
    for turn in turns:
        end = cursor + _duration(turn.text)
        spans.append((round(cursor, 3), round(end, 3)))
        cursor = end + _TURN_GAP_S
    return spans, True


def _monotonic(values: "list[Optional[float]]") -> bool:
    return all(a <= b for a, b in zip(values, values[1:]))


def _duration(text: str) -> float:
    return max(_MIN_TURN_S, len(text.split()) / _WORDS_PER_SECOND)


def detected_language(text: str) -> str:
    """The ISO code the live engines write: `he` when the turn has any Hebrew
    letter, `en` otherwise. The record's tag only -- the coach never reads it
    (`app/coach/language.py`)."""
    return LANGUAGE_HEBREW if _HEBREW_LETTER.search(text) else LANGUAGE_ENGLISH


def find_duplicate(sessions_root: Path, sha256: str) -> Optional[str]:
    """The id of a session at this node already imported from these bytes."""
    root = Path(sessions_root)
    if not root.is_dir():
        return None
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(_TEMP_PREFIX):
            continue
        try:
            meta = json.loads((entry / METADATA_FILENAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and meta.get(HASH_KEY) == sha256:
            return entry.name
    return None


def iso(moment: datetime) -> str:
    # The live store's `_now_iso` shape: local offset, milliseconds.
    return moment.astimezone().isoformat(timespec="milliseconds")


def session_metadata(
    plan: FilePlan,
    *,
    started: datetime,
    started_at_source: str,
    participant: Optional[str],
) -> "dict[str, Any]":
    duration_s = plan.turns[-1].end_s if plan.turns else 0.0
    metadata: "dict[str, Any]" = {
        "engine": IMPORT_ENGINE,
        "source": f"file-import (transcript: {plan.format})",
        "imported_from": plan.file_name,
        HASH_KEY: plan.sha256,
        "imported_at": iso(datetime.now()),
        "started_at": iso(started),
        "started_at_source": started_at_source,
        "closed_at": iso(started + timedelta(seconds=duration_s)),
        "times_synthetic": plan.times_synthetic,
        "speaker_roles": {
            name: INTERVIEWER if name == plan.me else INTERVIEWEE for name, _ in plan.speaker_turns
        },
        "audio_retained": False,
        "coach_enabled": False,
    }
    if participant is not None:
        metadata[PARTICIPANT_KEY] = participant
    return metadata


def write_session(sessions_root: Path, plan: FilePlan, metadata: "dict[str, Any]", *, started: datetime) -> Path:
    """Write the session and return its directory. The id is minted from
    `started`, disambiguated like a live one."""
    written_at = iso(datetime.now())
    lines = []
    for seq, turn in enumerate(plan.turns):
        record = SegmentRecord(
            kind="segment",
            seq=seq,
            speaker=turn.role,
            text=turn.text,
            # REAL for a subtitle file (the cue's start), synthetic
            # otherwise and flagged in session.json -- gate 35 names this
            # module as a writer for that reason.
            audio_start_s=turn.start_s,
            audio_end_s=turn.end_s,
            # No pipeline ran: ready the moment it ended, zero latency.
            ready_wall_s=turn.end_s,
            latency_s=0.0,
            detected_language=detected_language(turn.text),
            engine=IMPORT_ENGINE,
            written_at=written_at,
        )
        lines.append(json.dumps(asdict(record), ensure_ascii=False))
    return write_session_dir(sessions_root, metadata, started=started, transcript="".join(line + "\n" for line in lines))


def write_session_dir(
    sessions_root: Path,
    metadata: "dict[str, Any]",
    *,
    started: datetime,
    transcript: str,
    add_files: Optional[Callable[[Path], None]] = None,
) -> Path:
    """The whole-session atomic write every import shares: the transcript, the
    metadata and whatever `add_files` puts beside them go into a hidden
    temporary directory that is renamed into place."""
    root = Path(sessions_root)
    root.mkdir(parents=True, exist_ok=True)
    final_dir = create_session_dir(root, started)
    temp_dir = root / f"{_TEMP_PREFIX}{final_dir.name}.tmp"
    if temp_dir.exists():
        # Only ever an import's own leftover from a crash mid-write.
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    try:
        if add_files is not None:
            add_files(temp_dir)
        _write_synced(temp_dir / TRANSCRIPT_FILENAME, transcript)
        _write_synced(temp_dir / METADATA_FILENAME, json.dumps(metadata, indent=2, ensure_ascii=False))
        os.replace(temp_dir, final_dir)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return final_dir


def _write_synced(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
