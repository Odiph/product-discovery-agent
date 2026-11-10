"""The after-meeting commands through `main()`: `diarize-after`,
`confirm-speakers`, and `extract`'s refusal of an unconfirmed in-person session.

`diarize-after` is driven with an injected client and model loader only:
through `main()` it would read the real key from .env and upload audio.
"""

from __future__ import annotations

import json

import pytest

from app import evidence_cli
from app.main import main
from app.session import evidence as ev
from app.tests import test_evidence_pass as fixtures


@pytest.fixture
def session(tmp_path):
    d = tmp_path / "20261020T100000"
    d.mkdir()
    (d / "session.json").write_text(json.dumps({
        "capture": "in-person", ev.EVIDENCE_KEY: ev.EVIDENCE_PENDING, "closed_at": "2026-10-20T10:30:00+00:00",
    }), encoding="utf-8")
    fixtures._room(d / ev.ROOM_AUDIO_FILENAME, fixtures.SPANS, 14)
    return d


class FakeClient:
    def __init__(self):
        self.files = []

    def transcribe_file(self, path):
        self.files.append(path.name)
        return list(fixtures.TOKENS)


def _diarize(session, client=None):
    client = client or FakeClient()
    code = evidence_cli.run_diarize_after(
        session, client_factory=lambda: client, embedder_loader=lambda: (fixtures.CodedEmbedder(), ""),
        enrol_s=4.0,  # the fixture room is 14 s; production enrols over 120 s
    )
    return code, client


def _meta(session):
    return json.loads((session / "session.json").read_text(encoding="utf-8"))


def test_extract_refuses_an_unconfirmed_in_person_session_before_any_key_or_vendor(session, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["extract", str(session)]) == 1
    err = capsys.readouterr().err
    assert "confirm-speakers" in err and "ANTHROPIC_API_KEY" not in err


def test_diarize_after_uploads_the_room_and_writes_the_evidence(session, capsys):
    code, client = _diarize(session)
    assert code == 0 and client.files == [ev.ROOM_AUDIO_FILENAME]
    assert _meta(session)[ev.EVIDENCE_KEY] == ev.EVIDENCE_TRANSCRIBED
    out = capsys.readouterr().out
    assert "5 turns, 1 disputed" in out and "confirm-speakers" in out


def test_diarize_after_without_a_key_stops_cleanly(session, capsys):
    from benchmark.engines.soniox_async import SonioxAsyncConfigError

    def no_key():
        raise SonioxAsyncConfigError("SONIOX_API_KEY is not set.")

    assert evidence_cli.run_diarize_after(session, client_factory=no_key, embedder_loader=lambda: (None, "x")) == 1
    assert _meta(session)[ev.EVIDENCE_KEY] == ev.EVIDENCE_PENDING


def test_confirm_speakers_without_confirm_only_shows(session, capsys):
    _diarize(session)
    capsys.readouterr()
    assert main(["confirm-speakers", str(session)]) == 0
    out = capsys.readouterr().out
    assert "INTERVIEWER" in out and "Do I have your consent?" in out
    assert "DISPUTED by the voiceprint (1)" in out and "--disputed" in out
    assert _meta(session)[ev.EVIDENCE_KEY] == ev.EVIDENCE_TRANSCRIBED
    assert (session / ev.ROOM_AUDIO_FILENAME).exists()


def test_confirm_speakers_refuses_until_the_disputed_side_is_chosen(session, capsys):
    _diarize(session)
    assert main(["confirm-speakers", str(session), "--confirm"]) == 1
    assert "disputed" in capsys.readouterr().err


class _Captured(Exception):
    pass


def test_a_confirmed_session_is_extracted_from_the_evidence_not_the_live_roles(session, tmp_path, monkeypatch):
    _diarize(session)
    # The live transcript says the opposite of the evidence for every turn.
    live = [{**r, "speaker": "interviewee" if r["speaker"] == "interviewer" else "interviewer"}
            for r in ev.segment_fields(json.loads(l) for l in
                                       (session / ev.EVIDENCE_TRANSCRIPT_FILENAME).read_text(encoding="utf-8").splitlines())]
    (session / "transcript.jsonl").write_text("".join(json.dumps(r) + "\n" for r in live), encoding="utf-8")
    assert main(["confirm-speakers", str(session), "--confirm", "--disputed", "label"]) == 0

    seen = {}

    def capture(client, *, transcript, **kwargs):
        seen["speakers"] = [s.speaker for s in transcript]
        raise _Captured

    monkeypatch.setenv("APP_CONTEXT_DIR", str(tmp_path / "context"))
    monkeypatch.setattr("app.coach.reasoning_client.build_client", lambda: object())
    monkeypatch.setattr("app.coach.extract.extract_facts", capture)
    with pytest.raises(_Captured):
        main(["extract", str(session)])
    assert seen["speakers"] == ["interviewer", "interviewee", "interviewer", "interviewee", "interviewer"]


def test_confirm_then_extract_gets_past_the_gate(session, capsys, monkeypatch):
    _diarize(session)
    assert main(["confirm-speakers", str(session), "--confirm", "--disputed", "voiceprint"]) == 0
    assert not (session / ev.ROOM_AUDIO_FILENAME).exists()
    # Past the gate, extract reaches the key check: proof the refusal is gone,
    # without making a paid call.
    monkeypatch.setattr("app.coach.reasoning_client.build_client",
                        lambda: (_ for _ in ()).throw(__import__("app.coach.reasoning_client", fromlist=["x"]).CoachConfigError("no key in test")))
    capsys.readouterr()
    assert main(["extract", str(session)]) == 1
    err = capsys.readouterr().err
    assert "no key in test" in err and "confirm-speakers" not in err


def test_accept_live_roles_needs_confirm_then_unlocks_extract(session, capsys):
    assert main(["confirm-speakers", str(session), "--accept-live-roles"]) == 1
    assert _meta(session)[ev.EVIDENCE_KEY] == ev.EVIDENCE_PENDING
    assert main(["confirm-speakers", str(session), "--confirm", "--accept-live-roles"]) == 0
    assert _meta(session)[ev.EVIDENCE_SOURCE_KEY] == ev.EVIDENCE_SOURCE_LIVE
    assert not (session / ev.ROOM_AUDIO_FILENAME).exists()


def test_diarize_after_warns_when_the_vendor_kept_a_copy(session, capsys):
    client = FakeClient()
    client.cleanup_failures = ["/v1/files/file-1"]
    _diarize(session, client)
    assert "/v1/files/file-1" in capsys.readouterr().err
