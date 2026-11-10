"""The async (file) Soniox client behind the in-person evidence pass.

Driven through a fake transport: no network, no key spent. What matters here
is the contract with the vendor (auth, model, diarization on), that a failed
or slow job raises instead of returning a partial transcript, and that the
uploaded meeting audio is deleted from the vendor on EVERY path -- the room
recording of a customer meeting must not outlive the pass that needed it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.engines import soniox_async as sa


class FakeTransport:
    def __init__(self, statuses=("queued", "transcribing", "completed"), tokens=None, fail_on=None):
        self.calls: "list[tuple[str, str, dict, bytes]]" = []
        self._statuses = list(statuses)
        self._tokens = tokens if tokens is not None else [
            {"text": "Hi", "start_ms": 0, "end_ms": 300, "speaker": "1", "language": "en"},
        ]
        self._fail_on = fail_on
        self.stored: "list[dict]" = []
        self.undeletable: "set[str]" = set()

    def __call__(self, method, url, headers, body):
        if body is not None and not isinstance(body, bytes):
            body = b"".join(body)  # the upload streams; the fake reads it whole
        self.calls.append((method, url, headers, body))
        path = url.split("api.soniox.com", 1)[1]
        if method == "POST" and path == "/v1/files":
            # The vendor stores the upload even when the client then fails.
            name = body.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            self.stored.append({"id": "file-1", "filename": name})
        if method == "GET" and path == "/v1/files?limit=1000":
            return 200, json.dumps({"files": self.stored, "next_page_cursor": None}).encode()
        if method == "DELETE" and path in self.undeletable:
            return 500, b"{}"
        if self._fail_on and self._fail_on == (method, path.split("/")[2] if path.count("/") >= 2 else path):
            return 500, b'{"message": "boom"}'
        if method == "POST" and path == "/v1/files":
            return 201, json.dumps({"id": "file-1"}).encode()
        if method == "POST" and path == "/v1/transcriptions":
            return 201, json.dumps({"id": "tr-1"}).encode()
        if method == "GET" and path == "/v1/transcriptions/tr-1":
            status = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
            body_out = {"id": "tr-1", "status": status}
            if status in ("error", "failed"):
                body_out["error_message"] = "audio unreadable"
            return 200, json.dumps(body_out).encode()
        if method == "GET" and path == "/v1/transcriptions/tr-1/transcript":
            return 200, json.dumps({"id": "tr-1", "text": "Hi", "tokens": self._tokens}).encode()
        if method == "DELETE":
            return 204, b""
        return 404, b"{}"

    def paths(self, method):
        return [url.split("api.soniox.com", 1)[1] for m, url, _, _ in self.calls if m == method]


def _client(transport, **kw):
    return sa.SonioxAsyncClient(api_key="k-test", transport=transport, poll_interval_s=0, sleep=lambda s: None, **kw)


@pytest.fixture
def wav(tmp_path):
    path = tmp_path / "room.wav"
    path.write_bytes(b"RIFF....WAVEfmt fake")
    return path


def test_a_file_is_uploaded_transcribed_with_diarization_and_its_tokens_returned(wav):
    t = FakeTransport()
    tokens = _client(t).transcribe_file(wav)

    assert tokens == [{"text": "Hi", "start_ms": 0, "end_ms": 300, "speaker": "1", "language": "en"}]
    method, url, headers, body = t.calls[0]
    assert (method, url) == ("POST", "https://api.soniox.com/v1/files")
    assert headers["Authorization"] == "Bearer k-test"
    assert b'name="file"; filename="' in body and b'-room.wav"' in body and b"RIFF....WAVEfmt fake" in body

    create = json.loads(next(b for m, u, _, b in t.calls if m == "POST" and u.endswith("/v1/transcriptions")))
    assert create == {
        "model": sa.DEFAULT_ASYNC_MODEL,
        "file_id": "file-1",
        "enable_speaker_diarization": True,
        "enable_language_identification": True,
    }


def test_the_vendor_copy_is_deleted_after_success(wav):
    t = FakeTransport()
    _client(t).transcribe_file(wav)
    assert t.paths("DELETE") == ["/v1/transcriptions/tr-1", "/v1/files/file-1"]


@pytest.mark.parametrize("terminal", ["error", "failed"])
def test_a_failed_job_raises_and_still_deletes_the_vendor_copy(wav, terminal):
    t = FakeTransport(statuses=("transcribing", terminal))
    with pytest.raises(sa.SonioxAsyncError, match="audio unreadable"):
        _client(t).transcribe_file(wav)
    assert t.paths("DELETE") == ["/v1/transcriptions/tr-1", "/v1/files/file-1"]


def test_a_job_that_never_finishes_times_out_and_still_deletes(wav):
    t = FakeTransport(statuses=("transcribing",))
    with pytest.raises(sa.SonioxAsyncError, match="did not finish"):
        _client(t, timeout_s=0, clock=iter([0.0, 1.0, 2.0, 3.0]).__next__).transcribe_file(wav)
    assert "/v1/files/file-1" in t.paths("DELETE")


def test_a_failed_create_deletes_the_uploaded_file(wav):
    t = FakeTransport(fail_on=("POST", "transcriptions"))
    with pytest.raises(sa.SonioxAsyncError):
        _client(t).transcribe_file(wav)
    assert t.paths("DELETE") == ["/v1/files/file-1"]


def test_an_http_error_message_never_echoes_the_key(wav):
    t = FakeTransport(fail_on=("POST", "files"))
    with pytest.raises(sa.SonioxAsyncError) as info:
        _client(t).transcribe_file(wav)
    assert "k-test" not in str(info.value)


def test_a_blank_key_is_refused_before_any_request(monkeypatch):
    monkeypatch.setenv("SONIOX_API_KEY", "   ")
    with pytest.raises(sa.SonioxAsyncConfigError):
        sa.SonioxAsyncClient.from_env()


def test_an_upload_that_fails_client_side_but_landed_is_found_and_deleted(wav):
    t = FakeTransport(fail_on=("POST", "files"))
    client = _client(t)
    with pytest.raises(sa.SonioxAsyncError):
        client.transcribe_file(wav)
    assert t.paths("DELETE") == ["/v1/files/file-1"]
    assert client.cleanup_failures == []


def test_each_upload_gets_its_own_name_so_only_ours_is_deleted(wav):
    t = FakeTransport(fail_on=("POST", "files"))
    t.stored.append({"id": "someone-else", "filename": "room.wav"})
    with pytest.raises(sa.SonioxAsyncError):
        _client(t).transcribe_file(wav)
    assert "/v1/files/someone-else" not in t.paths("DELETE")


def test_a_delete_the_vendor_refuses_is_reported_not_claimed(wav):
    t = FakeTransport()
    t.undeletable.add("/v1/files/file-1")
    client = _client(t)
    client.transcribe_file(wav)
    assert client.cleanup_failures == ["/v1/files/file-1"]


def test_a_clean_run_reports_no_cleanup_failures(wav):
    client = _client(FakeTransport())
    client.transcribe_file(wav)
    assert client.cleanup_failures == []


# --- the upload streams; an over-long meeting never leaves the laptop ----------


def _real_wav(path, seconds, rate=16000):
    import wave

    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


class StreamRecorder(FakeTransport):
    def __call__(self, method, url, headers, body):
        if method == "POST" and url.endswith("/v1/files"):
            self.upload_type = type(body)
            self.chunks = list(body)
            self.upload_headers = headers
            body = b"".join(self.chunks)
        return super().__call__(method, url, headers, body)


def test_the_upload_streams_in_bounded_chunks_with_an_exact_length(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "UPLOAD_CHUNK_BYTES", 1000)
    room = _real_wav(tmp_path / "room.wav", 0.5)  # 16 KB of audio
    t = StreamRecorder()
    _client(t).transcribe_file(room)

    assert t.upload_type is not bytes  # never one in-memory body
    assert max(len(c) for c in t.chunks) <= 1000
    body = b"".join(t.chunks)
    assert int(t.upload_headers["Content-Length"]) == len(body)
    assert room.read_bytes() in body and b'name="file"; filename="' in body
    assert body.endswith(b"--\r\n")


def test_a_recording_over_the_vendors_duration_cap_is_refused_before_any_upload(tmp_path):
    room = _real_wav(tmp_path / "room.wav", 1.0)
    t = FakeTransport()
    with pytest.raises(sa.SonioxAsyncError) as raised:
        _client(t, max_duration_s=0.5).transcribe_file(room)
    assert t.calls == []  # nothing sent, so nothing to delete
    assert "minutes" in str(raised.value)


def test_the_documented_cap_is_300_minutes():
    assert sa.MAX_FILE_DURATION_S == 300 * 60


def test_urllib_transport_sends_a_streamed_body_with_its_length_not_chunked():
    import http.server
    import threading

    received = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 -- stdlib name
            received["te"] = self.headers.get("Transfer-Encoding")
            received["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(201)
            self.end_headers()
            self.wfile.write(b'{"id": "x"}')

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        chunks = [b"ab", b"cd", b"ef"]
        status, raw = sa.urllib_transport(
            "POST", f"http://127.0.0.1:{server.server_port}/v1/files",
            {"Content-Length": "6", "Content-Type": "application/octet-stream"}, iter(chunks),
        )
    finally:
        server.shutdown()
    assert (status, raw) == (201, b'{"id": "x"}')
    assert received == {"te": None, "body": b"abcdef"}


# --- the multipart header and the Authorization header stay ours ---------------


def _uploaded_filename(transport):
    body = next(body for method, url, _, body in transport.calls if method == "POST" and url.endswith("/v1/files"))
    return body.split(b'filename="', 1)[1].split(b'"', 1)[0]


# Built from code points so the source stays ASCII: a carriage return and
# Hebrew letters (the word for "file") written literally are easy to mangle.
CRLF = chr(13) + chr(10)
HEBREW_WORD = "".join(map(chr, (0x5E7, 0x5D5, 0x5D1, 0x5E5)))


@pytest.mark.parametrize("name, expected", [
    ('room"' + CRLF + 'X-Injected: 1.wav', "roomX-Injected1.wav"),
    (HEBREW_WORD + " x.wav", "x.wav"),
    (HEBREW_WORD + ".wav", "audio.wav"),
    ("..wav", "audio.wav"),
    ("noext", "noext"),
    ("meeting 2026-11-10.wav", "meeting2026-11-10.wav"),
])
def test_the_upload_name_carries_only_safe_characters(name, expected):
    # A local file name reaches a multipart HEADER: a quote or a newline in it
    # would end the header early, and a person's name in it is sent to the
    # vendor for no reason the pass needs.
    assert sa._safe_upload_name(Path(name)) == expected


def test_the_uploaded_header_names_a_sanitised_file(tmp_path):
    audio = tmp_path / (HEBREW_WORD + " meeting.wav")
    audio.write_bytes(b"RIFF....WAVEfmt fake")
    t = FakeTransport()
    _client(t).transcribe_file(audio)
    uploaded = _uploaded_filename(t).decode("ascii")
    assert uploaded.endswith("-meeting.wav")
    assert all(c.isascii() and (c.isalnum() or c in "._-") for c in uploaded)


def test_urllib_transport_refuses_a_redirect_rather_than_forwarding_the_key():
    # urllib follows a 3xx by default and copies the request's headers onto the
    # new request, Authorization included -- a redirect would hand the API key
    # to whatever host the Location names.
    import http.server
    import threading

    seen = {"target": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 -- stdlib name
            if self.path == "/target":
                seen["target"] += 1
                seen["auth"] = self.headers.get("Authorization")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
                return
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/target")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(OSError) as raised:
            sa.urllib_transport(
                "GET", f"http://127.0.0.1:{server.server_port}/v1/files",
                {"Authorization": "Bearer k-test"}, None,
            )
    finally:
        server.shutdown()
    assert seen["target"] == 0
    assert "k-test" not in str(raised.value)


def test_a_refused_redirect_surfaces_as_a_vendor_error(wav):
    def redirecting(method, url, headers, body):
        raise sa.RedirectRefused("redirect refused")

    with pytest.raises(sa.SonioxAsyncError):
        _client(redirecting).transcribe_file(wav)
