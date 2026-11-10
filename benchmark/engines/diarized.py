"""Cut a diarized token stream into turns.

With one microphone and several voices, the engine tags every token with a
speaker id. Diarization needs end-of-turn detection OFF -- measured on a real
one-microphone meeting, turning it on dropped speaker agreement from 87% to
56% -- so no `<end>` marker ever arrives, and the turn boundaries the rest of
the pipeline needs have to come from the tokens themselves:

- the speaker id changes;
- a pause of at least `gap_s` between two tokens;
- the turn has run for `max_s`, so the coach sees a monologue before it ends;
- no new token for `idle_flush_s` of wall time (`tick`), so the last turn
  before a silence is not held back until someone speaks again.

Vendor-agnostic on purpose: tokens are plain dicts with `text`, `start_ms`,
`end_ms`, and optionally `speaker` and `language`.
"""

from __future__ import annotations

from typing import Callable, Optional

from benchmark.engines.base import Segment

ENDPOINT_MARKER_TEXT = "<end>"


def _majority_language(tokens: "list[dict]") -> Optional[str]:
    weights: "dict[str, int]" = {}
    for token in tokens:
        language = token.get("language")
        if language:
            weights[language] = weights.get(language, 0) + len(token.get("text") or "")
    return max(weights, key=weights.get) if weights else None


class DiarizedSegmenter:
    """Stateful: feed finalized tokens in arrival order; turns come out as
    `Segment`s carrying `speaker_label` and `speech_start_s`."""

    def __init__(
        self,
        *,
        gap_s: float,
        max_s: float,
        idle_flush_s: float,
        language_of: Callable[["list[dict]"], Optional[str]] = _majority_language,
    ) -> None:
        self._gap_ms = gap_s * 1000.0
        self._max_ms = max_s * 1000.0
        self._idle_flush_s = idle_flush_s
        self._language_of = language_of
        self._run: "list[dict]" = []
        self._speaker: Optional[str] = None
        self._last_arrival: Optional[float] = None

    def feed(self, tokens: "list[dict]", *, ready_wall_s: float, now: float) -> "list[Segment]":
        out: "list[Segment]" = []
        for token in tokens:
            text = token.get("text") or ""
            if not text or text == ENDPOINT_MARKER_TEXT or token.get("start_ms") is None:
                continue
            speaker = token.get("speaker") or self._speaker
            if self._run and self._closes_run(token, speaker):
                out.extend(self._emit(ready_wall_s))
            if not self._run:
                self._speaker = speaker
            self._run.append(token)
            self._last_arrival = now
        return out

    def tick(self, *, ready_wall_s: float, now: float) -> "list[Segment]":
        if self._run and self._last_arrival is not None and now - self._last_arrival >= self._idle_flush_s:
            return self._emit(ready_wall_s)
        return []

    def flush(self, *, ready_wall_s: float) -> "list[Segment]":
        return self._emit(ready_wall_s) if self._run else []

    def _closes_run(self, token: dict, speaker: Optional[str]) -> bool:
        if speaker is not None and speaker != self._speaker:
            return True
        if token["start_ms"] - self._run[-1]["end_ms"] >= self._gap_ms:
            return True
        return token["end_ms"] - self._run[0]["start_ms"] > self._max_ms

    def _emit(self, ready_wall_s: float) -> "list[Segment]":
        run, self._run = self._run, []
        text = "".join(t["text"] for t in run).strip()
        if not text:
            return []
        return [
            Segment(
                text=text,
                audio_end_s=max(t["end_ms"] for t in run) / 1000.0,
                ready_wall_s=ready_wall_s,
                detected_language=self._language_of(run),
                speaker_label=self._speaker,
                speech_start_s=min(t["start_ms"] for t in run) / 1000.0,
            )
        ]
