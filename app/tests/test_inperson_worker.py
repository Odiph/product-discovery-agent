"""`StreamWorker` with a `RoleResolver`: one diarized stream, two roles out.

In a one-microphone meeting a single worker carries both people. Each turn's
role comes from the resolver, fed the turn's own audio from the worker's ring
-- and a voiceprint that overrules the engine label is recorded as an event
(never with text). Without a resolver nothing about the two-stream path moves.
"""

from __future__ import annotations

import json
import queue

import numpy as np

from app.capture.stream import CaptureFrame
from app.session.store import SessionStore, create_session_dir
from app.stt.live import StreamWorker
from app.stt.roles import RoleResolver
from benchmark.engines.base import Segment

SR = 16000


class _ScriptedSession:
    def __init__(self, segments):
        self._segments = list(segments)
        self.sent = 0

    def send_audio(self, pcm16):
        self.sent += len(pcm16)

    def poll(self, timeout_s=0.0):
        out, self._segments = self._segments, []
        return tuple(out)

    def close(self):
        return ()


class _ScriptedEngine:
    name = "scripted-diarized"

    def __init__(self, segments):
        self.session = _ScriptedSession(segments)

    def open_session(self, *, sample_rate, label=""):
        return self.session


def turn(label, start, end, text="words"):
    return Segment(text=text, audio_end_s=end, ready_wall_s=end + 1, speaker_label=label, speech_start_s=start)


def run_worker(tmp_path, segments, *, audio_seconds, voice_by_second=None, resolver=None):
    store = SessionStore(create_session_dir(tmp_path))
    q: "queue.Queue[CaptureFrame]" = queue.Queue()
    for second in range(audio_seconds):
        value = (voice_by_second or {}).get(second, 0)
        q.put(CaptureFrame(seq=second, pcm16=int(value).to_bytes(2, "little", signed=True) * SR,
                           kind="real", captured_monotonic=0.0))
    engine = _ScriptedEngine(segments)
    worker = StreamWorker(engine=engine, frame_queue=q, store=store, speaker="room",
                          sample_rate=SR, role_resolver=resolver)
    # Deliver every frame before the scripted segments come out, as the real
    # engine does: it finalizes a turn seconds after its audio was sent.
    worker._session = engine.open_session(sample_rate=SR)
    engine.session._held, engine.session._segments = engine.session._segments, []
    while not q.empty():
        worker._send_and_poll(q.get_nowait())
    engine.session._segments = engine.session._held
    worker._send_and_poll(CaptureFrame(seq=-1, pcm16=b"", kind="synthesized", captured_monotonic=0.0))
    store.close()
    records = [json.loads(l) for l in (store.session_dir / "transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    return worker, records


def segments_of(records):
    return [r for r in records if r["kind"] == "segment"]


def test_each_turn_gets_its_role_first_voice_interviewer(tmp_path):
    resolver = RoleResolver(embedder=None, enrol_s=120.0, min_turn_s=1.0)
    _, records = run_worker(tmp_path, [turn("2", 0, 2), turn("1", 2, 4), turn("2", 4, 6)],
                            audio_seconds=6, resolver=resolver)
    assert [r["speaker"] for r in segments_of(records)] == ["interviewer", "interviewee", "interviewer"]


def test_a_diarized_turn_records_its_real_start_not_a_fabricated_one(tmp_path):
    resolver = RoleResolver(embedder=None, enrol_s=120.0, min_turn_s=1.0)
    _, records = run_worker(tmp_path, [turn("1", 1.5, 3.0)], audio_seconds=4, resolver=resolver)
    assert segments_of(records)[0]["audio_start_s"] == 1.5


class _VoiceFromAudio:
    """Embeds by reading the turn's own samples: 1 = me, 2 = them, so the test
    proves the worker handed the resolver the RIGHT slice of audio."""

    def embed(self, pcm16, sample_rate):
        values = set(np.frombuffer(pcm16, dtype="<i2").tolist())
        return np.array([1.0, 0.0]) if values == {1} else np.array([0.0, 1.0])


def test_a_swapped_engine_label_is_overruled_by_the_turns_own_audio_and_recorded(tmp_path):
    resolver = RoleResolver(embedder=_VoiceFromAudio(), enrol_s=4.0, min_turn_s=1.0)
    voices = {0: 1, 1: 1, 2: 2, 3: 2, 5: 2, 6: 2}   # me for 0-2 s, them for 2-4 s, them for 5-7 s
    segments = [turn("1", 0, 2), turn("2", 2, 4), turn("1", 5, 7)]  # the last label is swapped
    worker, records = run_worker(tmp_path, segments, audio_seconds=8, voice_by_second=voices, resolver=resolver)
    assert [r["speaker"] for r in segments_of(records)] == ["interviewer", "interviewee", "interviewee"]
    overrules = [r for r in records if r["kind"] == "event" and r["event"] == "speaker-overruled"]
    assert len(overrules) == 1
    assert "text" not in json.dumps(overrules[0]["detail"])
    assert worker.role_counts == {"voiceprint": 1, "diarization": 2, "overruled": 1}


def test_without_a_resolver_the_worker_speaker_is_written_even_if_the_engine_labels_turns(tmp_path):
    _, records = run_worker(tmp_path, [turn("1", 0, 2), turn("2", 2, 4)], audio_seconds=4)
    assert [r["speaker"] for r in segments_of(records)] == ["room", "room"]
