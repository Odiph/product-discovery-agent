"""The ASGI app factory and the uvicorn embedding (03-01-PLAN.md §P2, §P7;
03-CONTEXT.md D-05). The one invariant this module exists to protect: the
asyncio event loop hosting uvicorn runs on the MAIN thread -- capture and STT
stay exactly where they already are, as plain background OS threads
(03-RESEARCH.md §1). Since uvicorn 0.13.0, `Server.install_signal_handlers()`
is a no-op off the main thread (Python itself only allows signal handlers on
the main thread of the main interpreter) -- so if this module's server were
ever run from a background thread, Ctrl-C would silently stop being handled
by it. `run_start` in `app/main.py` is the only caller that constructs and
drives the server returned here, and it does so via its own top-level
`asyncio.run()`, never a nested one.

Every route lives beneath `/s/<token>` (D-05) -- there is no unauthenticated
static mount. A wrong or absent token gets a generic 404 that echoes nothing,
compared in constant time via `secrets.compare_digest` (never `==`, which
leaks a timing side-channel for free). The four static assets are read from
disk exactly ONCE, at factory time, into memory -- a synchronous file read
inside an `async def` handler would stall the entire event loop and therefore
freeze every connected client at once (03-RESEARCH.md §1 Pitfall 1).

03-02-PLAN.md Task 1: `ACCEPTED_CLIENT_MESSAGE_TYPES` and `SERVER_MESSAGE_TYPES`
are the whole protocol surface, pinned as module-level constants and asserted
equal by set equality in `app/tests/test_web_reconnect.py` -- this is what
permanently forbids a resume/backfill request (D-01), a client-reported gap
(D-02), and a two-way control channel (deferred per 03-CONTEXT.md) from ever
being silently reintroduced. The heartbeat (`ping`/`pong`) is the ONLY
client->server message this protocol has, or is ever meant to have.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, Response

from app import config as config_mod
from app.session.store import SessionStore
from app.web.hub import ConnectionHub, hello_payload
from app.web.status import StatusBoard, status_message

logger = logging.getLogger(__name__)

_NOT_FOUND = PlainTextResponse("Not Found", status_code=404)

# WebSocket close code used to reject a bad token BEFORE ever accepting the
# connection -- so a rejected socket never enters the hub's active set
# (D-05). 4404 is in the app-defined range (4000-4999) per RFC 6455 §7.4.2.
_WS_CLOSE_BAD_TOKEN = 4404

# The message type literals, defined ONCE here and imported by
# `app/static/live-state.mjs`'s test (`app/tests/test_web_reconnect.py`
# imports both and asserts the literal that both sides consume comes from
# one place, never typed twice and hoped about).
MESSAGE_TYPE_HELLO = "hello"
MESSAGE_TYPE_PING = "ping"
MESSAGE_TYPE_PONG = "pong"
MESSAGE_TYPE_SEGMENT = "segment"
MESSAGE_TYPE_SERVER_STATUS = "server_status"
# 04-03-PLAN.md §E1: the protocol grows by exactly one message, deliberately.
# A ranked suggestion set (app/coach/pipeline.py's on_ranked callback, wired
# in app/main.py) reaches the phone through this ONE new type. Adding it here
# without also updating SERVER_MESSAGE_TYPES below AND gate 8's own assertion
# in the SAME commit is the intended friction (§E1) -- the protocol surface
# grows by decision, never by drift.
MESSAGE_TYPE_SUGGESTION = "suggestion"
# Phase C: the protocol grows by exactly one more message, deliberately, and
# under the same friction as the line above -- adding it here without also
# updating SERVER_MESSAGE_TYPES, gate 8's assertion, and the two other
# set-equality assertions that pin this surface (test_web_reconnect.py,
# test_web_suggestion.py) in the SAME commit fails the suite.
#
# This is the one server->client message that carries no model output. It is
# computed from the authored survey plus coverage state, so it is the only
# thing the surface can show that cannot be delayed or emptied by a slow or
# failing vendor call.
MESSAGE_TYPE_SURVEY = "survey"

# The ENTIRE client->server protocol surface (D-01/D-02/03-CONTEXT.md's
# deferred two-way control channel). Asserted as SET EQUALITY, not a
# "contains" check and not a negative grep for forbidden vocabulary --
# equality is what catches a field nobody thought to forbid, and cannot be
# invalidated by a comment the way a negative grep can (T-03-14, T-03-15).
#
# 04-03-PLAN.md §E1: deliberately UNTOUCHED by the suggestion message above.
# D-01's no-replay rule and the deferred two-way control channel (dismiss/pin
# a suggestion from the phone) both depend on this set staying exactly the
# heartbeat -- adding a suggestion type is a server->client change ONLY.
ACCEPTED_CLIENT_MESSAGE_TYPES = frozenset({MESSAGE_TYPE_PING})

# The ENTIRE server->client protocol surface.
SERVER_MESSAGE_TYPES = frozenset(
    {
        MESSAGE_TYPE_HELLO,
        MESSAGE_TYPE_PONG,
        MESSAGE_TYPE_SEGMENT,
        MESSAGE_TYPE_SERVER_STATUS,
        MESSAGE_TYPE_SUGGESTION,
        MESSAGE_TYPE_SURVEY,
    }
)


def _parse_client_message(raw: str) -> Optional[dict[str, Any]]:
    """Returns the parsed message dict if -- and only if -- `raw` is valid
    JSON, is a JSON object, and its `type` is one of
    `ACCEPTED_CLIENT_MESSAGE_TYPES`. Returns `None` for anything else:
    malformed JSON, a non-object payload, or an unrecognized `type` -- all
    ignored without raising and without ever logging the content (S7,
    T-03-14)."""
    try:
        message = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(message, dict):
        return None
    if message.get("type") not in ACCEPTED_CLIENT_MESSAGE_TYPES:
        return None
    return message


class PortInUseError(Exception):
    """Raised when the pinned port is already bound by another process. The
    message names the port and how to change it -- never a silent fallback to
    a different port, which would desynchronize the printed/QR'd join URL
    from what is actually listening (03-RESEARCH.md §4, OPS-05)."""


def check_port_available(port: int, *, host: str = "0.0.0.0") -> None:
    """Raises `PortInUseError` if `port` cannot be bound on `host` right now.
    Called before `uvicorn.Config`/`uvicorn.Server` are constructed, so a
    taken port is a typed, actionable error rather than something the caller
    has to parse out of an uvicorn log line."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError as exc:
        raise PortInUseError(
            f"port {port} is already in use -- is another session already running? "
            f"Set APP_PORT to use a different one."
        ) from exc
    finally:
        probe.close()


