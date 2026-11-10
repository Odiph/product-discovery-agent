"""Browser-facing hardening of the live surface (`app/web/server.py`).

- every HTTP response carries a strict CSP plus nosniff / no-referrer / DENY;
- the pages the CSP covers contain no inline script it would not allow, so the
  policy is something the real pages satisfy, not a header nobody tested;
- a WebSocket whose browser Origin is another site is refused before accept
  (a non-browser client sends no Origin and is still allowed);
- the single mic slot is last-connection-wins: a squatter cannot lock the
  operator's phone out, and the replaced socket never frees the new one's slot.
"""

from __future__ import annotations

import base64
import hashlib
import re
import urllib.error
import urllib.request

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as ws_connect

from app.tests.test_web_serving import STATIC_DIR, _events, _running_server, _store
from app.web import server as web_server
from app.web.hub import ConnectionHub

TOKEN = "hardening-token"
_REQUIRED = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}


def _build(tmp_path, sink=None):
    store = _store(tmp_path)
    app = web_server.create_app(
        token=TOKEN, hub=ConnectionHub(), static_dir=STATIC_DIR, store=store,
        session_id="s", server_started_at="t", audio_sink=sink,
    )
    return app, store


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8"), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, "", {k.lower(): v for k, v in e.headers.items()}


def _csp(headers) -> dict[str, list[str]]:
    policy = {}
    for directive in headers["content-security-policy"].split(";"):
        parts = directive.split()
        if parts:
            policy[parts[0]] = parts[1:]
    return policy


def _inline_script_hashes(html: str) -> set[str]:
    bodies = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.DOTALL)
    # A browser hashes the script text AFTER the HTML parser has normalized
    # CRLF/CR to LF -- and this checkout's index.html is CRLF.
    normalized = (b.replace("\r\n", "\n").replace("\r", "\n") for b in bodies)
    return {
        "'sha256-" + base64.b64encode(hashlib.sha256(b.encode("utf-8")).digest()).decode() + "'"
        for b in normalized
    }


@pytest.mark.parametrize(
    "path",
    [f"/s/{TOKEN}", f"/s/{TOKEN}?mic", f"/s/{TOKEN}/app.js", f"/s/{TOKEN}/style.css",
     f"/s/{TOKEN}/live-state.mjs", f"/s/{TOKEN}/mic.js", f"/s/{TOKEN}/mic-core.mjs",
     "/", "/s/wrong", "/s/wrong/app.js"],
)
def test_every_http_response_carries_the_security_headers(tmp_path, path):
    app, _ = _build(tmp_path, sink=lambda b: None)
    with _running_server(app) as (base, _loop):
        _, _, headers = _get(base + path)
    for name, value in _REQUIRED.items():
        assert headers.get(name) == value, (path, name)
    policy = _csp(headers)
    assert policy["default-src"] == ["'self'"]
    assert policy["frame-ancestors"] == ["'none'"]
    assert policy["base-uri"] == ["'none'"]
    assert policy["form-action"] == ["'none'"]
    assert policy["object-src"] == ["'none'"]
    assert "'unsafe-inline'" not in headers["content-security-policy"]
    assert "'unsafe-eval'" not in headers["content-security-policy"]


def test_connect_src_names_the_pages_own_host_for_both_socket_schemes(tmp_path):
    app, _ = _build(tmp_path)
    with _running_server(app) as (base, _loop):
        _, _, headers = _get(f"{base}/s/{TOKEN}")
    host = base.split("//", 1)[1]
    connect = _csp(headers)["connect-src"]
    assert "'self'" in connect and f"ws://{host}" in connect and f"wss://{host}" in connect


def test_a_hostile_host_header_never_reaches_the_policy(tmp_path):
    app, _ = _build(tmp_path)
    with _running_server(app) as (base, _loop):
        request = urllib.request.Request(f"{base}/s/{TOKEN}", headers={"Host": "evil; script-src *"})
        with urllib.request.urlopen(request, timeout=5) as r:
            csp = r.headers["Content-Security-Policy"]
    assert "evil" not in csp and "script-src *" not in csp


@pytest.mark.parametrize("query", ["", "?mic"])
def test_every_inline_script_on_a_served_page_is_allowed_by_hash_and_nothing_else_inline(tmp_path, query):
    app, _ = _build(tmp_path, sink=lambda b: None)
    with _running_server(app) as (base, _loop):
        _, html, headers = _get(f"{base}/s/{TOKEN}{query}")
    script_src = _csp(headers)["script-src"]
    hashes = _inline_script_hashes(html)
    assert hashes, "the page bootstrap is inline: it must be hash-allowed, or the page is dead"
    assert hashes <= set(script_src)
    # no allowance for inline code the page does not actually contain
    assert {s for s in script_src if s.startswith("'sha256-")} == hashes
    assert not re.search(r"\son[a-z]+\s*=", html, re.IGNORECASE), "inline event handler"
    assert not re.search(r"\sstyle\s*=", html, re.IGNORECASE), "inline style attribute"
    assert "<style" not in html.lower()
    assert _csp(headers)["style-src"] == ["'self'"]


def test_the_mic_bar_loads_its_script_by_src_not_inline(tmp_path):
    app, _ = _build(tmp_path, sink=lambda b: None)
    with _running_server(app) as (base, _loop):
        plain = _get(f"{base}/s/{TOKEN}")[1]
        mic = _get(f"{base}/s/{TOKEN}?mic")[1]
    assert _inline_script_hashes(mic) == _inline_script_hashes(plain)
    assert f'src="/s/{TOKEN}/mic.js"' in mic


