"""`python -m app precheck --in-person`: the go/no-go for a meeting where the
PHONE is the microphone (.planning/in-person/PLAN.md, Phase 4).

No laptop audio device is opened -- `start --in-person` opens none either, so
measuring them would be a green light for a rig nobody runs. What has to hold
instead, in the order an operator would fix it:

1. the app's port is free on loopback (`start --in-person` binds 127.0.0.1);
2. Tailscale is running and this laptop has a tailnet name;
3. `tailscale serve` forwards `https://<name>/` to THIS app's port;
4. Tailscale Funnel is OFF for that name -- Funnel would put the phone page
   and the mic socket on the public internet behind only the URL token;
5. that name completes a certificate-verified TLS handshake -- a phone grants
   the microphone only in a secure context;
6. the diarizing in-person engine answers (skippable, like the call precheck).

Every dependency is injectable, so the report is testable with no Tailscale,
no network and no key.
"""

from __future__ import annotations

import argparse
from typing import Callable, Optional

from app import config as config_mod
from app.capture.precheck import (
    RESULT_FAIL,
    RESULT_PASS,
    RESULT_SKIPPED,
    PrecheckReport,
    PrecheckRow,
    _engine_row,
    _port_row,
)
from app.stt.live import IN_PERSON_SUFFIX, get_engine
from app.web import server as web_server
from app.web import tailnet

IN_PERSON_PREFLIGHT_RULES = (
    "Ask for consent before pressing Start on the phone -- the mic page shows the consent line.",
    "Charge or plug in the phone: the mic page keeps its screen awake for the whole meeting.",
    "Put the phone on the table between you, face up -- not in a pocket or behind a laptop.",
    'Set the laptop\'s power plan to "never sleep": it runs the engine the phone streams to.',
)

_SERVE_NAME = "Tailscale serve forwards to this app"
_HTTPS_NAME = "HTTPS name reachable (verified certificate)"
_FUNNEL_NAME = "Not public (Tailscale Funnel off)"


def in_person_conflict(args: argparse.Namespace) -> Optional[str]:
    """The precheck flags that assume laptop audio devices or the LAN."""
    if getattr(args, "phone", False):
        return "--phone (that check is the LAN QR flow; in person the phone joins over Tailscale)"
    for flag in ("interviewee_device", "interviewer_device"):
        if getattr(args, flag, None):
            return f"--{flag.replace('_', '-')} (no laptop audio device is opened in person)"
    return None


def _tailscale_row(dns_name: Optional[str]) -> PrecheckRow:
    name = "Tailscale running"
    if dns_name:
        return PrecheckRow(name=name, result=RESULT_PASS, measured=dns_name)
    return PrecheckRow(
        name=name, result=RESULT_FAIL,
        remedy=(
            "Tailscale is not installed, not running, or has no name. Install it from "
            "tailscale.com/download, run `tailscale up`, and sign the phone in to the same tailnet."
        ),
    )


def _serve_row(dns_name: str, port: int, raw: Optional[str]) -> PrecheckRow:
    command = f"tailscale serve --bg {port}"
    if raw is None:
        return PrecheckRow(
            name=_SERVE_NAME, result=RESULT_FAIL,
            remedy=f"Could not read `tailscale serve status --json`. Run `{command}` on this laptop.",
        )
    routes = tailnet.serve_routes(raw, dns_name)
    for route in routes:
        if tailnet.route_reaches_port(route, port):
            measured = f"https://{dns_name}/ -> {route.proxy}"
            if route.foreground:
                measured += (
                    " (foreground only: it stops when that terminal closes -- "
                    f"`{command}` keeps it running)"
                )
            return PrecheckRow(name=_SERVE_NAME, result=RESULT_PASS, measured=measured)
    if routes:
        elsewhere = ", ".join(route.proxy for route in routes)
        remedy = f"https://{dns_name}/ forwards to {elsewhere}, not this app. Run `{command}`."
    else:
        remedy = f"Nothing is served at https://{dns_name}/. Run `{command}` on this laptop."
    return PrecheckRow(name=_SERVE_NAME, result=RESULT_FAIL, remedy=remedy)


