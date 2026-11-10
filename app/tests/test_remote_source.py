"""`RemoteAudioSource`: the phone's microphone as a capture stream.

Audio arrives over a websocket in bursts, at the network's pace. The engine and
the worker assume cumulative audio tracks wall time 1:1 (a frame every
`frame_ms`, zero-filled when there is none), because Soniox's clock is audio
SENT. So the source buffers what the phone sends and paces it out, exactly
like `CaptureStream` paces a device -- and when the phone goes quiet (screen
locked, network gone) it emits synthesized silence, which is what makes the
existing supervisor raise `idle` instead of the transcript silently stopping.
"""

from __future__ import annotations

import numpy as np

from app.capture.remote import RemoteAudioSource

SR = 16000
FRAME_MS = 150
FRAME_BYTES = SR * FRAME_MS // 1000 * 2


def src(**kw):
    return RemoteAudioSource(sample_rate=SR, frame_ms=FRAME_MS, queue_max_seconds=5.0, **kw)


def tone(n_bytes, value=1000):
    return (np.full(n_bytes // 2, value, dtype="<i2")).tobytes()


def test_buffered_phone_audio_comes_out_as_real_frames_of_exactly_frame_ms():
    s = src()
    s.push(tone(FRAME_BYTES * 2))
    s._emit_one_frame(); s._emit_one_frame()
    frames = [s.queue.get_nowait() for _ in range(2)]
    assert [f.kind for f in frames] == ["real", "real"]
    assert all(len(f.pcm16) == FRAME_BYTES for f in frames)
    assert [f.seq for f in frames] == [0, 1]
    assert s.health.last_real_audio_monotonic is not None


def test_no_phone_audio_means_synthesized_silence_on_schedule():
    s = src()
    s._emit_one_frame()
    f = s.queue.get_nowait()
    assert f.kind == "synthesized" and f.pcm16 == b"\x00" * FRAME_BYTES
    assert s.health.consecutive_synthesized_frames == 1


def test_a_partial_frame_waits_for_the_rest_rather_than_being_padded():
    s = src()
    s.push(tone(FRAME_BYTES // 2))
    s._emit_one_frame()
    assert s.queue.get_nowait().kind == "synthesized"
    s.push(tone(FRAME_BYTES // 2))
    s._emit_one_frame()
    assert s.queue.get_nowait().kind == "real"


def test_an_odd_byte_split_across_pushes_keeps_samples_aligned():
    s = src()
    whole = tone(FRAME_BYTES, value=0x1234)
    s.push(whole[:1001]); s.push(whole[1001:])
    s._emit_one_frame()
    assert s.queue.get_nowait().pcm16 == whole


def test_a_backlog_beyond_the_cap_drops_the_oldest_audio_and_counts_it():
    s = src(max_backlog_s=0.3)            # two frames' worth
    s.push(tone(FRAME_BYTES * 5))
    assert s.buffered_seconds() <= 0.3 + 1e-9
    assert s.health.dropped_frame_count == 3


def test_the_level_probe_measures_only_real_audio():
    s = src()
    s._emit_one_frame()
    assert s.recent_peak_dbfs() is None
    s.push(tone(FRAME_BYTES, value=16384))
    s._emit_one_frame()
    assert -7.0 < s.recent_peak_dbfs() < -5.0   # 16384 / 32768 = -6 dBFS


def test_it_presents_a_device_the_supervisor_and_session_metadata_can_name():
    s = src()
    assert s.device.identity == "remote:phone-microphone"
    assert s.device.native_sample_rate == SR and s.device.channels == 1
    assert not s.is_dead
    s.mark_dead()
    assert s.is_dead