# In-person mode only (`start --in-person`): the phone's microphone channel.
# One binary frame is at most ~2 s of 16 kHz mono PCM16; anything larger, or
# not whole 16-bit samples, closes the socket. This is the one route a client
# can push data into the laptop through, so it is bounded.
MAX_AUDIO_FRAME_BYTES = 65536
# Last connection wins: a newer mic socket closes the older one with this
# code, which mic.js treats as final (retrying would steal the mic back and
# the two phones would take turns forever).
WS_CLOSE_MIC_REPLACED = 4410
_WS_CLOSE_BAD_AUDIO = 1003
_MIC_PAGE_MARKER = b"</body>"
# Appended to the live page for `/s/{t}?mic`, and ONLY there: a two-stream
# run's page never carries a capture script (gate 2). The script is loaded by
# src, not by an inline loader, so the CSP needs no hash for it; the token is
# known at factory time, which is what makes an absolute src possible.
_MIC_BAR_HTML = (
    '<div id="mic-region" class="mic-region">'
    '<button id="mic-button" type="button">Start recording</button>'
    '<span id="mic-status" class="mic-status" dir="ltr">Say the consent line first: '
    'the first voice is taken to be you.</span>'
    '<span id="mic-level" class="mic-level"></span></div>'
    '<script type="module" src="/s/{token}/mic.js"></script>'
)

# A browser-sent Origin that is not this page's own host: refused before
# accept, like a bad token, but with its own code so the two are told apart.
_WS_CLOSE_BAD_ORIGIN = 4403

