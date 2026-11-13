"""`python -m app import <file-or-folder>`: a past interview's transcript export
becomes a session, so `extract`, `standing`, `themes`, `mirror` and
`critique-questions` can see it.

The words in these fixtures stand for a customer's speech, so every test that
reads the terminal also asserts none of them was printed.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest

from app import main as main_mod
from app import projects as projects_mod
from app.session.reader import read_session
from app.session.store import SegmentRecord

SPOKEN = "we export everything to a spreadsheet every friday"
HEBREW = "אנחנו מייצאים הכל"

VTT = f"""WEBVTT

00:00:01.000 --> 00:00:04.500
<v Sam>How do you handle the weekly report today?

00:00:05.000 --> 00:00:09.250
<v Dana>Honestly {SPOKEN}.

00:00:09.500 --> 00:00:12.000
<v Dana>{HEBREW}

00:00:12.500 --> 00:00:15.000
<v Sam>When did you last do that?
"""

PLAIN = f"""Sam: How do you handle the weekly report today?
Dana: Honestly {SPOKEN}.
Sam: When did you last do that?
Dana: Last friday, it took two hours.
"""

PLAIN_TIMED = f"""[00:03] Sam: How do you handle the weekly report today?
[00:09] Dana: Honestly {SPOKEN}.
[01:15] Sam: When did you last do that?
[01:20] Dana: Last friday, it took two hours.
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(projects_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(tmp_path / "context"))
    return tmp_path


def _write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _import(*argv: str) -> int:
    return main_mod.main(["import", *argv])


def _sessions(repo: Path, node: str = "acme") -> Path:
    return repo / "projects" / node / "sessions"


def _only_session(repo: Path) -> Path:
    found = [p for p in _sessions(repo).iterdir() if p.is_dir()]
    assert len(found) == 1, found
    return found[0]


def _meta(session_dir: Path) -> dict:
    return json.loads((session_dir / "session.json").read_text(encoding="utf-8"))


def _segments(session_dir: Path) -> "list[dict]":
    return list(read_session(session_dir).records_of_kind("segment"))


# --- a subtitle file, end to end ------------------------------------------------


def test_a_vtt_becomes_one_closed_session_with_the_live_segment_shape(repo, tmp_path, capsys):
    source = _write(tmp_path / "exports", "dana-call.vtt", VTT)
    assert _import(str(source), "--project", "acme", "--me", "Sam", "--date", "2026-03-04", "--yes") == 0

    session_dir = _only_session(repo)
    assert session_dir.name.startswith("20260304T")
    segments = _segments(session_dir)
    # Exactly the keys the live store writes -- built from the dataclass, so a
    # field added there and forgotten here fails.
    expected_keys = {f.name for f in dataclasses.fields(SegmentRecord)}
    assert all(set(s) == expected_keys for s in segments)
    assert [s["speaker"] for s in segments] == ["interviewer", "interviewee", "interviewer"]
    assert [s["seq"] for s in segments] == [0, 1, 2]
    # Consecutive Dana cues are one turn: first cue's start, last cue's end.
    assert segments[1]["audio_start_s"] == 5.0 and segments[1]["audio_end_s"] == 12.0
    assert all(s["kind"] == "segment" and s["engine"] == "import" for s in segments)
    assert [s["detected_language"] for s in segments] == ["en", "he", "en"]

    meta = _meta(session_dir)
    assert meta["engine"] == "import"
    assert meta["source"] == "file-import (transcript: vtt)"
    assert meta["participant"] == "Dana"
    assert meta["audio_retained"] is False
    assert meta["coach_enabled"] is False
    assert meta["started_at"].startswith("2026-03-04T")
    assert "closed_at" in meta
    assert meta["times_synthetic"] is False
    assert read_session(session_dir).closed

    out = capsys.readouterr().out
    assert SPOKEN not in out and "weekly report" not in out


def test_imported_from_is_the_file_name_never_its_path(repo, tmp_path):
    source = _write(tmp_path / "private-folder-name", "dana-call.vtt", VTT)
    _import(str(source), "--project", "acme", "--me", "Sam", "--yes")
    raw = (_only_session(repo) / "session.json").read_text(encoding="utf-8")
    assert _meta(_only_session(repo))["imported_from"] == "dana-call.vtt"
    assert "private-folder-name" not in raw


