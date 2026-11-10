"""`start --in-person`, end to end: a real `python -m app start` child, fed audio
through its `/s/{t}/audio` socket exactly as the phone page does.

What only this test can see: the wiring. That in-person mode opens no local
audio device (no PyAudio at all), binds the phone surface to loopback only
(Tailscale's `serve` is the HTTPS front door, so the LAN never sees it), cuts
one room stream into BOTH roles, and records how its speaker labels were
obtained -- which the evidence side will need before it trusts them.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest
from websockets.sync.client import connect as ws_connect

REPO_ROOT = Path(__file__).resolve().parents[2]
URL_PATTERN = re.compile(r"http://127\.0\.0\.1:(\d+)/s/([A-Za-z0-9_-]+)\?mic")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env(tmp_path, port):
    return {
        **os.environ,
        "APP_SESSIONS_ROOT": str(tmp_path / "sessions"),
        "APP_CONTEXT_DIR": str(tmp_path / "context"),
        "APP_PORT": str(port),
        "APP_OPEN_BROWSER": "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }


def _start(tmp_path, *extra):
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "app", "start", "--in-person", "--engine", "fake", "--no-coach", *extra],
        cwd=str(REPO_ROOT), env=_env(tmp_path, port),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    lines: "list[str]" = []
    threading.Thread(target=lambda: [lines.append(l) for l in proc.stdout], daemon=True).start()
    return proc, lines


def _wait_for_url(lines, proc, timeout=40.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for line in list(lines):
            m = URL_PATTERN.search(line)
            if m:
                return int(m.group(1)), m.group(2)
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    raise AssertionError("no in-person phone URL printed:\n" + "".join(lines))


def test_an_in_person_run_turns_one_phone_stream_into_both_roles(tmp_path):
    proc, lines = _start(tmp_path, "--seconds", "12")
    try:
        port, token = _wait_for_url(lines, proc)
        tone = (np.sin(np.arange(1600) / 5.0) * 3000).astype("<i2").tobytes()  # 100 ms
        with ws_connect(f"ws://127.0.0.1:{port}/s/{token}/audio", open_timeout=10) as phone:
            for _ in range(40):  # 4 s, paced like a phone
                phone.send(tone)
                time.sleep(0.1)
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    output = "".join(lines)
    assert proc.returncode == 0, output

    session = next((tmp_path / "sessions").iterdir())
    records = [json.loads(l) for l in (session / "transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    speakers = {r["speaker"] for r in records if r["kind"] == "segment"}
    assert speakers == {"interviewer", "interviewee"}, output
    events = [r["event"] for r in records if r["kind"] == "event"]
    assert "mic-connected" in events and "mic-disconnected" in events

    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    assert meta["capture"] == "in-person"
    assert meta["speaker_source"] == "diarization-live"
    assert "Phone" in meta["interviewer_device"]
    assert meta["closed_at"]

    # The room audio is kept, WITHOUT --retain-audio, for the after-meeting
    # evidence pass -- and named for what it holds (both voices), never as
    # one role's stream.
    assert meta["audio_retained"] is True
    assert meta["evidence"] == "pending"
    assert not (session / "interviewer.wav").exists()
    with wave.open(str(session / "room.wav"), "rb") as room:
        assert (room.getframerate(), room.getnchannels(), room.getsampwidth()) == (16000, 1, 2)
        # At least the 4 s the phone sent; the pacer zero-fills the rest.
        assert room.getnframes() >= 4 * 16000

    # A real customer's voice is on disk with no flag on it, so the run says so
    # as it ends, and names the commands that remove it.
    tail = output[output.index("Transcript written to"):]
    assert f"room.wav is still on this laptop" in tail, output
    assert f"python -m app diarize-after {session.name}" in tail
    assert f"python -m app confirm-speakers {session.name} --confirm" in tail
    assert f"python -m app forget {session.name}" in tail


def test_the_room_audio_reminder_carries_the_project_flag(tmp_path):
    from app.main import _room_audio_reminder

    session_dir = tmp_path / "20261110T101500"
    session_dir.mkdir()
    (session_dir / "room.wav").write_bytes(b"RIFF")
    text = _room_audio_reminder(session_dir, project="acme/onboarding")
    assert str(session_dir / "room.wav") in text
    assert "python -m app confirm-speakers 20261110T101500 --confirm --project acme/onboarding" in text
    assert "--accept-live-roles" in text


def test_no_room_audio_reminder_when_nothing_was_kept(tmp_path):
    from app.main import _room_audio_reminder

    assert _room_audio_reminder(tmp_path, project=None) is None


def test_the_phone_surface_is_not_reachable_from_the_lan_in_person(tmp_path):
    proc, lines = _start(tmp_path, "--seconds", "6")
    try:
        port, _token = _wait_for_url(lines, proc)
        lan_ip = socket.gethostbyname(socket.gethostname())
        if lan_ip.startswith("127."):
            pytest.skip("no non-loopback address on this machine to test against")
        with pytest.raises(OSError):
            socket.create_connection((lan_ip, port), timeout=2).close()
    finally:
        proc.wait(timeout=60)


@pytest.mark.parametrize("flag", [["--no-serve"], ["--only", "interviewee"]], ids=["no-serve", "only"])
def test_in_person_refuses_flags_that_cannot_work_with_it(tmp_path, flag):
    result = subprocess.run(
        [sys.executable, "-m", "app", "start", "--in-person", "--engine", "fake", "--no-coach", *flag],
        cwd=str(REPO_ROOT), env=_env(tmp_path, _free_port()), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0
    assert "--in-person" in result.stderr
    assert not (tmp_path / "sessions").exists() or not any((tmp_path / "sessions").iterdir())
