"""Soniox async (file) transcription -- the after-meeting pass of an
in-person session. No vendor SDK, stdlib HTTP only (no new dependency).

Why a file pass at all: with one microphone the live stream's speaker labels
were right for ~87% of words, and Soniox's own guidance is that async
diarization is the more accurate one. The live roles drive coaching; this
pass is what evidence is built from.

Flow confirmed AT IMPLEMENTATION TIME (2026-10-20) against Soniox's docs
(soniox.com/docs/stt/async/async-transcription and the API reference):
- base https://api.soniox.com, `Authorization: Bearer <key>`
- POST /v1/files (multipart field `file`) -> {"id": file_id}
- POST /v1/transcriptions {"model", "file_id", "enable_speaker_diarization"}
  -> {"id": transcription_id}
- GET /v1/transcriptions/{id} until `status` is terminal. The guide's loop
  names "completed"/"error"; the reference's error text names "failed". Both
  are treated as terminal failures here.
- GET /v1/transcriptions/{id}/transcript -> {"tokens": [{text, start_ms,
  end_ms, confidence, speaker, language}]}
- DELETE /v1/transcriptions/{id}, DELETE /v1/files/{id}

The vendor copy of the meeting audio is deleted on EVERY exit path -- success,
a failed job, a timeout, a crash between upload and create. Deletion itself is
best-effort (a failure is logged, never raised over the original error).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional, Union

SONIOX_API_URL = "https://api.soniox.com"
DEFAULT_ASYNC_MODEL = "stt-async-v5"
TERMINAL_OK = "completed"
TERMINAL_FAILED = frozenset({"error", "failed"})
DEFAULT_POLL_INTERVAL_S = 3.0
# A one-hour meeting transcribes in a few minutes; this only stops a hung job
# from holding the operator's terminal forever.
DEFAULT_TIMEOUT_S = 1800.0
HTTP_TIMEOUT_S = 120.0
# docs.soniox.com/stt/async/limits-and-quotas (read 2026-11-09): "File duration:
# 300 minutes. This limit is fixed and cannot be increased." No byte-size cap is
# documented (storage: 10 GB across all files). Checked locally, so a meeting
# the vendor would refuse is never uploaded in the first place.
MAX_FILE_DURATION_S = 300 * 60
# The upload streams from disk in pieces this size, never the whole file.
UPLOAD_CHUNK_BYTES = 1024 * 1024

logger = logging.getLogger(__name__)

# (method, url, headers, body) -> (status, body). Injected by tests. The body is
# bytes, None, or (the upload) an iterable of chunks with Content-Length set.
Body = Optional[Union[bytes, Iterable[bytes]]]
Transport = Callable[[str, str, "dict[str, str]", Body], "tuple[int, bytes]"]


class SonioxAsyncConfigError(Exception):
    """Missing or invalid configuration. Never carries key material."""


class SonioxAsyncError(Exception):
    """The vendor refused, failed, or timed out. Never carries key material."""


class RedirectRefused(urllib.error.URLError):
    """The API answered with a redirect. Never followed: urllib copies the
    request's headers onto the redirected request, so following it would hand
    the Bearer key (and the meeting audio) to whatever host `Location` names.
    An `OSError`, so `_request` reports it as a failed call like any other."""


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 -- stdlib signature
        # Neither the target URL nor any header goes into the message: the
        # target is attacker-chosen text and the headers carry the key.
        raise RedirectRefused(f"HTTP {code} redirect refused")


# Built once: the default handler chain, with redirects refused instead of followed.
_OPENER = urllib.request.build_opener(_RefuseRedirects)

# What may appear in the multipart `filename`: a quote or CR/LF would end the
# header early, and anything beyond this set (a person's name in Hebrew, say)
# tells the vendor nothing the pass needs.
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _safe_upload_name(path: Path) -> str:
    stem = _UNSAFE_NAME_CHARS.sub("", path.stem).strip(".") or "audio"
    return stem + _UNSAFE_NAME_CHARS.sub("", path.suffix)


def urllib_transport(method: str, url: str, headers: "dict[str, str]", body: Body) -> "tuple[int, bytes]":
    # urllib sends an iterable body piece by piece; with Content-Length set by
    # the caller it is not chunk-encoded.
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with _OPENER.open(request, timeout=HTTP_TIMEOUT_S) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class SonioxAsyncClient:
    def __init__(
        self,
        *,
        api_key: str,
        transport: Transport = urllib_transport,
        model: str = DEFAULT_ASYNC_MODEL,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_duration_s: float = MAX_FILE_DURATION_S,
    ) -> None:
        self._key = api_key
        self._transport = transport
        self._model = model
        self._poll_interval_s = poll_interval_s
        self._timeout_s = timeout_s
        self._sleep = sleep
        self._clock = clock
        self._max_duration_s = max_duration_s
        self.cleanup_failures: "list[str]" = []

    @classmethod
    def from_env(cls, **kwargs) -> "SonioxAsyncClient":
        # `.strip()` for the same reason as the realtime engine: an exported
        # but blank variable is truthy.
        api_key = (os.environ.get("SONIOX_API_KEY") or "").strip()
        if not api_key:
            raise SonioxAsyncConfigError(
                "SONIOX_API_KEY is not set. Read from the environment only -- see benchmark/README.md."
            )
        return cls(api_key=api_key, **kwargs)

    def transcribe_file(self, path: Path) -> "list[dict]":
        """Diarized tokens for a local audio file, in time order.

        Afterwards `cleanup_failures` names every vendor object that could NOT
        be deleted (empty when the vendor holds nothing), so the caller can
        tell the operator rather than claim a deletion that did not happen."""
        self.cleanup_failures: "list[str]" = []
        self._refuse_if_too_long(Path(path))
        # Unique per upload: if the upload times out after the vendor stored
        # the file, this name is the only way to find it again.
        upload_name = f"{uuid.uuid4().hex}-{_safe_upload_name(Path(path))}"
        try:
            file_id = self._upload(Path(path), upload_name)
        except SonioxAsyncError:
            self._delete_orphan_upload(upload_name)
            raise
        transcription_id: Optional[str] = None
        try:
            try:
                transcription_id = self._json("POST", "/v1/transcriptions", {
                    "model": self._model,
                    "file_id": file_id,
                    "enable_speaker_diarization": True,
                    "enable_language_identification": True,
                })["id"]
            except SonioxAsyncError:
                self._delete_orphan_transcriptions(file_id)
                raise
            self._wait(transcription_id)
            tokens = self._json("GET", f"/v1/transcriptions/{transcription_id}/transcript").get("tokens") or []
            return sorted(tokens, key=lambda t: (t.get("start_ms") or 0))
        finally:
            if transcription_id is not None:
                self._delete(f"/v1/transcriptions/{transcription_id}")
            self._delete(f"/v1/files/{file_id}")

    # --- steps ---------------------------------------------------------------

    def _delete_orphan_upload(self, upload_name: str) -> None:
        """An upload that failed client-side may still have landed."""
        try:
            listing = self._json("GET", "/v1/files?limit=1000")
        except SonioxAsyncError:
            self.cleanup_failures.append(f"file {upload_name} (could not list files to check)")
            return
        for item in listing.get("files") or []:
            if item.get("filename") == upload_name and item.get("id"):
                self._delete(f"/v1/files/{item['id']}")

    def _delete_orphan_transcriptions(self, file_id: str) -> None:
        """A create that failed client-side may still have started a job.
        Best-effort: the listing's shape is not in the docs this was checked
        against, so an unrecognised one is reported, never guessed at."""
        try:
            listing = self._json("GET", "/v1/transcriptions?limit=1000")
        except SonioxAsyncError:
            self.cleanup_failures.append(f"transcription for file {file_id} (could not list to check)")
            return
        for item in listing.get("transcriptions") or []:
            if item.get("file_id") == file_id and item.get("id"):
                self._delete(f"/v1/transcriptions/{item['id']}")

    def _refuse_if_too_long(self, path: Path) -> None:
        """Only a WAV is measured (the in-person room audio is one); anything
        else, or a header that does not parse, is left to the vendor."""
        try:
            with wave.open(str(path), "rb") as audio:
                seconds = audio.getnframes() / float(audio.getframerate())
        except (wave.Error, EOFError, OSError, ZeroDivisionError):
            return
        if seconds > self._max_duration_s:
            raise SonioxAsyncError(
                f"the recording is {seconds / 60:.0f} minutes; the file pass accepts at most "
                f"{self._max_duration_s / 60:.0f} minutes per file. Nothing was uploaded."
            )

    def _upload(self, path: Path, upload_name: str) -> str:
        """Streams the file from disk: a 90-minute meeting is ~170 MB, and the
        old single-body upload held it in memory about twice over."""
        boundary = uuid.uuid4().hex
        head = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{upload_name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
        ])
        tail = f"\r\n--{boundary}--\r\n".encode()
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(head) + path.stat().st_size + len(tail)),
        }
        return self._request("POST", "/v1/files", _multipart_stream(head, path, tail), headers)["id"]

    def _wait(self, transcription_id: str) -> None:
        deadline = self._clock() + self._timeout_s
        while True:
            job = self._json("GET", f"/v1/transcriptions/{transcription_id}")
            status = job.get("status")
            if status == TERMINAL_OK:
                return
            if status in TERMINAL_FAILED:
                raise SonioxAsyncError(f"transcription {status}: {job.get('error_message') or 'no message'}")
            if self._clock() >= deadline:
                raise SonioxAsyncError(f"transcription did not finish within {self._timeout_s:.0f} s (last status: {status})")
            self._sleep(self._poll_interval_s)

    def _delete(self, path: str) -> None:
        try:
            status, _ = self._transport("DELETE", SONIOX_API_URL + path, self._headers(), None)
            ok = status < 400 or status == 404
            if not ok:
                logger.warning("vendor cleanup failed path=%s status=%s", path, status)
        except Exception as exc:  # noqa: BLE001 -- cleanup must never mask the real error
            logger.warning("vendor cleanup failed path=%s error_type=%s", path, type(exc).__name__)
            ok = False
        if not ok:
            self.cleanup_failures.append(path)

    # --- HTTP ----------------------------------------------------------------

    def _json(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        return self._request(method, path, body, headers)

    def _request(self, method: str, path: str, body: Body, extra: "dict[str, str]") -> dict:
        try:
            status, raw = self._transport(method, SONIOX_API_URL + path, {**self._headers(), **extra}, body)
        except OSError as exc:
            raise SonioxAsyncError(f"{method} {path} failed: {type(exc).__name__}") from exc
        if status >= 400:
            raise SonioxAsyncError(f"{method} {path} returned HTTP {status}: {_message(raw)}")
        try:
            return json.loads(raw or b"{}")
        except ValueError as exc:
            raise SonioxAsyncError(f"{method} {path} returned a non-JSON body") from exc

    def _headers(self) -> "dict[str, str]":
        return {"Authorization": f"Bearer {self._key}"}


def _multipart_stream(head: bytes, path: Path, tail: bytes) -> "Iterator[bytes]":
    yield head
    with open(path, "rb") as audio:
        while True:
            chunk = audio.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            yield chunk
    yield tail


def _message(raw: bytes) -> str:
    try:
        parsed = json.loads(raw)
    except ValueError:
        return "no message"
    if isinstance(parsed, dict):
        return str(parsed.get("message") or parsed.get("error_message") or "no message")[:200]
    return "no message"
