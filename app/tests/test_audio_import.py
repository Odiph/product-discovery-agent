"""`python -m app import <recording.wav>`: a past interview's AUDIO becomes a
session, through the same file pass and speaker confirmation an in-person
meeting uses.

Offline by construction: an autouse fixture replaces the vendor client's
constructor, so a test that forgot to inject a fake fails instead of reading a
key or uploading. The synthetic room and its tokens are test_evidence_pass's.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from app import main as main_mod
from app import projects as projects_mod
from app.session import evidence as ev
from app.session.evidence_view import read_view
from app.session.reader import read_session
from app.stt import voiceprint
from app.tests import test_evidence_pass as fixtures
from benchmark.engines import soniox_async

SPOKEN = ("consent", "Spreadsheets", "email")


class FakeClient:
    def __init__(self, error: "Exception | None" = None):
        self.files: "list[str]" = []
        self.cleanup_failures: "list[str]" = []
        self._error = error

    def transcribe_file(self, path):
        self.files.append(Path(path).name)
        if self._error is not None:
            raise self._error
        return list(fixtures.TOKENS)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(projects_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(tmp_path / "context"))
    return tmp_path


@pytest.fixture(autouse=True)
def no_vendor(monkeypatch):
    """Nothing here may build the real client. Tests that upload install a fake."""
    def explode(*args, **kwargs):
        raise AssertionError("the real file-pass client was built in an offline test")

    monkeypatch.setattr(soniox_async.SonioxAsyncClient, "from_env", explode)
    monkeypatch.setattr(voiceprint, "load_embedder", lambda: (fixtures.CodedEmbedder(), ""))
    # The fixture room is 14 s; production enrols over 120 s.
    monkeypatch.setattr(main_mod, "IN_PERSON_ENROL_S", 4.0)


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(soniox_async.SonioxAsyncClient, "from_env", lambda *a, **k: fake)
    return fake


def _recording(directory: Path, name: str = "pilot-call.wav", seconds: float = 14) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    fixtures._room(path, fixtures.SPANS, seconds)
    return path


def _import(*argv: str) -> int:
    return main_mod.main(["import", *argv])


def _sessions(repo: Path) -> Path:
    return repo / "projects" / "acme" / "sessions"


def _only_session(repo: Path) -> Path:
    found = [p for p in _sessions(repo).iterdir() if p.is_dir()]
    assert len(found) == 1, found
    return found[0]


def _meta(session_dir: Path) -> dict:
    return json.loads((session_dir / "session.json").read_text(encoding="utf-8"))


# --- without --yes: show, call nothing ------------------------------------------


def test_without_yes_it_shows_what_would_be_uploaded_and_calls_nothing(repo, tmp_path, capsys):
    source = _recording(tmp_path / "recordings")
    # `no_vendor` makes building a client an AssertionError: reaching exit 0 is the proof.
    assert _import(str(source), "--project", "acme") == 0
    assert not (repo / "projects").exists()
    out = capsys.readouterr().out
    assert "pilot-call.wav" in out
    assert "0.2 min" in out  # 14 s
    assert "0.4 MB" in out  # 14 s of 16 kHz mono 16-bit
    assert "Soniox" in out
    assert "confirm-speakers" in out
    assert "Nothing written, nothing uploaded" in out and "--yes" in out


def test_me_is_not_needed_for_audio_but_still_is_for_a_transcript(repo, tmp_path, capsys):
    transcript = tmp_path / "call.txt"
    transcript.write_text("Sam: How is it going?\nDana: Fine.\nSam: Good.\nDana: Yes.\n", encoding="utf-8")
    assert _import(str(transcript), "--project", "acme", "--yes") == 2
    assert "--me" in capsys.readouterr().err
    assert not (repo / "projects").exists()


# --- with --yes: one session, through the existing pass ------------------------------


def test_a_wav_becomes_a_session_awaiting_speaker_confirmation(repo, tmp_path, client, capsys):
    source = _recording(tmp_path / "recordings")
    original = source.read_bytes()
    assert _import(str(source), "--project", "acme", "--date", "2026-03-04", "--participant", "Dana", "--yes") == 0

    session_dir = _only_session(repo)
    meta = _meta(session_dir)
    assert session_dir.name.startswith("20260304T")
    assert meta["engine"] == "import"
    assert meta["source"] == "file-import (audio: wav)"
    assert meta["imported_from"] == "pilot-call.wav"
    assert "recordings" not in json.dumps(meta)
    assert meta["participant"] == "Dana"
    assert meta["coach_enabled"] is False
    assert meta["audio_retained"] is True
    assert "closed_at" in meta
    # The existing pass ran on the session's own copy, and left it for confirmation.
    assert client.files == [ev.ROOM_AUDIO_FILENAME]
    assert meta[ev.EVIDENCE_KEY] == ev.EVIDENCE_TRANSCRIBED
    assert (session_dir / ev.ROOM_AUDIO_FILENAME).read_bytes() == original
    assert source.read_bytes() == original
    assert (session_dir / ev.EVIDENCE_TRANSCRIPT_FILENAME).is_file()
    # Roles are a claim until confirmed: `extract` refuses, exactly as in-person.
    refusal = ev.extract_refusal(meta)
    assert refusal is not None
    # ... but in its own words: it was never a meeting and has no live roles.
    assert "imported recording" in refusal
    assert "in-person" not in refusal and "accept-live-roles" not in refusal
    assert not read_session(session_dir).records

    out = capsys.readouterr().out
    assert f"confirm-speakers {session_dir.name}" in out
    assert not any(word in out for word in SPOKEN)
    assert [p.name for p in _sessions(repo).iterdir()] == [session_dir.name]  # no temp dir left


def test_confirming_speakers_makes_it_readable_like_any_session_and_deletes_the_copy(repo, tmp_path, client):
    source = _recording(tmp_path)
    assert _import(str(source), "--project", "acme", "--yes") == 0
    session_dir = _only_session(repo)
    assert main_mod.main([
        "confirm-speakers", session_dir.name, "--project", "acme", "--confirm", "--disputed", "label",
    ]) == 0

    meta = _meta(session_dir)
    assert ev.extract_refusal(meta) is None
    assert meta["audio_retained"] is False
    assert not (session_dir / ev.ROOM_AUDIO_FILENAME).exists()
    assert source.is_file()  # only the session's copy is deleted
    segments = list(
        read_session(session_dir, transcript_filename=ev.transcript_filename_for(meta)).records_of_kind("segment")
    )
    assert [s["speaker"] for s in segments][:2] == ["interviewer", "interviewee"]
    assert "consent" in segments[0]["text"]
    # The reader every post-interview command goes through sees the same turns.
    assert [s["seq"] for s in read_view(session_dir).records_of_kind("segment")] == [s["seq"] for s in segments]


def test_swap_is_how_a_recording_the_other_person_opened_is_put_right(repo, tmp_path, client):
    assert _import(str(_recording(tmp_path)), "--project", "acme", "--yes") == 0
    session_dir = _only_session(repo)
    assert main_mod.main([
        "confirm-speakers", session_dir.name, "--project", "acme", "--confirm", "--swap", "--disputed", "label",
    ]) == 0
    meta = _meta(session_dir)
    segments = list(
        read_session(session_dir, transcript_filename=ev.transcript_filename_for(meta)).records_of_kind("segment")
    )
    assert segments[0]["speaker"] == "interviewee"


# --- refusals, all before anything is uploaded or written -----------------------------


def test_a_compressed_recording_is_refused_with_how_to_convert_it(repo, tmp_path, capsys):
    source = tmp_path / "call.m4a"
    source.write_bytes(b"\x00\x01")
    assert _import(str(source), "--project", "acme", "--yes") == 1
    assert not (repo / "projects").exists()
    err = capsys.readouterr().err
    assert "call.m4a" in err and "ffmpeg" in err and "16000" in err


def test_a_wav_in_another_format_is_refused_with_how_to_convert_it(repo, tmp_path, capsys):
    source = tmp_path / "stereo.wav"
    with wave.open(str(source), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 44100)
    assert _import(str(source), "--project", "acme", "--yes") == 1
    assert not (repo / "projects").exists()
    err = capsys.readouterr().err
    assert "44100" in err and "ffmpeg" in err


def test_a_file_named_wav_that_is_not_one_is_refused(repo, tmp_path, capsys):
    source = tmp_path / "broken.wav"
    source.write_bytes(b"RIFF")
    assert _import(str(source), "--project", "acme", "--yes") == 1
    assert not (repo / "projects").exists()
    assert "broken.wav" in capsys.readouterr().err


def test_a_recording_longer_than_the_file_pass_accepts_is_refused_before_upload(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(soniox_async, "MAX_FILE_DURATION_S", 5)
    assert _import(str(_recording(tmp_path)), "--project", "acme", "--yes") == 1
    assert not (repo / "projects").exists()
    assert "at most" in capsys.readouterr().err


def test_without_a_key_nothing_is_written(repo, tmp_path, monkeypatch, capsys):
    def no_key(*args, **kwargs):
        raise soniox_async.SonioxAsyncConfigError("SONIOX_API_KEY is not set.")

    monkeypatch.setattr(soniox_async.SonioxAsyncClient, "from_env", no_key)
    assert _import(str(_recording(tmp_path)), "--project", "acme", "--yes") == 1
    assert not (repo / "projects").exists()
    assert "SONIOX_API_KEY" in capsys.readouterr().err


def test_the_same_recording_twice_is_refused_naming_the_existing_session(repo, tmp_path, client, capsys):
    source = _recording(tmp_path)
    assert _import(str(source), "--project", "acme", "--yes") == 0
    first = _only_session(repo).name
    assert _import(str(source), "--project", "acme", "--yes") == 1
    assert first in capsys.readouterr().err
    assert client.files == [ev.ROOM_AUDIO_FILENAME]  # not uploaded a second time
    _only_session(repo)


# --- a failed pass ----------------------------------------------------------------


def test_a_failed_pass_keeps_the_session_and_says_how_to_retry(repo, tmp_path, monkeypatch, capsys):
    fake = FakeClient(error=soniox_async.SonioxAsyncError("POST /v1/files failed: TimeoutError"))
    monkeypatch.setattr(soniox_async.SonioxAsyncClient, "from_env", lambda *a, **k: fake)
    assert _import(str(_recording(tmp_path)), "--project", "acme", "--yes") == 1
    session_dir = _only_session(repo)
    meta = _meta(session_dir)
    assert meta[ev.EVIDENCE_KEY] == ev.EVIDENCE_PENDING
    assert (session_dir / ev.ROOM_AUDIO_FILENAME).is_file()
    assert not (session_dir / ev.EVIDENCE_TRANSCRIPT_FILENAME).exists()
    captured = capsys.readouterr()
    assert f"diarize-after {session_dir.name}" in captured.out + captured.err


# --- a folder ---------------------------------------------------------------------


def test_a_folder_takes_transcripts_and_recordings_together(repo, tmp_path, client):
    folder = tmp_path / "exports"
    _recording(folder, "b-call.wav")
    (folder / "a-call.txt").write_text(
        "Sam: How is it going?\nDana: Fine.\nSam: Good.\nDana: Yes.\n", encoding="utf-8"
    )
    assert _import(str(folder), "--project", "acme", "--me", "Sam", "--yes") == 0
    sources = sorted(_meta(p)["imported_from"] for p in _sessions(repo).iterdir())
    assert sources == ["a-call.txt", "b-call.wav"]