def _funnel_row(dns_name: str, port: int, raw: Optional[str]) -> PrecheckRow:
    if raw is None:  # the serve row already fails on an unreadable status
        return PrecheckRow(name=_FUNNEL_NAME, result=RESULT_SKIPPED)
    if not tailnet.funnel_enabled(raw, dns_name):
        return PrecheckRow(name=_FUNNEL_NAME, result=RESULT_PASS, measured="tailnet only")
    return PrecheckRow(
        name=_FUNNEL_NAME, result=RESULT_FAIL,
        remedy=(
            f"Tailscale Funnel is ON for https://{dns_name}: the phone page and mic would be on the "
            f"public internet behind only the URL token. {tailnet.funnel_off_instruction(port).capitalize()}."
        ),
    )


def _https_row(dns_name: str, port: int, failure: "Optional[tailnet.HandshakeFailure]") -> PrecheckRow:
    if failure is None:
        return PrecheckRow(name=_HTTPS_NAME, result=RESULT_PASS, measured=f"https://{dns_name}")
    if failure.tls:
        remedy = (
            f"https://{dns_name} answered but its certificate did not verify ({failure.detail}). "
            "In the Tailscale admin console, DNS page, enable MagicDNS and HTTPS Certificates; "
            "the first certificate can take a minute after `tailscale serve` starts."
        )
    else:
        remedy = (
            f"Could not connect to https://{dns_name} ({failure.detail}). Usually `serve` is not "
            f"running: run `tailscale serve --bg {port}`, then precheck again."
        )
    return PrecheckRow(name=_HTTPS_NAME, result=RESULT_FAIL, remedy=remedy)


def build_in_person_report(
    *,
    cfg: config_mod.AppConfig,
    port: int,
    skip_stt: bool = False,
    port_checker: Optional[Callable[[int], None]] = None,
    dns_detector: Callable[[], Optional[str]] = tailnet.detect_dns_name,
    serve_reader: Callable[[], Optional[str]] = tailnet.read_serve_status,
    https_probe: "Callable[[str], Optional[tailnet.HandshakeFailure]]" = tailnet.https_handshake_error,
    engine_lookup: Callable[[str], object] = get_engine,
) -> PrecheckReport:
    checker = port_checker or (lambda p: web_server.check_port_available(p, host="127.0.0.1"))
    rows: list[PrecheckRow] = [_port_row(port, port_checker=checker)]

    dns_name = dns_detector()
    rows.append(_tailscale_row(dns_name))
    if dns_name:
        serve_status = serve_reader()
        rows.append(_serve_row(dns_name, port, serve_status))
        rows.append(_funnel_row(dns_name, port, serve_status))
        rows.append(_https_row(dns_name, port, https_probe(dns_name)))
    else:
        rows.append(PrecheckRow(name=_SERVE_NAME, result=RESULT_SKIPPED))
        rows.append(PrecheckRow(name=_FUNNEL_NAME, result=RESULT_SKIPPED))
        rows.append(PrecheckRow(name=_HTTPS_NAME, result=RESULT_SKIPPED))

    if skip_stt:
        rows.append(PrecheckRow(name="Engine reachability", result=RESULT_SKIPPED))
    else:
        engine_name = cfg.engine_name + IN_PERSON_SUFFIX
        rows.append(_engine_row(
            engine_factory=lambda: engine_lookup(engine_name),
            sample_rate=cfg.sample_rate,
            pcm16=b"",  # no laptop mic in person: the row probes with half a second of silence
            timeout_s=cfg.precheck_engine_timeout_s,
        ))
    return PrecheckReport(rows=tuple(rows))
