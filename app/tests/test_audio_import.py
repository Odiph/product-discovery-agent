"""`python -m app import <recording>`: a past interview's AUDIO becomes a
session, through the same file pass and speaker confirmation an in-person
meeting uses.

Offline by construction: an autouse fixture replaces the vendor client's
constructor, so a test that forgot to inject a fake fails instead of reading a
key or uploading. The synthetic room and its tokens are test_evidence_pass's.
"""

from __future__ import annotations

import json
from datetime import datetime
from fractions import Fraction
import sys
import wave
from pathlib import Path

import numpy as np
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


def _compressed(directory: Path, suffix: str, seconds: float = 14, name: str = "call") -> Path:
    """The synthetic room as a phone would hand it over: compressed, 44.1 kHz
    stereo. Tones, not the WAV fixture's constant levels, because a lossy
    codec removes a constant; each tone's mean level matches its voice's, so
    the coded embedder still tells the two apart."""
    import av

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}{suffix}"
    codec = {".m4a": "aac", ".mp3": "libmp3lame", ".ogg": "libopus", ".flac": "flac"}[suffix]
    rate = 48000 if codec == "libopus" else 44100
    t = np.arange(int(seconds * rate)) / rate
    level = np.zeros_like(t)
    for start, end, value in fixtures.SPANS:
        level[int(start * rate):int(end * rate)] = value * np.pi / 2  # mean |sin| is 2/pi
    mono = (level * np.sin(2 * np.pi * 440 * t)).astype("<i2")
    with av.open(str(path), "w") as container:
        stream = container.add_stream(codec, rate=rate, layout="stereo")
        if len(mono):
            frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(np.stack([mono, mono])),
                                               format="s16p", layout="stereo")
            frame.sample_rate = rate
            resampler = av.AudioResampler(format=stream.codec_context.format.name, layout="stereo", rate=rate)
            for converted in resampler.resample(frame) + resampler.resample(None):
                container.mux(stream.encode(converted))
        container.mux(stream.encode(None))
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


def test_without_a_decoder_a_compressed_recording_is_refused_with_how_to_convert_it(
        repo, tmp_path, monkeypatch, capsys):
    source = _compressed(tmp_path, ".m4a")
    monkeypatch.setitem(sys.modules, "av", None)  # `import av` now raises ImportError
    assert _import(str(source), "--project", "acme", "--yes") == 1
    assert not (repo / "projects").exists()
    err = capsys.readouterr().err
    assert "call.m4a" in err and "ffmpeg" in err


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


# --- a compressed recording, decoded to the WAV the file pass reads -----------------


def _room_shape(path: Path) -> "tuple[int, int, int, float]":
    with wave.open(str(path), "rb") as w:
        return w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes() / w.getframerate()


@pytest.mark.parametrize("suffix", [".m4a", ".mp3", ".ogg", ".flac"])
def test_a_compressed_recording_is_decoded_into_the_session(repo, tmp_path, client, suffix):
    source = _compressed(tmp_path / "recordings", suffix)
    original = source.read_bytes()
    assert _import(str(source), "--project", "acme", "--yes") == 0

    session_dir = _only_session(repo)
    meta = _meta(session_dir)
    assert meta["source"] == f"file-import (audio: {suffix[1:]})"
    assert meta["imported_from"] == source.name
    rate, channels, width, duration = _room_shape(session_dir / ev.ROOM_AUDIO_FILENAME)
    assert (rate, channels, width) == (16000, 1, 2)
    assert abs(duration - 14) < 0.2
    assert abs(meta_duration(meta) - duration) < 0.2
    assert client.files == [ev.ROOM_AUDIO_FILENAME]
    assert meta[ev.EVIDENCE_KEY] == ev.EVIDENCE_TRANSCRIBED
    assert source.read_bytes() == original
    assert [p.name for p in _sessions(repo).iterdir()] == [session_dir.name]  # no temp dir left


def meta_duration(meta: dict) -> float:
    from datetime import datetime
    return (datetime.fromisoformat(meta["closed_at"]) - datetime.fromisoformat(meta["started_at"])).total_seconds()


