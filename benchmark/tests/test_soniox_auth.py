"""Soniox WebSocket auth: the key travels in the handshake, never in a frame.

Soniox announced (2026-10-09) that from 2027-01-15 a real-time connection whose
key arrives in the first JSON message is refused with 401. The key must go in
an `Authorization: Bearer` header on the connect itself. Both of this engine's
connections -- the live `open_session` and the file `transcribe` -- open a
socket, so both are pinned here, offline, with a stub `connect`.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from benchmark.engines import soniox


class _Conn:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)

    def recv(self, timeout=None):
        return json.dumps({"tokens": [], "finished": True})

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def connect_calls(monkeypatch):
    import websockets.sync.client as ws_client

    calls = []

    def _connect(*args, **kwargs):
        conn = _Conn()
        calls.append((kwargs, conn))
        return conn

    monkeypatch.setenv("SONIOX_API_KEY", "k-test")
    monkeypatch.setattr(ws_client, "connect", _connect)
    return calls


def _assert_key_in_handshake_only(kwargs, conn):
    assert dict(kwargs["additional_headers"]) == {"Authorization": "Bearer k-test"}
    start = json.loads(conn.sent[0])
    assert "api_key" not in start
    assert all("k-test" not in str(frame) for frame in conn.sent)


def test_the_live_session_sends_its_key_in_the_handshake(connect_calls):
    soniox.SonioxEngine().open_session(sample_rate=16000)
    [(kwargs, conn)] = connect_calls
    _assert_key_in_handshake_only(kwargs, conn)


def test_the_file_pass_sends_its_key_in_the_handshake(connect_calls, monkeypatch):
    monkeypatch.setattr(soniox.audio_mod, "load_audio", lambda *a, **kw: np.zeros(1600, dtype=np.float32))
    soniox.SonioxEngine().transcribe("unused.wav")
    [(kwargs, conn)] = connect_calls
    _assert_key_in_handshake_only(kwargs, conn)


def test_the_start_frame_carries_no_key_at_all():
    assert "api_key" not in json.loads(soniox.build_start_message(soniox.SonioxConfig()))