# --- browser hardening headers ------------------------------------------------
#
# Every page script is same-origin; the one inline script (index.html's
# bootstrap, which derives the token path from the URL) is allowed by its
# hash, computed from the bytes actually served, so nothing else inline runs.
# No inline style or event-handler attribute exists, so style-src stays 'self'.
_STATIC_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
)
_INLINE_SCRIPT = re.compile(rb"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
# Only a plain host[:port] (or bracketed IPv6) is ever echoed into the policy:
# the Host header is client-controlled.
_SAFE_HOST = re.compile(r"^(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?::\d{1,5})?$")


def _inline_script_hashes(html: bytes) -> "tuple[str, ...]":
    # The HTML parser normalizes CRLF/CR to LF before the browser hashes a
    # script's text, so hash what the browser will see, not the file's bytes.
    hashes = []
    for body in _INLINE_SCRIPT.findall(html):
        text = body.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest = base64.b64encode(hashlib.sha256(text).digest()).decode("ascii")
        hashes.append(f"'sha256-{digest}'")
    return tuple(dict.fromkeys(hashes))


def content_security_policy(host: Optional[str], script_extra: "Sequence[str]" = ()) -> str:
    # 'self' covers same-origin ws/wss in current browsers; the explicit
    # scheme+host entries are for older WebKit, which did not.
    connect = ["'self'"]
    if host and _SAFE_HOST.match(host):
        connect += [f"ws://{host}", f"wss://{host}"]
    directives = (
        "default-src 'self'",
        "script-src " + " ".join(("'self'", *script_extra)),
        "style-src 'self'",
        "img-src 'self'",
        "connect-src " + " ".join(connect),
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    )
    return "; ".join(directives)


def _scope_header(scope: dict, name: bytes) -> Optional[str]:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


class _SecurityHeaders:
    """Pure ASGI (not BaseHTTPMiddleware): adds the hardening headers to every
    HTTP response, the 404s included, and leaves WebSocket traffic alone. A
    route that set its own CSP (the page, which needs its script hashes)
    keeps it; everything else gets the hash-free default."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        default_csp = content_security_policy(_scope_header(scope, b"host")).encode("ascii")

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", ()))
                present = {key.lower() for key, _ in headers}
                headers += [(k, v) for k, v in _STATIC_HEADERS if k not in present]
                if b"content-security-policy" not in present:
                    headers.append((b"content-security-policy", default_csp))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _host_port(netloc_or_url: str, default_port: int) -> "Optional[tuple[str, int]]":
    parts = urlsplit(netloc_or_url if "//" in netloc_or_url else "//" + netloc_or_url)
    try:
        port = parts.port
    except ValueError:
        return None
    if not parts.hostname:
        return None
    return parts.hostname.lower(), port or default_port


def _origin_allowed(origin: str, hosts: "Sequence[str]") -> bool:
    """True when a browser's Origin names one of the hosts this request was
    addressed to. `hosts` is Host plus any X-Forwarded-Host: behind `tailscale
    serve` the proxy may present either. Trusting a forwarded header costs
    nothing here -- a page cannot set it on a WebSocket, and a non-browser
    client can simply omit Origin anyway."""
    try:
        scheme = urlsplit(origin).scheme
    except ValueError:
        return False
    if scheme not in ("http", "https"):
        return False  # includes the opaque "null" origin
    default_port = 443 if scheme == "https" else 80
    target = _host_port(origin, default_port)
    if target is None:
        return False
    return any(_host_port(host.strip(), default_port) == target for host in hosts if host.strip())


def _websocket_origin_ok(websocket: WebSocket) -> bool:
    # No Origin: not a browser (the CLI tests, a curl); the token still gates it.
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    hosts = [websocket.headers.get("host") or ""]
    hosts += (websocket.headers.get("x-forwarded-host") or "").split(",")
    return _origin_allowed(origin, hosts)


@dataclass(frozen=True)
class _StaticAssets:
    index_html: bytes
    style_css: bytes
    app_js: bytes
    live_state_mjs: bytes
    # Loaded only for an in-person run: a two-stream server never reads them.
    mic_js: bytes = b""
    mic_core_mjs: bytes = b""


def _load_static_assets(static_dir: Path, *, include_mic: bool = False) -> _StaticAssets:
    """Reads the four static assets from disk exactly once. No request
    handler below ever touches the filesystem -- every response below is
    served from these in-memory bytes."""
    return _StaticAssets(
        index_html=(static_dir / "index.html").read_bytes(),
        style_css=(static_dir / "style.css").read_bytes(),
        app_js=(static_dir / "app.js").read_bytes(),
        live_state_mjs=(static_dir / "live-state.mjs").read_bytes(),
        mic_js=(static_dir / "mic.js").read_bytes() if include_mic else b"",
        mic_core_mjs=(static_dir / "mic-core.mjs").read_bytes() if include_mic else b"",
    )


def create_app(
    *,
    token: str,
    hub: ConnectionHub,
    static_dir: Path,
    store: SessionStore,
    session_id: str,
    server_started_at: str,
    status_board: Optional["StatusBoard"] = None,
    survey_provider: Optional["Callable[[], Optional[dict[str, Any]]]"] = None,
    project: Optional[str] = None,
    grounding_sources: "Sequence[str]" = (),
    coach_enabled: bool = False,
    heartbeat_interval_ms: int = config_mod.DEFAULT_HEARTBEAT_INTERVAL_MS,
    heartbeat_timeout_ms: int = config_mod.DEFAULT_HEARTBEAT_TIMEOUT_MS,
    reconnect_backoff_base_ms: int = config_mod.DEFAULT_RECONNECT_BACKOFF_BASE_MS,
    reconnect_backoff_cap_ms: int = config_mod.DEFAULT_RECONNECT_BACKOFF_CAP_MS,
    audio_sink: "Optional[Callable[[bytes], None]]" = None,
) -> FastAPI:
    """Builds the ASGI app. Registers exactly five routes, all beneath the
    per-run token: the page, the three assets, and the socket. No other route
    ever serves anything -- a catch-all falls through to a generic 404 that
    echoes nothing (D-05).

    `status_board` defaults to a fresh, healthy `StatusBoard` when omitted
    (e.g. in tests that don't exercise 03-02's server-status path);
    `app/main.py`'s real call site passes the ONE board instance its status
    poller also writes to, so a fresh connect and a poll both read the same
    "last known status" (§Q6/§Q7).

    `coach_enabled` says whether a coach ACTUALLY came up on this run -- not
    whether one was asked for. It defaults to `False`, which is the honest
    default for a server built without one, and it is the value a client uses
    to decide whether to promise suggestions at all. The live caller cannot
    forget it: gate 31 pins `app/main.py`'s call keyword set by equality
    against this signature, which is why a default here is safe where the
    same default on `hub.hello_payload` would not be -- that function is the
    wire projection itself, and a wrong value there renders a wrong panel with
    nothing downstream to catch it.

    `survey_provider` (Phase C) is called on every fresh connect and returns
    an already-projected `survey` wire payload, or `None` when there is no
    survey to report (`--no-serve` never reaches here; a key-less run has no
    coach and therefore no coverage state). It returns the PAYLOAD rather
    than the survey and coverage state themselves so this module keeps
    importing nothing from `app.coach` -- `app/web/hub.py` stays the only
    place that projects anything onto the wire, and `app/main.py` stays the
    single injection point. Pushed alongside `hello` for the same reason the
    server status is: a browser that joins mid-interview, or reconnects after
    a sleep, must be correct immediately rather than at the next coverage
    change (which may be minutes away, or never)."""
    assets = _load_static_assets(static_dir, include_mic=audio_sink is not None)
    board = status_board if status_board is not None else StatusBoard()
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    def _token_matches(candidate: str) -> bool:
        # `secrets.compare_digest` on two `str` requires ASCII on both
        # sides -- Starlette percent-decodes path params, so a non-ASCII
        # candidate (Hebrew is plausible on this project, D-04) would
        # otherwise raise `TypeError` here, producing an HTTP 500 (a
        # observable deviation from D-05's uniform-404 posture) instead of
        # the same generic rejection a wrong-but-ASCII token gets. A
        # non-ASCII candidate can never equal the token (tokens are
        # generated from an ASCII alphabet, D-05), so short-circuiting to
        # "no match" here is correct, not just safe.
        if not candidate.isascii():
            return False
        return secrets.compare_digest(candidate, token)

    app.add_middleware(_SecurityHeaders)
    mic_bar = _MIC_BAR_HTML.replace("{token}", quote(token, safe="")).encode("utf-8")
    mic_page = assets.index_html.replace(_MIC_PAGE_MARKER, mic_bar + _MIC_PAGE_MARKER, 1)
    page_hashes = _inline_script_hashes(assets.index_html)
    # mic.js builds its AudioWorklet from a blob: URL, which script-src
    # governs; only the mic page is granted it.
    mic_hashes = (*_inline_script_hashes(mic_page), "blob:")

    @app.get("/s/{candidate_token}")
    async def get_page(candidate_token: str, request: Request) -> Response:
        if not _token_matches(candidate_token):
            return _NOT_FOUND
        wants_mic = audio_sink is not None and "mic" in request.query_params
        csp = content_security_policy(request.headers.get("host"), mic_hashes if wants_mic else page_hashes)
        return Response(
            content=mic_page if wants_mic else assets.index_html,
            media_type="text/html",
            headers={"Cache-Control": "no-store", "Content-Security-Policy": csp},
        )

    @app.get("/s/{candidate_token}/app.js")
    async def get_app_js(candidate_token: str) -> Response:
        if not _token_matches(candidate_token):
            return _NOT_FOUND
        return Response(
            content=assets.app_js,
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/s/{candidate_token}/style.css")
    async def get_style_css(candidate_token: str) -> Response:
        if not _token_matches(candidate_token):
            return _NOT_FOUND
        return Response(
            content=assets.style_css,
            media_type="text/css",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/s/{candidate_token}/live-state.mjs")
    async def get_live_state_mjs(candidate_token: str) -> Response:
        if not _token_matches(candidate_token):
            return _NOT_FOUND
        return Response(
            content=assets.live_state_mjs,
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.websocket("/s/{candidate_token}/ws")
    async def websocket_endpoint(websocket: WebSocket, candidate_token: str) -> None:
        if not _token_matches(candidate_token):
            # Never accepted -- rejected before ever entering the hub's active
            # set (D-05). Sending "websocket.close" before "websocket.accept"
            # refuses the handshake at the ASGI level.
            await websocket.close(code=_WS_CLOSE_BAD_TOKEN)
            return
        if not _websocket_origin_ok(websocket):
            # Another site's page holding a leaked token: refused before
            # accept, so it never joins the hub either.
            await websocket.close(code=_WS_CLOSE_BAD_ORIGIN)
            return
        await hub.connect(websocket)
        disconnect_reason = "unknown"
        try:
            await websocket.send_json(
                hello_payload(
                    session_id=session_id,
                    server_started_at=server_started_at,
                    heartbeat_interval_ms=heartbeat_interval_ms,
                    heartbeat_timeout_ms=heartbeat_timeout_ms,
                    reconnect_backoff_base_ms=reconnect_backoff_base_ms,
                    reconnect_backoff_cap_ms=reconnect_backoff_cap_ms,
                    project=project,
                    grounding_sources=grounding_sources,
                    coach_enabled=coach_enabled,
                )
            )
            # Pushed on EVERY fresh connect, alongside hello -- a laptop-side
            # failure survives a reconnect even though transcript content
            # deliberately does not (§Q6 versus D-01: this is "whatever
            # arrives next", not a replay of missed transcript).
            await websocket.send_json(status_message(board.current))
            # Phase C: pushed on every fresh connect too, for the same reason
            # the status above is -- but guarded, because a provider that
            # raises must not take the whole connection down with it. The
            # survey panel going momentarily unpopulated is a far smaller
            # failure than a browser that cannot connect at all, and this
            # message exists precisely to be the thing that still works when
            # other things do not.
            if survey_provider is not None:
                try:
                    survey = survey_provider()
                except Exception as exc:  # noqa: BLE001 -- never fail a connect over the survey panel
                    logger.warning("survey provider failed error_type=%s", type(exc).__name__)
                    survey = None
                if survey is not None:
                    await websocket.send_json(survey)
            while True:
                raw = await websocket.receive_text()
                message = _parse_client_message(raw)
                if message is None:
                    # Unaccepted type or malformed payload: ignored without
                    # raising, without closing the socket, and without ever
                    # logging its content (S7, T-03-14).
                    continue
                if message.get("type") == MESSAGE_TYPE_PING:
                    await websocket.send_json({"type": MESSAGE_TYPE_PONG})
        except WebSocketDisconnect as exc:
            # 03-RESEARCH Open Question 2: recorded so the server's own view
            # of a disconnect can be compared against the client's own
            # heartbeat-timeout log during Task 3's real-phone rehearsal.
            disconnect_reason = f"websocket-close-code-{exc.code}"
        finally:
            await hub.disconnect(websocket)
            store.append_event(
                event="ws-disconnected",
                detail={"reason": disconnect_reason, "connection_count": hub.connection_count},
            )

    if audio_sink is not None:
        _register_mic_routes(app, assets=assets, token_matches=_token_matches, store=store, audio_sink=audio_sink)

    @app.get("/{_catch_all:path}")
    async def catch_all(_catch_all: str) -> Response:
        # Covers "/", "/s/" (empty token segment), and anything else not
        # matched above -- always a generic 404, nothing ever echoed back.
        return _NOT_FOUND

    return app


def build_uvicorn_server(
    app: FastAPI,
    *,
    host: str,
    port: int,
    ws_ping_interval_s: float = config_mod.DEFAULT_WS_PING_INTERVAL_S,
    ws_ping_timeout_s: float = config_mod.DEFAULT_WS_PING_TIMEOUT_S,
) -> "object":
    """Constructs `uvicorn.Config` + `uvicorn.Server` -- never `uvicorn.run()`,
    which calls `asyncio.run()` internally and cannot be nested inside this
    process's own top-level `asyncio.run()` (03-RESEARCH.md §1). Deferred
    import: `uvicorn` is only needed here, at the one call site that embeds
    it, keeping every other module in this package importable without it.

    `ws_ping_interval_s`/`ws_ping_timeout_s` (independent review finding B)
    are passed EXPLICITLY, sourced from `app/config.py`'s own
    `DEFAULT_WS_PING_*` knobs -- never left to ride on `websockets`'
    undocumented default. This is the only bound on
    `app/web/hub.py::ConnectionHub._broadcast_payload`'s sequential fan-out:
    a half-open phone whose write buffer fills parks `send_json()` on
    backpressure rather than raising, and without an explicit ping/pong
    timeout a future dependency bump could silently make that starvation
    indefinite instead of bounded."""
    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        ws_ping_interval=ws_ping_interval_s,
        ws_ping_timeout=ws_ping_timeout_s,
    )
    return uvicorn.Server(config)


def _register_mic_routes(app: FastAPI, *, assets: _StaticAssets, token_matches, store: SessionStore, audio_sink) -> None:
    """In-person mode: the capture script and the binary audio socket."""
    # The socket that currently owns the mic. Last connection wins: a stray
    # token holder connecting first can no longer lock the operator out --
    # reloading the phone page always takes the mic back.
    slot: "dict[str, Optional[WebSocket]]" = {"owner": None}

    def _script(content: bytes) -> Response:
        return Response(content=content, media_type="text/javascript", headers={"Cache-Control": "no-store"})

    @app.get("/s/{candidate_token}/mic.js")
    async def get_mic_js(candidate_token: str) -> Response:
        return _script(assets.mic_js) if token_matches(candidate_token) else _NOT_FOUND

    @app.get("/s/{candidate_token}/mic-core.mjs")
    async def get_mic_core(candidate_token: str) -> Response:
        return _script(assets.mic_core_mjs) if token_matches(candidate_token) else _NOT_FOUND

    @app.websocket("/s/{candidate_token}/audio")
    async def audio_endpoint(websocket: WebSocket, candidate_token: str) -> None:
        if not token_matches(candidate_token):
            await websocket.close(code=_WS_CLOSE_BAD_TOKEN)
            return
        if not _websocket_origin_ok(websocket):
            await websocket.close(code=_WS_CLOSE_BAD_ORIGIN)
            return
        await websocket.accept()
        previous, slot["owner"] = slot["owner"], websocket
        if previous is not None:
            try:
                await previous.close(code=WS_CLOSE_MIC_REPLACED, reason="replaced by a newer connection")
            except Exception:  # noqa: BLE001 -- already closing: its own handler cleans up
                pass
        store.append_event(event="mic-connected", detail={"replaced_previous": previous is not None})
        reason = "unknown"
        try:
            while True:
                message = await websocket.receive()
                if slot["owner"] is not websocket:
                    # Replaced while waiting: never feed a second room into
                    # the transcript, even one frame.
                    reason = "replaced"
                    break
                if message["type"] == "websocket.disconnect":
                    reason = f"websocket-close-code-{message.get('code')}"
                    break
                frame = message.get("bytes")
                if frame is None:
                    continue  # text: not audio, ignored without echoing it
                if len(frame) > MAX_AUDIO_FRAME_BYTES or len(frame) % 2:
                    reason = "bad-audio-frame"
                    await websocket.close(code=_WS_CLOSE_BAD_AUDIO)
                    break
                audio_sink(frame)
        except WebSocketDisconnect as exc:
            reason = "replaced" if slot["owner"] is not websocket else f"websocket-close-code-{exc.code}"
        finally:
            # Release only our OWN claim: a replaced socket's cleanup runs
            # after the new owner took the slot and must not free it.
            if slot["owner"] is websocket:
                slot["owner"] = None
            store.append_event(event="mic-disconnected", detail={"reason": reason})