def test_a_decoded_recording_keeps_the_voices_apart(repo, tmp_path, client):
    """The decode keeps the sound that tells the speakers apart. The roles come
    from the transcript's labels, so only the voiceprint reads the audio: it
    must flag exactly the one turn the fixture mislabels ("And email."), the
    same as on the uncompressed room in test_evidence_pass."""
    assert _import(str(_compressed(tmp_path, ".m4a")), "--project", "acme", "--yes") == 0
    session_dir = _only_session(repo)
    pass_lines = (session_dir / ev.EVIDENCE_TRANSCRIPT_FILENAME).read_text(encoding="utf-8").splitlines()
    turns = [json.loads(line) for line in pass_lines if line.strip()]
    turns = [turn for turn in turns if "disputed" in turn]
    assert [turn["disputed"] for turn in turns] == [False, False, False, False, True]


def test_a_wav_in_another_format_is_converted_too(repo, tmp_path, client):
    source = tmp_path / "stereo.wav"
    with wave.open(str(source), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(44100)
        w.writeframes(np.full(44100 * 14 * 2, 500, dtype="<i2").tobytes())
    assert _import(str(source), "--project", "acme", "--yes") == 0
    session_dir = _only_session(repo)
    rate, channels, width, duration = _room_shape(session_dir / ev.ROOM_AUDIO_FILENAME)
    assert (rate, channels, width) == (16000, 1, 2) and abs(duration - 14) < 0.1
    assert _meta(session_dir)["source"] == "file-import (audio: wav)"


def test_without_yes_a_compressed_recording_is_measured_and_nothing_is_written(repo, tmp_path, capsys):
    assert _import(str(_compressed(tmp_path, ".mp3")), "--project", "acme") == 0
    assert not (repo / "projects").exists()
    out = capsys.readouterr().out
    assert "call.mp3 (recording): 0.2 min" in out
    assert "decoded to 16 kHz mono WAV" in out


def test_a_long_compressed_recording_is_refused_before_anything_is_decoded(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(soniox_async, "MAX_FILE_DURATION_S", 5)
    assert _import(str(_compressed(tmp_path, ".m4a")), "--project", "acme", "--yes") == 1
    assert not (repo / "projects").exists()
    assert "at most" in capsys.readouterr().err


def test_a_container_with_no_sound_is_refused(repo, tmp_path, capsys):
    assert _import(str(_compressed(tmp_path, ".m4a", seconds=0.0)), "--project", "acme", "--yes") == 1
    assert not (repo / "projects").exists()
    assert "call.m4a" in capsys.readouterr().err


def test_a_folder_lists_compressed_recordings_too(repo, tmp_path, client):
    folder = tmp_path / "phone"
    _compressed(folder, ".m4a", name="a")
    _compressed(folder, ".mp3", name="b")
    assert _import(str(folder), "--project", "acme", "--yes") == 0
    assert sorted(_meta(p)["imported_from"] for p in _sessions(repo).iterdir()) == ["a.m4a", "b.mp3"]


def _mixed_bitrate_mp3(directory: Path) -> Path:
    """Two MP3s joined byte for byte, at 32 and 192 kbps: 7 s each. ffmpeg's
    header estimate (file size over the FIRST frame's bitrate) reads this as
    far longer than 14 s -- the shape a VBR phone export without a Xing
    header has, and what two real podcast MP3s showed (243 s for 219 s)."""
    import av

    directory.mkdir(parents=True, exist_ok=True)
    parts = []
    for kbps in (32, 192):
        part = directory / f"part-{kbps}.mp3"
        rate = 44100
        t = np.arange(7 * rate) / rate
        mono = (3000 * np.sin(2 * np.pi * 440 * t)).astype("<i2")
        with av.open(str(part), "w") as container:
            stream = container.add_stream("libmp3lame", rate=rate, layout="mono")
            stream.bit_rate = kbps * 1000
            frame = av.AudioFrame.from_ndarray(mono.reshape(1, -1), format="s16p", layout="mono")
            frame.sample_rate = rate
            resampler = av.AudioResampler(format=stream.codec_context.format.name, layout="mono", rate=rate)
            for converted in resampler.resample(frame) + resampler.resample(None):
                container.mux(stream.encode(converted))
            container.mux(stream.encode(None))
        parts.append(part.read_bytes())
        part.unlink()
    path = directory / "joined.mp3"
    path.write_bytes(b"".join(parts))
    return path


def test_the_length_is_measured_from_the_packets_not_the_header_estimate(tmp_path):
    import av
    from app.session import audio_decode

    source = _mixed_bitrate_mp3(tmp_path)
    with av.open(str(source)) as container:
        estimate = float(container.duration / 1_000_000)
    assert abs(estimate - 14) > 3, f"the fixture no longer fools the header estimate ({estimate:.1f}s)"
    decoded = audio_decode.to_wav(source, tmp_path / "out.wav").seconds
    assert abs(decoded - 14) < 0.2
    assert abs(audio_decode.probe(source) - decoded) < 0.1


class _Packet:
    def __init__(self, good: bool):
        self._good = good

    def decode(self):
        import av
        if not self._good:
            raise av.InvalidDataError(1094995529, "Invalid data found when processing input")
        frame = av.AudioFrame.from_ndarray(np.full((1, 1024), 2000, dtype="<i2"), format="s16", layout="mono")
        frame.sample_rate = 16000
        return [frame]


class _Container:
    def __init__(self, pattern: str):
        self.streams = type("S", (), {"audio": ["stream"]})()
        self._pattern = pattern

    def demux(self, stream):
        return [_Packet(mark == "+") for mark in self._pattern]

    def close(self):
        pass


@pytest.mark.parametrize("pattern, refused", [("+" * 99 + "-", False), ("+" * 90 + "-" * 10, True)])
def test_a_glitch_is_skipped_but_a_damaged_recording_is_refused(tmp_path, monkeypatch, caplog, pattern, refused):
    from app.session import audio_decode

    monkeypatch.setattr(audio_decode, "_open", lambda path: _Container(pattern))
    destination = tmp_path / "out.wav"
    if refused:
        with pytest.raises(audio_decode.DecodeError, match="10 of 100"):
            audio_decode.to_wav(tmp_path / "in.m4a", destination)
        return
    result = audio_decode.to_wav(tmp_path / "in.m4a", destination)
    assert abs(result.seconds - 99 * 1024 / 16000) < 0.01
    assert (result.bad_packets, result.packets) == (1, 100)
    assert "skipped 1 of 100" in caplog.text


def _middle_damaged_mp3(directory: Path) -> Path:
    """An mp3 whose middle third is overwritten with random bytes: the demuxer
    resyncs past the junk, so few PACKETS fail -- the audio is simply gone."""
    source = _compressed(directory, ".mp3", name="damaged")
    data = bytearray(source.read_bytes())
    third = len(data) // 3
    data[third:2 * third] = np.random.default_rng(7).integers(0, 256, third, dtype=np.uint8).tobytes()
    source.write_bytes(bytes(data))
    return source


# The damaged file really is shorter, so the fake transcript's last turns fall
# past its end and the test embedder averages an empty span.
@pytest.mark.filterwarnings("ignore:Mean of empty slice", "ignore:invalid value encountered")
def test_a_recording_with_damaged_audio_says_so_to_the_operator(repo, tmp_path, client, capsys):
    """Not refused: every decoder, the ffmpeg command line included, gives the
    shorter audio. Measured on this fixture, neither the packet length nor the
    share of bytes read tells it from a healthy file (99.7% read; a healthy
    10-minute m4a reads 74.8%), so the one honest signal -- packets that would
    not decode -- is shown to the operator, not only logged."""
    source = _middle_damaged_mp3(tmp_path)
    assert _import(str(source), "--project", "acme", "--yes") == 0
    out = capsys.readouterr().out
    assert "damaged.mp3" in out and "would not decode and were skipped" in out


def test_a_decode_failure_while_writing_leaves_no_session(repo, tmp_path, monkeypatch):
    from app.session import audio_decode, audio_import

    source = _compressed(tmp_path, ".m4a")
    monkeypatch.setattr(audio_decode, "MAX_BAD_PACKET_SHARE", -1.0)  # every file now counts as damaged
    sessions = tmp_path / "sessions"
    with pytest.raises(audio_decode.DecodeError):
        audio_import.write_session(sessions, source, {}, started=datetime(2026, 3, 4), decode=True)
    assert list(sessions.iterdir()) == []


class _TimestampOnlyPacket:
    def __init__(self, pts: int):
        self.pts, self.duration, self.time_base = pts, 0, Fraction(1, 1000)


class _TimestampOnlyContainer:
    """A stream whose packets carry timestamps but no durations, as some
    browser-recorded webm does."""
    streams = type("S", (), {"audio": ["stream"]})()

    def demux(self, stream):
        return [_TimestampOnlyPacket(pts) for pts in range(0, 10_000, 20)] + [_TimestampOnlyPacket(None)]

    def close(self):
        pass


def test_a_stream_without_packet_durations_is_measured_from_its_timestamps(monkeypatch):
    from app.session import audio_decode

    monkeypatch.setattr(audio_decode, "_open", lambda path: _TimestampOnlyContainer())
    assert abs(audio_decode.probe(Path("x.webm")) - 10.0) < 0.05