def test_without_a_date_the_file_time_is_used_and_flagged(repo, tmp_path):
    source = _write(tmp_path, "call.vtt", VTT)
    stamp = 1_700_000_000  # 2023-11-14
    os.utime(source, (stamp, stamp))
    _import(str(source), "--project", "acme", "--me", "Sam", "--yes")
    meta = _meta(_only_session(repo))
    assert meta["started_at_source"] == "file-mtime"
    assert _only_session(repo).name.startswith("2023111")


# --- plain text -------------------------------------------------------------------


def test_plain_text_without_times_gets_synthetic_monotonic_times_and_says_so(repo, tmp_path):
    source = _write(tmp_path, "notes.txt", PLAIN)
    assert _import(str(source), "--project", "acme", "--me", "sam", "--yes") == 0
    session_dir = _only_session(repo)
    segments = _segments(session_dir)
    assert [s["speaker"] for s in segments] == ["interviewer", "interviewee", "interviewer", "interviewee"]
    ends = [s["audio_end_s"] for s in segments]
    starts = [s["audio_start_s"] for s in segments]
    assert all(a < b for a, b in zip(ends, ends[1:]))
    assert all(start < end for start, end in zip(starts, ends))
    meta = _meta(session_dir)
    assert meta["times_synthetic"] is True
    assert meta["source"] == "file-import (transcript: text)"


def test_plain_text_label_times_are_used(repo, tmp_path):
    source = _write(tmp_path, "notes.txt", PLAIN_TIMED)
    _import(str(source), "--project", "acme", "--me", "Sam", "--yes")
    session_dir = _only_session(repo)
    starts = [s["audio_start_s"] for s in _segments(session_dir)]
    assert starts == [3.0, 9.0, 75.0, 80.0]
    assert _meta(session_dir)["times_synthetic"] is False


def test_a_text_file_that_is_not_a_speaker_transcript_is_refused(repo, tmp_path, capsys):
    source = _write(tmp_path, "notes.txt", "Just some notes.\nNothing labelled here.\n")
    assert _import(str(source), "--project", "acme", "--me", "Sam", "--yes") == 1
    assert not _sessions(repo).exists()
    assert "speaker" in capsys.readouterr().err


# --- the dry run and refusals ---------------------------------------------------


def test_without_yes_it_prints_the_plan_and_writes_nothing(repo, tmp_path, capsys):
    source = _write(tmp_path, "dana-call.vtt", VTT)
    assert _import(str(source), "--project", "acme", "--me", "Sam") == 0
    assert not (repo / "projects").exists()
    out = capsys.readouterr().out
    assert "dana-call.vtt" in out
    assert "Sam" in out and "Dana" in out
    assert "interviewer" in out
    assert "--yes" in out
    assert SPOKEN not in out and "weekly report" not in out and HEBREW not in out


def test_me_naming_no_speaker_refuses_and_lists_the_speakers(repo, tmp_path, capsys):
    source = _write(tmp_path, "dana-call.vtt", VTT)
    assert _import(str(source), "--project", "acme", "--me", "Someone", "--yes") == 1
    assert not _sessions(repo).exists()
    err = capsys.readouterr().err
    assert "Someone" in err and "Sam" in err and "Dana" in err


def test_more_than_two_speakers_keeps_every_other_as_interviewee_and_says_so(repo, tmp_path, capsys):
    text = PLAIN + "Avi: I agree with Dana on that.\nAvi: Me too, really.\n"
    source = _write(tmp_path, "group.txt", text)
    assert _import(str(source), "--project", "acme", "--me", "Sam", "--yes") == 0
    session_dir = _only_session(repo)
    assert [s["speaker"] for s in _segments(session_dir)][-1] == "interviewee"
    # Two people besides you: nobody to infer as THE participant.
    assert "participant" not in _meta(session_dir)
    assert "3 speakers" in capsys.readouterr().out


def test_a_compressed_audio_file_is_refused_with_the_conversion(repo, tmp_path, capsys):
    source = tmp_path / "call.m4a"
    source.write_bytes(b"\x00\x01")
    assert _import(str(source), "--project", "acme", "--me", "Sam", "--yes") == 1
    assert not _sessions(repo).exists()
    assert "ffmpeg" in capsys.readouterr().err


