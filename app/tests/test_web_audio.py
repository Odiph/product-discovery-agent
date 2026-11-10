"""The phone's microphone channel for in-person meetings: `/s/{t}?mic` and `/s/{t}/audio`.

Everything here exists only when the server is built with an `audio_sink`
(`start --in-person`). A two-stream run's phone page stays receive-only: no
capture script, no audio route. The audio socket is BINARY ONLY and bounded,
because it is the one route a client can push data into the laptop through:
text is ignored, a frame that is not whole 16-bit samples or is over the size
cap is refused, and only one phone may stream at a time -- two phones would
interleave two rooms into one transcript.
"""

from __future__ import annotations

import time
import urllib.request

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as ws_connect

from app.web import server as web_server
from app.web.hub import ConnectionHub
from app.tests.test_web_serving import STATIC_DIR, _events, _running_server, _store

TOKEN = "mic-token"


def build(tmp_path, sink=None):
    store = _store(tmp_path)
    app = web_server.create_app(
        token=TOKEN, hub=ConnectionHub(), static_dir=STATIC_DIR, store=store,
        session_id="s", server_started_at="t", audio_sink=sink,
    )
    return app, store


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8"), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, "", ""


def wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def test_a_two_stream_server_has_no_capture_page_script_or_audio_route(tmp_path):
    app, _ = build(tmp_path)
    with _running_server(app) as (base, _loop):
        status, body, _ = get(f"{base}/s/{TOKEN}?mic")
        assert status == 200 and "mic.js" not in body and "mic-region" not in body
        assert get(f"{base}/s/{TOKEN}/mic.js")[0] == 404
        assert get(f"{base}/s/{TOKEN}/mic-core.mjs")[0] == 404
        with pytest.raises(Exception):
            with ws_connect(base.replace("http://", "ws://") + f"/s/{TOKEN}/audio", open_timeout=5) as c:
                c.recv(timeout=2)


def test_an_in_person_server_adds_the_mic_bar_only_on_the_mic_page(tmp_path):
    app, _ = build(tmp_path, sink=lambda b: None)
    with _running_server(app) as (base, _loop):
        plain = get(f"{base}/s/{TOKEN}")[1]
        mic = get(f"{base}/s/{TOKEN}?mic")[1]
        assert "mic-region" not in plain and "mic.js" not in plain
        assert 'id="mic-region"' in mic and "/mic.js" in mic
        status, js, ctype = get(f"{base}/s/{TOKEN}/mic.js")
        assert status == 200 and "javascript" in ctype
        assert get(f"{base}/s/{TOKEN}/mic-core.mjs")[0] == 200
        assert get(f"{base}/s/wrong-token/mic.js")[0] == 404


def _audio_url(base, token=TOKEN):
    return base.replace("http://", "ws://") + f"/s/{token}/audio"


def test_binary_frames_reach_the_sink_in_order_and_text_is_ignored(tmp_path):
    got = []
    app, store = build(tmp_path, sink=got.append)
    with _running_server(app) as (base, _loop):
        with ws_connect(_audio_url(base), open_timeout=5) as c:
            c.send(b"\x01\x00\x02\x00")
            c.send("not audio")
            c.send(b"\x03\x00")
            assert wait_for(lambda: len(got) == 2)
        assert got == [b"\x01\x00\x02\x00", b"\x03\x00"]
        assert wait_for(lambda: any(e["event"] == "mic-disconnected" for e in _events(store)))
    events = [e["event"] for e in _events(store)]
    assert "mic-connected" in events


@pytest.mark.parametrize(
    "frame",
    [b"\x01\x02\x03", b"\x00" * (web_server.MAX_AUDIO_FRAME_BYTES + 2)],
    ids=["half-a-sample", "over-the-cap"],
)
def test_a_frame_that_is_not_whole_samples_or_is_over_the_cap_is_refused(tmp_path, frame):
    got = []
    app, _ = build(tmp_path, sink=got.append)
    with _running_server(app) as (base, _loop):
        with ws_connect(_audio_url(base), open_timeout=5, max_size=None) as c:
            c.send(frame)
            with pytest.raises(ConnectionClosed):
                c.recv(timeout=5)
    assert got == []


def test_only_one_phone_may_stream_at_a_time(tmp_path):
    got = []
    app, _ = build(tmp_path, sink=got.append)
    with _running_server(app) as (base, _loop):
        with ws_connect(_audio_url(base), open_timeout=5) as first:
            first.send(b"\x01\x00")
            assert wait_for(lambda: got == [b"\x01\x00"])
            with ws_connect(_audio_url(base), open_timeout=5) as second:
                with pytest.raises(ConnectionClosed) as exc:
                    second.recv(timeout=5)
                assert exc.value.rcvd.code == web_server.WS_CLOSE_MIC_BUSY
        # the slot frees when the first phone leaves
        assert wait_for(lambda: True)
        with ws_connect(_audio_url(base), open_timeout=5) as again:
            again.send(b"\x02\x00")
            assert wait_for(lambda: got[-1] == b"\x02\x00")


def test_a_wrong_token_never_reaches_the_sink(tmp_path):
    got = []
    app, _ = build(tmp_path, sink=got.append)
    with _running_server(app) as (base, _loop):
        with pytest.raises(Exception):
            with ws_connect(_audio_url(base, "wrong"), open_timeout=5) as c:
                c.send(b"\x01\x00")
                c.recv(timeout=2)
    assert got == []
