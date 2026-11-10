"""`app.stt.voiceprint`: the speaker-embedding model behind the in-person role check.

The model is downloaded on an explicit command, never silently, into a
git-ignored `models/` folder, and a file whose SHA-256 does not match the pinned
value is refused and deleted: a swapped model is the one failure that would
quietly assign turns to the wrong person. Missing library or model degrades to
the engine's own labels, with the reason, and never stops a meeting.

Measured, not asserted here: on a real one-microphone meeting this model
(3D-Speaker ERes2Net, Apache-2.0) gave 97.4% held-out turn accuracy, while a
different model of the same size (WeSpeaker CAM++) gave 49.5%. The model is
therefore pinned by hash, not by name.
"""

from __future__ import annotations

import hashlib
import math
import subprocess

import numpy as np
import pytest

from app.stt import voiceprint


def test_the_models_folder_is_git_ignored():
    result = subprocess.run(["git", "check-ignore", "-q", "models/x.onnx"], cwd=voiceprint.REPO_ROOT)
    assert result.returncode == 0, "models/ must be git-ignored: a 25 MB binary does not belong in the repo"


def test_a_missing_model_degrades_with_a_reason(tmp_path):
    embedder, reason = voiceprint.load_embedder(tmp_path / "absent.onnx")
    assert embedder is None
    assert "fetch-voiceprint-model" in reason


def test_a_model_whose_hash_does_not_match_is_refused(tmp_path):
    fake = tmp_path / voiceprint.MODEL_FILENAME
    fake.write_bytes(b"not the model")
    embedder, reason = voiceprint.load_embedder(fake)
    assert embedder is None
    assert "hash" in reason.lower()


def test_fetch_verifies_the_download_and_deletes_a_bad_one(tmp_path, monkeypatch):
    monkeypatch.setattr(voiceprint, "_download", lambda url, dest: dest.write_bytes(b"tampered"))
    with pytest.raises(voiceprint.ModelIntegrityError):
        voiceprint.fetch_model(tmp_path)
    assert not (tmp_path / voiceprint.MODEL_FILENAME).exists()


def test_fetch_keeps_a_download_whose_hash_matches(tmp_path, monkeypatch):
    payload = b"pretend model bytes"
    monkeypatch.setattr(voiceprint, "MODEL_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(voiceprint, "_download", lambda url, dest: dest.write_bytes(payload))
    path = voiceprint.fetch_model(tmp_path)
    assert path.read_bytes() == payload


def test_the_pinned_url_is_the_official_release_and_https():
    assert voiceprint.MODEL_URL.startswith("https://github.com/k2-fsa/sherpa-onnx/releases/download/")
    assert voiceprint.MODEL_URL.endswith(voiceprint.MODEL_FILENAME)


@pytest.mark.skipif(not voiceprint.default_model_path().is_file(), reason="voiceprint model not fetched on this machine")
def test_the_real_model_embeds_audio_into_a_finite_unit_vector():
    embedder, reason = voiceprint.load_embedder()
    assert embedder is not None, reason
    t = np.arange(16000 * 2) / 16000
    pcm = (0.2 * np.sin(2 * math.pi * 220 * t) * 32767).astype("<i2").tobytes()
    v = embedder.embed(pcm, 16000)
    assert v.ndim == 1 and v.size >= 64 and np.all(np.isfinite(v))
