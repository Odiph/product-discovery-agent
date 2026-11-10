"""`app.web.tailnet`: the phone URL for an in-person run.

Phone browsers only allow microphone capture over HTTPS, and `tailscale serve`
gives this laptop a real HTTPS name on the tailnet. The name comes from
`tailscale status --json`; everything degrades to an instruction when
Tailscale is missing, stopped, or has no name, and nothing here may hang a
start.
"""

from __future__ import annotations

import json

from app.web import tailnet

STATUS = {"BackendState": "Running", "Self": {"DNSName": "laptop.tail1234.ts.net.", "Online": True}}


def test_the_https_name_is_read_from_status_without_the_trailing_dot():
    assert tailnet.dns_name_from_status(json.dumps(STATUS)) == "laptop.tail1234.ts.net"


def test_a_stopped_tailscale_has_no_name():
    stopped = {**STATUS, "BackendState": "Stopped"}
    assert tailnet.dns_name_from_status(json.dumps(stopped)) is None


def test_garbage_or_a_missing_name_has_no_name():
    assert tailnet.dns_name_from_status("not json") is None
    assert tailnet.dns_name_from_status(json.dumps({"BackendState": "Running", "Self": {}})) is None


def test_the_phone_url_uses_https_and_the_mic_page():
    assert tailnet.phone_url("laptop.tail1234.ts.net", "tok") == "https://laptop.tail1234.ts.net/s/tok?mic"


def test_a_missing_tailscale_binary_degrades_to_none(monkeypatch):
    monkeypatch.setattr(tailnet, "_tailscale_binary", lambda: None)
    assert tailnet.detect_dns_name() is None
