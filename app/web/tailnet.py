"""The phone URL for an in-person run, over Tailscale.

A phone browser grants microphone access only in a secure context, and a
bare LAN IP over plain HTTP is not one. `tailscale serve --bg <port>` puts
this laptop's loopback-only server behind a real HTTPS name on the tailnet.
That name is reachable from any device signed in to the operator's tailnet
(the token in the URL is what keeps out the ones that should not join), and
from the public internet only if Tailscale Funnel is on for it -- which the
in-person precheck refuses, see `funnel_enabled`.

Detection is best-effort and bounded: no Tailscale, a stopped one, or a slow
one all degrade to printing the instruction instead of the URL.
"""

from __future__ import annotations

import json
import shutil
import socket
import ssl
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

_WINDOWS_DEFAULT = Path("C:/Program Files/Tailscale/tailscale.exe")
_TIMEOUT_S = 3.0


def _tailscale_binary() -> Optional[str]:
    found = shutil.which("tailscale")
    if found:
        return found
    return str(_WINDOWS_DEFAULT) if _WINDOWS_DEFAULT.is_file() else None


def dns_name_from_status(raw: str) -> Optional[str]:
    try:
        status = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(status, dict) or status.get("BackendState") != "Running":
        return None
    name = (status.get("Self") or {}).get("DNSName") or ""
    name = name.rstrip(".")
    return name or None


def detect_dns_name() -> Optional[str]:
    binary = _tailscale_binary()
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [binary, "status", "--json"], capture_output=True, text=True, timeout=_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return dns_name_from_status(result.stdout) if result.returncode == 0 else None


def phone_url(dns_name: str, token: str) -> str:
    return f"https://{dns_name}/s/{token}?mic"


# --- `precheck --in-person`: is `tailscale serve` forwarding to THIS app? ---
#
# `tailscale serve status --json` prints Tailscale's `ipn.ServeConfig`
# (ipn/serve.go): `Web["<name>:443"].Handlers["/"].Proxy`. A bare
# `serve --bg 8000` stores `http://127.0.0.1:8000`; a `serve` run without
# `--bg` is stored under `Foreground[<session id>]` and ends with its terminal.

# IPv4 only: `start --in-person` binds 127.0.0.1, so a `[::1]` proxy would 502.
# `localhost` counts because Tailscale's dialer falls back across families.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


@dataclass(frozen=True)
class ServeRoute:
    proxy: str
    foreground: bool


def _root_proxy(config: object, dns_name: str) -> Optional[str]:
    if not isinstance(config, dict):
        return None
    web = config.get("Web")
    server = web.get(f"{dns_name}:443") if isinstance(web, dict) else None
    handlers = server.get("Handlers") if isinstance(server, dict) else None
    root = handlers.get("/") if isinstance(handlers, dict) else None
    proxy = root.get("Proxy") if isinstance(root, dict) else None
    return proxy if isinstance(proxy, str) and proxy else None


def serve_routes(raw: str, dns_name: str) -> "tuple[ServeRoute, ...]":
    """Every proxy mounted at `/` on `https://<dns_name>`, background first."""
    try:
        config = json.loads(raw)
    except (ValueError, TypeError):
        return ()
    if not isinstance(config, dict):
        return ()
    routes: list[ServeRoute] = []
    proxy = _root_proxy(config, dns_name)
    if proxy:
        routes.append(ServeRoute(proxy=proxy, foreground=False))
    foreground = config.get("Foreground")
    if isinstance(foreground, dict):
        for nested in foreground.values():
            proxy = _root_proxy(nested, dns_name)
            if proxy:
                routes.append(ServeRoute(proxy=proxy, foreground=True))
    return tuple(routes)


def _funnel_on(config: object, dns_name: str) -> bool:
    if not isinstance(config, dict):
        return False
    allow = config.get("AllowFunnel")
    return isinstance(allow, dict) and allow.get(f"{dns_name}:443") is True


def funnel_enabled(raw: str, dns_name: str) -> bool:
    """True when `serve status --json` has Funnel on for `<dns_name>:443`, in
    the background config or any foreground session. Funnel puts the phone
    surface and the mic socket on the PUBLIC internet behind only the URL
    token, so in person it is a hard no. Unparseable status says False: the
    caller's serve row already fails on an unreadable status."""
    try:
        config = json.loads(raw)
    except (ValueError, TypeError):
        return False
    if not isinstance(config, dict):
        return False
    if _funnel_on(config, dns_name):
        return True
    foreground = config.get("Foreground")
    return isinstance(foreground, dict) and any(_funnel_on(nested, dns_name) for nested in foreground.values())


def funnel_off_instruction(port: int) -> str:
    # Both are long-standing CLI forms: `funnel ... off` drops the public
    # route, and re-serving restores the tailnet-only one.
    return (
        "turn Funnel off for this name with `tailscale funnel --https=443 off`, then "
        f"`tailscale serve --bg {port}` (tailnet only), and check `tailscale serve status` "
        "no longer says Funnel on"
    )


def public_funnel_warning(
    dns_name: str,
    port: int,
    *,
    serve_reader: "Optional[Callable[[], Optional[str]]]" = None,
) -> Optional[str]:
    """For the run-start URL print: a warning line when Funnel is on for the
    phone's name, else None. Best-effort like the rest of this module: an
    unreadable status says nothing rather than guessing."""
    raw = (serve_reader or read_serve_status)()
    if raw is None or not funnel_enabled(raw, dns_name):
        return None
    return (
        f"WARNING: Tailscale Funnel is ON for https://{dns_name} -- the phone page and mic "
        f"are on the public internet behind only the URL token. Stop and {funnel_off_instruction(port)}."
    )


def route_reaches_port(route: ServeRoute, port: int) -> bool:
    parts = urlsplit(route.proxy)
    try:
        return (
            parts.scheme == "http"
            and parts.hostname in _LOOPBACK_HOSTS
            and parts.port == port
            and parts.path in ("", "/")  # under a prefix, /s/<token> would 404
        )
    except ValueError:  # a malformed port in the stored URL
        return False


def read_serve_status() -> Optional[str]:
    binary = _tailscale_binary()
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [binary, "serve", "status", "--json"],
            capture_output=True, text=True, timeout=_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _tls_connect(host: str, port: int, timeout_s: float) -> None:
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout_s) as raw_socket:
        with context.wrap_socket(raw_socket, server_hostname=host):
            pass


@dataclass(frozen=True)
class HandshakeFailure:
    tls: bool  # True: TLS itself failed (certificate); False: no connection at all
    detail: str


def https_handshake_error(
    dns_name: str,
    *,
    timeout_s: float = _TIMEOUT_S,
    connect: Callable[[str, int, float], None] = _tls_connect,
) -> Optional[HandshakeFailure]:
    """None when `https://<dns_name>` completes a certificate-VERIFIED TLS
    handshake -- the secure context a phone needs before it grants the mic.
    Otherwise what failed, split by kind: a refused or timed-out connection
    usually means `serve` is not running; a TLS error means the certificate.
    The app need not be running: the handshake is Tailscale's, not the app's."""
    try:
        connect(dns_name, 443, timeout_s)
    except (ssl.SSLError, ssl.CertificateError) as exc:
        return HandshakeFailure(tls=True, detail=f"{type(exc).__name__}: {exc}")
    except OSError as exc:  # refused, reset, timeout, no such name
        return HandshakeFailure(tls=False, detail=f"{type(exc).__name__}: {exc}")
    return None