def test_only_the_mic_page_may_run_a_blob_worklet(tmp_path):
    # mic.js loads its AudioWorklet from a blob: URL, which script-src governs.
    app, _ = _build(tmp_path, sink=lambda b: None)
    with _running_server(app) as (base, _loop):
        mic = _csp(_get(f"{base}/s/{TOKEN}?mic")[2])["script-src"]
        plain = _csp(_get(f"{base}/s/{TOKEN}")[2])["script-src"]
    assert "blob:" in mic and "blob:" not in plain


# --- WebSocket Origin ------------------------------------------------------------


def _ws(base, path):
    return base.replace("http://", "ws://") + f"/s/{TOKEN}/{path}"


@pytest.mark.parametrize("path", ["ws", "audio"])
def test_a_cross_site_origin_is_refused_before_accept(tmp_path, path):
    got = []
    app, store = _build(tmp_path, sink=got.append)
    with _running_server(app) as (base, _loop):
        with pytest.raises(Exception):
            with ws_connect(_ws(base, path), open_timeout=5, origin="https://evil.example") as c:
                c.send(b"\x01\x00")
                c.recv(timeout=2)
    assert got == []
    assert "mic-connected" not in [e["event"] for e in _events(store)]


@pytest.mark.parametrize("path", ["ws", "audio"])
def test_a_null_origin_is_refused(tmp_path, path):
    app, _ = _build(tmp_path, sink=lambda b: None)
    with _running_server(app) as (base, _loop):
        with pytest.raises(Exception):
            with ws_connect(_ws(base, path), open_timeout=5, origin="null") as c:
                c.recv(timeout=2)


@pytest.mark.parametrize("path", ["ws", "audio"])
def test_the_pages_own_origin_and_no_origin_are_both_allowed(tmp_path, path):
    got = []
    app, _ = _build(tmp_path, sink=got.append)
    with _running_server(app) as (base, _loop):
        for origin in (base, None):
            with ws_connect(_ws(base, path), open_timeout=5, origin=origin) as c:
                if path == "ws":
                    assert c.recv(timeout=5)  # hello
                else:
                    c.send(b"\x01\x00")
    if path == "audio":
        assert got  # at least one frame got through


def test_origin_matches_the_forwarded_host_behind_tailscale_serve():
    assert web_server._origin_allowed("https://laptop.tail1.ts.net", ("127.0.0.1:8000", "laptop.tail1.ts.net"))
    assert web_server._origin_allowed("https://laptop.tail1.ts.net", ("laptop.tail1.ts.net:443",))
    assert web_server._origin_allowed("http://127.0.0.1:8000", ("127.0.0.1:8000",))
    assert not web_server._origin_allowed("http://127.0.0.1:8001", ("127.0.0.1:8000",))
    assert not web_server._origin_allowed("https://laptop.tail1.ts.net.evil.example", ("laptop.tail1.ts.net",))
    assert not web_server._origin_allowed("file://", ("127.0.0.1:8000",))
    assert not web_server._origin_allowed("http://[bad", ("127.0.0.1:8000",))
    assert not web_server._origin_allowed("https://laptop.tail1.ts.net", ())


def test_a_bad_token_is_still_rejected_first_with_its_own_code(tmp_path):
    app, _ = _build(tmp_path, sink=lambda b: None)
    with _running_server(app) as (base, _loop):
        url = base.replace("http://", "ws://") + "/s/wrong/ws"
        with pytest.raises(Exception):
            with ws_connect(url, open_timeout=5, origin="https://evil.example") as c:
                c.recv(timeout=2)


# --- the mic slot: last connection wins -------------------------------------------


def _wait(pred, timeout=5.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def test_a_new_mic_connection_replaces_the_old_one_and_keeps_the_slot(tmp_path):
    got = []
    app, store = _build(tmp_path, sink=got.append)
    with _running_server(app) as (base, _loop):
        with ws_connect(_ws(base, "audio"), open_timeout=5) as squatter:
            squatter.send(b"\x01\x00")
            assert _wait(lambda: got == [b"\x01\x00"])
            with ws_connect(_ws(base, "audio"), open_timeout=5) as phone:
                with pytest.raises(ConnectionClosed) as exc:
                    squatter.recv(timeout=5)
                assert exc.value.rcvd.code == web_server.WS_CLOSE_MIC_REPLACED
                # the replaced socket's cleanup ran, yet the new phone still streams
                assert _wait(lambda: any(
                    e["event"] == "mic-disconnected" and e.get("detail", {}).get("reason") == "replaced"
                    for e in _events(store)
                ))
                phone.send(b"\x02\x00")
                assert _wait(lambda: got[-1] == b"\x02\x00")
                # and a third connection replaces the phone in turn: the slot
                # was still held by the phone, not wrongly released
                with ws_connect(_ws(base, "audio"), open_timeout=5) as third:
                    with pytest.raises(ConnectionClosed) as exc2:
                        phone.recv(timeout=5)
                    assert exc2.value.rcvd.code == web_server.WS_CLOSE_MIC_REPLACED
                    third.send(b"\x03\x00")
                    assert _wait(lambda: got[-1] == b"\x03\x00")
        # all gone: a fresh connection still gets the slot
        with ws_connect(_ws(base, "audio"), open_timeout=5) as again:
            again.send(b"\x04\x00")
            assert _wait(lambda: got[-1] == b"\x04\x00")
