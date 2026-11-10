"""`AudioRing`: the last few minutes of sent audio, addressable on the engine's clock.

The voiceprint check needs the audio of a turn the engine has just finalized,
several seconds after it was sent. Soniox's token times count from the first
audio it received, so the ring is indexed by samples SENT, including the
zero-filled frames: skipping those would shift every later turn.
"""

from __future__ import annotations

from app.stt.audio_ring import AudioRing

SR = 16000


def pcm(n_samples, value):
    return int(value).to_bytes(2, "little", signed=True) * n_samples


def test_a_slice_returns_exactly_the_samples_of_that_time_span():
    ring = AudioRing(sample_rate=SR, max_s=10.0)
    ring.append(pcm(SR, 1))       # 0.0 - 1.0 s
    ring.append(pcm(SR, 2))       # 1.0 - 2.0 s
    got = ring.slice(0.5, 1.5)
    assert len(got) == SR * 2      # 1 s of 16-bit mono
    assert got[:2] == pcm(1, 1) and got[-2:] == pcm(1, 2)


def test_silence_frames_count_on_the_clock():
    ring = AudioRing(sample_rate=SR, max_s=10.0)
    ring.append(pcm(SR, 0))       # a zero-filled second
    ring.append(pcm(SR, 7))
    assert ring.slice(1.0, 2.0) == pcm(SR, 7)


def test_audio_older_than_max_s_is_gone_and_a_slice_of_it_is_empty():
    ring = AudioRing(sample_rate=SR, max_s=2.0)
    for v in range(1, 6):
        ring.append(pcm(SR, v))   # 5 s total, keeps the last 2
    assert ring.slice(0.0, 1.0) == b""
    assert ring.slice(4.0, 5.0) == pcm(SR, 5)


def test_a_slice_partly_out_of_range_is_clipped_not_padded():
    ring = AudioRing(sample_rate=SR, max_s=10.0)
    ring.append(pcm(SR, 3))
    assert ring.slice(0.5, 9.0) == pcm(SR // 2, 3)
    assert ring.slice(5.0, 6.0) == b""