def test_an_explicit_participant_wins(repo, tmp_path):
    source = _write(tmp_path, "dana-call.vtt", VTT)
    _import(str(source), "--project", "acme", "--me", "Sam", "--participant", "Dana Levi, ops", "--yes")
    assert _meta(_only_session(repo))["participant"] == "Dana Levi, ops"


def test_a_malformed_date_is_refused_by_argparse(repo, tmp_path):
    source = _write(tmp_path, "dana-call.vtt", VTT)
    with pytest.raises(SystemExit):
        _import(str(source), "--project", "acme", "--me", "Sam", "--date", "04/03/2026")


# --- idempotence and ids --------------------------------------------------------


def test_importing_the_same_file_twice_refuses_naming_the_existing_session(repo, tmp_path, capsys):
    source = _write(tmp_path, "dana-call.vtt", VTT)
    assert _import(str(source), "--project", "acme", "--me", "Sam", "--yes") == 0
    first = _only_session(repo).name
    capsys.readouterr()
    assert _import(str(source), "--project", "acme", "--me", "Sam", "--yes") == 1
    assert _only_session(repo).name == first
    assert first in capsys.readouterr().err


def test_the_same_content_under_another_name_is_still_a_duplicate(repo, tmp_path):
    _import(str(_write(tmp_path, "a.vtt", VTT)), "--project", "acme", "--me", "Sam", "--yes")
    assert _import(str(_write(tmp_path, "b.vtt", VTT)), "--project", "acme", "--me", "Sam", "--yes") == 1
    _only_session(repo)


def test_two_interviews_on_one_date_get_distinct_sortable_ids(repo, tmp_path):
    _import(str(_write(tmp_path, "a.vtt", VTT)), "--project", "acme", "--me", "Sam",
            "--date", "2026-03-04", "--yes")
    _import(str(_write(tmp_path, "b.txt", PLAIN)), "--project", "acme", "--me", "Sam",
            "--date", "2026-03-04", "--yes")
    _import(str(_write(tmp_path, "c.txt", PLAIN_TIMED)), "--project", "acme", "--me", "Sam",
            "--date", "2026-01-02", "--yes")
    names = sorted(p.name for p in _sessions(repo).iterdir())
    assert len(set(names)) == 3
    assert names[0].startswith("20260102T")
    assert names[1].startswith("20260304T") and names[2].startswith("20260304T")


# --- a folder ---------------------------------------------------------------------


def test_a_folder_imports_every_supported_file_and_refuses_bad_audio_by_name(repo, tmp_path, capsys):
    folder = tmp_path / "exports"
    _write(folder, "b-call.txt", PLAIN)
    _write(folder, "a-call.vtt", VTT)
    (folder / "c-call.wav").write_bytes(b"RIFF")
    (folder / "readme.pdf").write_bytes(b"%PDF")
    assert _import(str(folder), "--project", "acme", "--me", "Sam", "--yes") == 1
    sources = sorted(_meta(p)["imported_from"] for p in _sessions(repo).iterdir())
    assert sources == ["a-call.vtt", "b-call.txt"]
    err = capsys.readouterr().err
    assert "c-call.wav" in err and "not a readable PCM WAV" in err


def test_a_folder_refuses_one_participant_for_many_files(repo, tmp_path, capsys):
    folder = tmp_path / "exports"
    _write(folder, "a.vtt", VTT)
    _write(folder, "b.txt", PLAIN)
    assert _import(str(folder), "--project", "acme", "--me", "Sam", "--participant", "Dana", "--yes") == 2
    assert not _sessions(repo).exists()
    assert "--participant" in capsys.readouterr().err


# --- downstream commands see it -------------------------------------------------


def test_forget_erases_an_imported_session(repo, tmp_path):
    source = _write(tmp_path, "dana-call.vtt", VTT)
    _import(str(source), "--project", "acme", "--me", "Sam", "--yes")
    session_id = _only_session(repo).name
    assert main_mod.main(["forget", session_id, "--project", "acme", "--yes"]) == 0
    assert not (_sessions(repo) / session_id).exists()
    # And once forgotten, the same file may be imported again.
    assert _import(str(source), "--project", "acme", "--me", "Sam", "--yes") == 0


def test_no_temporary_directory_is_left_behind(repo, tmp_path):
    _import(str(_write(tmp_path, "a.vtt", VTT)), "--project", "acme", "--me", "Sam", "--yes")
    node = repo / "projects" / "acme"
    assert sorted(p.name for p in node.iterdir()) == ["sessions"]
