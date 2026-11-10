"""`precheck --in-person`: the go/no-go for a meeting where the PHONE is the
microphone. No laptop audio device is opened. What must hold instead: the
loopback port is free, Tailscale is up with a name, `tailscale serve`
forwards that name to this app's port, the name completes a VERIFIED TLS
handshake (a phone grants the mic only in a secure context), and the
diarizing engine answers.
"""

from __future__ import annotations

import json

import pytest

from app import config as config_mod
from app.capture import precheck_in_person as pip_mod
from app.capture.precheck import RESULT_FAIL, RESULT_PASS, RESULT_SKIPPED, PrecheckRow
from app.web import server as web_server
from app.web import tailnet

NAME = "laptop.tail1234.ts.net"
PORT = 8000


def _serve(proxy: str) -> str:
    return json.dumps({"Web": {f"{NAME}:443": {"Handlers": {"/": {"Proxy": proxy}}}}})


def _cfg():
    return config_mod.load_config()


def _build(**overrides):
    kwargs = dict(
        cfg=_cfg(),
        port=PORT,
        skip_stt=True,
        port_checker=lambda port: None,
        dns_detector=lambda: NAME,
        serve_reader=lambda: _serve(f"http://127.0.0.1:{PORT}"),
        https_probe=lambda name: None,
    )
    kwargs.update(overrides)
    return pip_mod.build_in_person_report(**kwargs)


def _row(report, prefix: str) -> PrecheckRow:
    (row,) = [r for r in report.rows if r.name.startswith(prefix)]
    return row


def test_everything_in_place_passes_and_opens_no_audio_device():
    report = _build()
    assert report.exit_code == 0
    names = [r.name for r in report.rows]
    assert not any("device" in n.lower() or "liveness" in n.lower() for n in names)
    assert _row(report, "Tailscale serve").result == RESULT_PASS
    assert NAME in _row(report, "HTTPS").measured


def test_the_default_port_check_binds_loopback_like_start_in_person(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        web_server, "check_port_available", lambda port, *, host="0.0.0.0": seen.update(port=port, host=host)
    )
    _build(port_checker=None)
    assert seen == {"port": PORT, "host": "127.0.0.1"}


def test_a_taken_port_fails_with_the_checkers_own_message():
    def taken(port):
        raise web_server.PortInUseError(f"port {port} is in use")

    report = _build(port_checker=taken)
    assert report.exit_code == 1
    assert "8000" in _row(report, "Web port").remedy


def test_no_tailscale_fails_and_skips_the_rows_that_need_a_name():
    report = _build(dns_detector=lambda: None)
    assert _row(report, "Tailscale running").result == RESULT_FAIL
    assert "tailscale up" in _row(report, "Tailscale running").remedy
    assert _row(report, "Tailscale serve").result == RESULT_SKIPPED
    assert _row(report, "HTTPS").result == RESULT_SKIPPED


def test_serve_not_configured_fails_with_the_exact_command():
    report = _build(serve_reader=lambda: "{}")
    row = _row(report, "Tailscale serve")
    assert row.result == RESULT_FAIL
    assert f"tailscale serve --bg {PORT}" in row.remedy


def test_serve_to_another_port_names_where_it_points():
    report = _build(serve_reader=lambda: _serve("http://127.0.0.1:9999"))
    row = _row(report, "Tailscale serve")
    assert row.result == RESULT_FAIL
    assert "http://127.0.0.1:9999" in row.remedy and f"--bg {PORT}" in row.remedy


def test_unreadable_serve_status_fails_rather_than_guessing():
    row = _row(_build(serve_reader=lambda: None), "Tailscale serve")
    assert row.result == RESULT_FAIL


def test_a_foreground_serve_passes_with_a_warning_that_it_dies_with_its_terminal():
    raw = json.dumps({"Foreground": {"s1": json.loads(_serve(f"http://127.0.0.1:{PORT}"))}})
    row = _row(_build(serve_reader=lambda: raw), "Tailscale serve")
    assert row.result == RESULT_PASS
    assert "--bg" in row.measured


def test_a_certificate_failure_points_at_the_admin_console():
    failure = tailnet.HandshakeFailure(tls=True, detail="certificate verify failed")
    row = _row(_build(https_probe=lambda name: failure), "HTTPS")
    assert row.result == RESULT_FAIL
    assert "certificate verify failed" in row.remedy and "HTTPS Certificates" in row.remedy


def test_a_refused_connection_points_at_serve_not_the_admin_console():
    failure = tailnet.HandshakeFailure(tls=False, detail="ConnectionRefusedError: refused")
    row = _row(_build(https_probe=lambda name: failure), "HTTPS")
    assert row.result == RESULT_FAIL
    assert "refused" in row.remedy and f"tailscale serve --bg {PORT}" in row.remedy
    assert "HTTPS Certificates" not in row.remedy


def test_skip_stt_reports_the_engine_as_skipped():
    assert _row(_build(skip_stt=True), "Engine").result == RESULT_SKIPPED


def test_the_engine_row_uses_the_in_person_engine():
    asked = []

    def factory_for(name):
        asked.append(name)
        raise RuntimeError("no key in this test")

    report = _build(skip_stt=False, engine_lookup=factory_for)
    assert asked and asked[0].endswith("-in-person")
    assert _row(report, "Engine").result == RESULT_FAIL


@pytest.mark.parametrize("flag", ["phone", "interviewee_device", "interviewer_device"])
def test_flags_that_assume_laptop_audio_or_the_lan_conflict_with_in_person(flag):
    import argparse

    args = argparse.Namespace(phone=False, interviewee_device=None, interviewer_device=None)
    setattr(args, flag, True if flag == "phone" else "Some Device")
    assert pip_mod.in_person_conflict(args)


def test_the_cli_runs_the_in_person_report_without_ever_opening_pyaudio(monkeypatch, capsys):
    from app import main as main_mod

    def no_pyaudio():
        raise AssertionError("precheck --in-person must not open laptop audio")

    monkeypatch.setattr(main_mod, "construct_pyaudio", no_pyaudio)
    monkeypatch.setattr(pip_mod.tailnet, "detect_dns_name", lambda: None)
    monkeypatch.setattr(
        pip_mod.web_server, "check_port_available", lambda port, *, host="0.0.0.0": None
    )
    code = main_mod.main(["precheck", "--in-person", "--skip-stt"])
    out = capsys.readouterr().out
    assert code == 1  # no Tailscale here -> the Tailscale row fails
    assert "Tailscale running" in out and "consent" in out
    assert "Loopback captures" not in out  # the call-capture rules are not shown


def test_the_cli_refuses_phone_with_in_person(monkeypatch, capsys):
    from app import main as main_mod

    monkeypatch.setattr(main_mod, "construct_pyaudio", lambda: (_ for _ in ()).throw(AssertionError()))
    assert main_mod.main(["precheck", "--in-person", "--phone"]) == 2
    assert "--phone" in capsys.readouterr().err
