"""`app.web.tailnet`: is `tailscale serve` actually forwarding the tailnet
HTTPS name to THIS app, and does that name complete a verified TLS handshake?

The JSON shapes are Tailscale's `ipn.ServeConfig` as `serve status --json`
prints it (ipn/serve.go): `Web["<name>:443"].Handlers["/"].Proxy`, and a
bare `serve --bg 8000` stores `http://127.0.0.1:8000`. A `serve` run WITHOUT
`--bg` lives under `Foreground[<session id>]` and dies with its terminal.
"""

from __future__ import annotations

import json
import ssl

from app.web import tailnet

NAME = "laptop.tail1234.ts.net"


def _web(proxy: str, host: str = NAME) -> dict:
    return {"Web": {f"{host}:443": {"Handlers": {"/": {"Proxy": proxy}}}}}


def test_a_background_serve_to_this_port_is_found():
    raw = json.dumps({"TCP": {"443": {"HTTPS": True}}, **_web("http://127.0.0.1:8000")})
    routes = tailnet.serve_routes(raw, NAME)
    assert routes == (tailnet.ServeRoute(proxy="http://127.0.0.1:8000", foreground=False),)
    assert tailnet.route_reaches_port(routes[0], 8000)


def test_a_foreground_serve_is_found_and_marked_foreground():
    raw = json.dumps({"Foreground": {"session-abc": _web("http://127.0.0.1:8000")}})
    (route,) = tailnet.serve_routes(raw, NAME)
    assert route.foreground and tailnet.route_reaches_port(route, 8000)


def test_localhost_counts_but_another_port_or_a_remote_host_does_not():
    assert tailnet.route_reaches_port(tailnet.ServeRoute("http://localhost:8000/", False), 8000)
    assert not tailnet.route_reaches_port(tailnet.ServeRoute("http://127.0.0.1:8001", False), 8000)
    assert not tailnet.route_reaches_port(tailnet.ServeRoute("http://10.0.0.5:8000", False), 8000)
    assert not tailnet.route_reaches_port(tailnet.ServeRoute("unix:/tmp/app.sock", False), 8000)
    # `start --in-person` binds 127.0.0.1 only: an IPv6-loopback proxy would 502.
    assert not tailnet.route_reaches_port(tailnet.ServeRoute("http://[::1]:8000", False), 8000)
    # mounted under a prefix, the phone page /s/<token> would 404
    assert not tailnet.route_reaches_port(tailnet.ServeRoute("http://127.0.0.1:8000/sub", False), 8000)


def test_a_handler_for_another_name_or_port_is_not_this_laptops_front_door():
    other_host = json.dumps(_web("http://127.0.0.1:8000", host="other.tail1234.ts.net"))
    assert tailnet.serve_routes(other_host, NAME) == ()
    not_443 = json.dumps({"Web": {f"{NAME}:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}}})
    assert tailnet.serve_routes(not_443, NAME) == ()


def test_nothing_configured_garbage_or_odd_shapes_give_no_routes():
    for raw in ("{}", "", "not json", "[]", json.dumps({"Web": {f"{NAME}:443": None}}),
                json.dumps({"Web": {f"{NAME}:443": {"Handlers": {"/": {"Path": "C:/site"}}}}})):
        assert tailnet.serve_routes(raw, NAME) == (), raw


def test_a_missing_tailscale_binary_reads_no_serve_status(monkeypatch):
    monkeypatch.setattr(tailnet, "_tailscale_binary", lambda: None)
    assert tailnet.read_serve_status() is None


def test_https_handshake_reports_none_on_success_and_the_reason_on_failure():
    seen = {}

    def ok(host, port, timeout_s):
        seen.update(host=host, port=port)

    assert tailnet.https_handshake_error(NAME, connect=ok) is None
    assert seen == {"host": NAME, "port": 443}

    def bad_cert(host, port, timeout_s):
        raise ssl.SSLCertVerificationError("certificate verify failed: self-signed")

    failure = tailnet.https_handshake_error(NAME, connect=bad_cert)
    assert failure.tls and "certificate" in failure.detail

    def refused(host, port, timeout_s):
        raise ConnectionRefusedError("refused")

    failure = tailnet.https_handshake_error(NAME, connect=refused)
    assert not failure.tls and "refused" in failure.detail
