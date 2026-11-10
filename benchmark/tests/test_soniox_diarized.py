"""Soniox with speaker diarization: the start message and the session's turn cutting.

The two-stream path must not move: its defaults are pinned first, because a
one-microphone meeting needs the OPPOSITE endpoint setting (endpoint detection
cut diarization agreement from 87% to 56% on a real meeting) and a default
flipped by accident would silently degrade every two-stream call.
"""

from __future__ import annotations

import json
import time

from benchmark.engines import soniox


class _Ws:
    def __init__(self, replies=()):
        self.sent = []
        self._replies = list(replies)

    def send(self, payload):
        self.sent.append(payload)

    def recv(self, timeout=None):
        if self._replies:
            return self._replies.pop(0)
        raise TimeoutError

    def close(self):
        pass


def _start(config):
    return json.loads(soniox.build_start_message(config))


def test_the_two_stream_default_is_unchanged_endpoint_on_and_no_diarization():
    payload = _start(soniox.SonioxConfig())
    assert payload["enable_endpoint_detection"] is True
    assert not payload.get("enable_speaker_diarization")


def test_a_diarized_config_turns_diarization_on_and_endpoint_detection_off():
    payload = _start(soniox.SonioxConfig(diarization=True, endpoint_detection=False))
    assert payload["enable_speaker_diarization"] is True
    assert payload["enable_endpoint_detection"] is False


def _session(config, ws=None):
    return soniox._SonioxStreamingSession(ws=ws or _Ws(), config=config, session_start=time.monotonic())


def _msg(*tokens):
    return json.dumps({"tokens": [{"is_final": True, "language": "en", **t} for t in tokens]})


DIAR = soniox.SonioxConfig(diarization=True, endpoint_detection=False, turn_idle_flush_s=0.05)


def test_a_diarized_session_emits_one_segment_per_turn_with_the_engine_speaker_id():
    s = _session(DIAR)
    s.send_audio(b"\x00\x00")
    out = s._handle_message(_msg(
        {"text": "Hi", "start_ms": 0, "end_ms": 300, "speaker": "1"},
        {"text": " there", "start_ms": 300, "end_ms": 600, "speaker": "1"},
        {"text": "Hello", "start_ms": 700, "end_ms": 900, "speaker": "2"},
    ))
    assert [(x.text, x.speaker_label, x.speech_start_s) for x in out] == [("Hi there", "1", 0.0)]


def test_a_diarized_session_releases_the_last_turn_after_a_quiet_poll():
    s = _session(DIAR)
    s.send_audio(b"\x00\x00")
    assert s._handle_message(_msg({"text": "Hi", "start_ms": 0, "end_ms": 300, "speaker": "1"})) == []
    time.sleep(0.08)
    out = s.poll(timeout_s=0.0)
    assert [(x.text, x.speaker_label) for x in out] == [("Hi", "1")]


def test_a_diarized_session_releases_the_open_turn_on_close():
    ws = _Ws(replies=[json.dumps({"tokens": [], "finished": True})])
    s = _session(soniox.SonioxConfig(diarization=True, endpoint_detection=False), ws)
    s.send_audio(b"\x00\x00")
    s._handle_message(_msg({"text": "Bye", "start_ms": 0, "end_ms": 300, "speaker": "2"}))
    out = s.close()
    assert [(x.text, x.speaker_label) for x in out] == [("Bye", "2")]


def test_a_two_stream_session_still_emits_one_segment_per_response_with_no_speaker():
    s = _session(soniox.SonioxConfig())
    s.send_audio(b"\x00\x00")
    out = s._handle_message(_msg({"text": "Hi", "start_ms": 0, "end_ms": 300, "speaker": "1"}))
    assert [(x.text, x.speaker_label) for x in out] == [("Hi", None)]


def test_open_session_keeps_the_diarization_settings_it_was_built_with(monkeypatch):
    """The bug the first real in-person run found: `open_session` rebuilt its
    config from three fields and silently dropped diarization, so every turn of
    a real meeting arrived unlabelled and was filed as the interviewer's. The
    tests above built the session object directly and could not see it."""
    import websockets.sync.client as ws_client

    sent = []

    class _Conn(_Ws):
        def send(self, payload):
            sent.append(payload)

    monkeypatch.setenv("SONIOX_API_KEY", "k")
    monkeypatch.setattr(ws_client, "connect", lambda *a, **kw: _Conn())
    engine = soniox.SonioxEngine(soniox.SonioxConfig(diarization=True, endpoint_detection=False))
    session = engine.open_session(sample_rate=16000)
    start = json.loads(sent[0])
    assert start["enable_speaker_diarization"] is True
    assert start["enable_endpoint_detection"] is False
    assert start["sample_rate"] == 16000
    assert session._segmenter is not None
