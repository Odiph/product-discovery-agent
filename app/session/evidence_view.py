"""What a READER of a session sees: for a confirmed in-person session, the
confirmed after-meeting turns, with the live events re-anchored onto them.

`extract` cites the confirmed turns' seqs (`evidence.jsonl`), and the mirror's
offer highlights do too, so a view that kept showing the live transcript would
point every one of those citations at the wrong words. This is the one place
that builds the view; `render` and the hub's transcript panel read it.

**Two numberings, never merged.** The live transcript numbers segments and
events from ONE shared counter, and the hub stores accepts and rejections by a
suggestion's own seq, so events keep their live seqs. Confirmed turns keep
theirs, because facts cite them. Only the fields that POINT at a turn are
rewritten -- a suggestion's `trigger_seq`, a coverage event's `matched_seq` /
`seq` -- each keeping its live value beside it under a `live_` name.

**One clock.** `room.wav` is written from the same frames the live engine was
fed, so a live turn's `audio_end_s` is a moment in the confirmed transcript
too. It maps to the confirmed turn running at that moment; else the first
ending at or after it (within `ANCHOR_TOLERANCE_S`, since the two passes cut
words a little differently); else the last turn. Unmappable pointers are None.

Nothing on disk is changed; every record returned is a new dict.
"""

from __future__ import annotations

from bisect import bisect_left
from pathlib import Path
from typing import Any, Callable, Optional

from app.session import evidence as ev
from app.session.reader import SessionReadResult, read_session
from app.session.store import TRANSCRIPT_FILENAME

ANCHOR_TOLERANCE_S = 0.5

_DETAIL_SEQ_KEYS = ("matched_seq", "seq")


def _end(record: "dict[str, Any]") -> Optional[float]:
    value = record.get("audio_end_s")
    return float(value) if isinstance(value, (int, float)) else None


def _anchor(live_segments, confirmed_segments) -> "Callable[[Any], Optional[int]]":
    """live seq -> confirmed seq, by the moment the live turn ended; None when
    there is no such moment (not a segment, no end time) or no confirmed turn.

    The turn RUNNING at that moment wins, so a long answer is not lost to a
    backchannel that ended a moment earlier; otherwise the first turn ending
    at or after it (within tolerance); otherwise the last turn."""
    confirmed = sorted((r for r in confirmed_segments if _end(r) is not None), key=_end)
    ends = [_end(r) for r in confirmed]
    live_end = {r.get("seq"): _end(r) for r in live_segments if _end(r) is not None}

    def to_confirmed(live_seq: Any) -> Optional[int]:
        if live_seq not in live_end or not confirmed:
            return None
        moment = live_end[live_seq]
        for record in confirmed:
            start = record.get("audio_start_s")
            if isinstance(start, (int, float)) and start <= moment <= _end(record):
                return record.get("seq")
        index = bisect_left(ends, moment - ANCHOR_TOLERANCE_S)
        return confirmed[min(index, len(confirmed) - 1)].get("seq")

    return to_confirmed


def _re_anchored(record: "dict[str, Any]", to_confirmed) -> "dict[str, Any]":
    """A pointer that cannot be mapped becomes None, never the raw live value:
    read in the confirmed numbering, that would name the wrong words."""
    if record.get("kind") == "suggestion" and "trigger_seq" in record:
        return {**record, "trigger_seq": to_confirmed(record["trigger_seq"]), "live_trigger_seq": record["trigger_seq"]}
    detail = record.get("detail")
    if record.get("kind") == "event" and isinstance(detail, dict):
        patched = dict(detail)
        for key in _DETAIL_SEQ_KEYS:
            if key in detail:
                patched[key] = to_confirmed(detail[key])
                patched[f"live_{key}"] = detail[key]
        return {**record, "detail": patched}
    return dict(record)


def read_view(session_dir: Path) -> SessionReadResult:
    return view_from(Path(session_dir), read_session(Path(session_dir)))


def view_from(session_dir: Path, live: SessionReadResult) -> SessionReadResult:
    """The view, from a live read the caller already holds (render also needs
    the live records: latency is a property of the live run, and the
    confirmed pass stores none)."""
    filename = ev.transcript_filename_for(live.metadata)
    if filename == TRANSCRIPT_FILENAME:
        return live
    confirmed = read_session(Path(session_dir), transcript_filename=filename)
    segments = ev.segment_fields(confirmed.records_of_kind("segment"))
    to_confirmed = _anchor(live.records_of_kind("segment"), segments)
    events = [_re_anchored(r, to_confirmed) for r in live.records if r.get("kind") != "segment"]
    return SessionReadResult(
        records=tuple(segments) + tuple(events),
        truncated_tail=live.truncated_tail if live.truncated_tail is not None else confirmed.truncated_tail,
        closed=live.closed,
        metadata=live.metadata,
    )
