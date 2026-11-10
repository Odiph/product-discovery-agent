"""The speaker-embedding model behind the in-person role check.

sherpa-onnx (Apache-2.0, offline, CPU) running 3D-Speaker's ERes2Net
(Apache-2.0, per its ModelScope card). Chosen by measurement on a real
one-microphone meeting: 97.4% held-out turn accuracy, where WeSpeaker CAM++,
a model of the same size, managed 49.5%. So the model is pinned by SHA-256,
not by name, and a mismatching file is refused.

Downloaded only by `python -m app fetch-voiceprint-model`, into the
git-ignored `models/` folder. Everything here degrades: without the library or
the model, `load_embedder` returns None and a reason, and the role check falls
back to the engine's own speaker labels.
"""

from __future__ import annotations

import hashlib
import logging
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_FILENAME = "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
    + MODEL_FILENAME
)
# Matches the checksum.txt published with that release (verified 2026-09-24).
MODEL_SHA256 = "c59158379255ad66e161679cca6af8d52d51e389e3224ab7d7a7baae295c2db5"
FETCH_HINT = "run `python -m app fetch-voiceprint-model` once to download it"


class ModelIntegrityError(Exception):
    pass


def default_model_path() -> Path:
    return REPO_ROOT / "models" / MODEL_FILENAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as out:  # noqa: S310 -- pinned https URL
        while chunk := response.read(1 << 20):
            out.write(chunk)


def fetch_model(models_dir: Optional[Path] = None) -> Path:
    """Download the pinned model and verify it. A mismatch deletes the file."""
    folder = models_dir or default_model_path().parent
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / MODEL_FILENAME
    partial = dest.with_suffix(".part")
    _download(MODEL_URL, partial)
    actual = _sha256(partial)
    if actual != MODEL_SHA256:
        partial.unlink(missing_ok=True)
        raise ModelIntegrityError(
            f"downloaded voiceprint model has SHA-256 {actual}, expected {MODEL_SHA256}; deleted it"
        )
    partial.replace(dest)
    return dest


class SherpaEmbedder:
    def __init__(self, extractor) -> None:
        self._extractor = extractor

    def embed(self, pcm16: bytes, sample_rate: int) -> "np.ndarray":
        samples = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate, samples)
        stream.input_finished()
        return np.asarray(self._extractor.compute(stream), dtype=np.float64)


def load_embedder(model_path: Optional[Path] = None) -> "tuple[Optional[SherpaEmbedder], str]":
    """(embedder, "") when ready; (None, reason) otherwise."""
    path = Path(model_path) if model_path else default_model_path()
    if not path.is_file():
        return None, f"voiceprint model not found at {path}; {FETCH_HINT}"
    if _sha256(path) != MODEL_SHA256:
        return None, f"voiceprint model at {path} has the wrong hash; delete it and {FETCH_HINT}"
    try:
        import sherpa_onnx
    except ImportError:
        return None, "sherpa-onnx is not installed; run `pip install -r requirements.txt`"
    try:
        extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(path), num_threads=2)
        )
    except Exception as exc:  # noqa: BLE001 -- a broken model must not stop a meeting
        return None, f"voiceprint model failed to load: {type(exc).__name__}"
    return SherpaEmbedder(extractor), ""
