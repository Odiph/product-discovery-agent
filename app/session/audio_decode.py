"""A recording in any common format, decoded to the WAV the file pass reads.

The file pass reads 16 kHz mono 16-bit WAV (app/stt/evidence_pass.py), and a
phone hands over m4a, mp3 or opus. PyAV (the `av` package, ffmpeg's libraries
in a wheel) decodes them here, so the operator never needs ffmpeg installed.

Rules, each a decision:

- **Probe reads, decode writes.** `probe` reports the length without
  decoding the sound, so a recording too long for the file pass is refused
  before any work. `to_wav` is the only function that writes.
- **The length is counted from the packets, never the header.** For an MP3
  without a Xing header ffmpeg ESTIMATES the length from the file size and the
  first frame's bitrate; on two real podcast MP3s that read 243 s for 219 s
  and 258 s for 300 s. Reading every packet's timestamp (demuxing, not
  decoding) gave both exactly, in 30 ms.
- **A packet that will not decode is skipped, not fatal.** One glitch in a
  phone recording must not refuse the interview: the ffmpeg command line skips
  it too, and a skipped MP3 packet is 26 ms. Only a recording where more than
  `MAX_BAD_PACKET_SHARE` of the packets fail is refused, and every skip is
  logged with its count.
- **Streamed, never whole.** An hour of 16 kHz mono is about 115 MB; the
  decode writes frame by frame and never holds the recording in memory.
- **The first audio stream only.** A video call export carries a picture
  stream too; it is skipped, never decoded.
- **`av` is imported lazily.** Without it a compressed recording is refused
  with the conversion command, and every other command keeps working.
"""

from __future__ import annotations

import logging
import statistics
import wave
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
# Above this share of undecodable packets the file is damaged, not glitched.
MAX_BAD_PACKET_SHARE = 0.05


@dataclass(frozen=True)
class Decoded:
    seconds: float
    packets: int
    # Skipped, not fatal (see the module docstring). Shown to the operator.
    bad_packets: int


class DecodeError(ValueError):
    """A recording that cannot be decoded, in the operator's words. Never
    quotes the file's content."""


def _av():
    try:
        import av
    except ImportError as exc:
        raise DecodeError("cannot be decoded here: the `av` package is not installed") from exc
    return av


def _open(path: Path):
    av = _av()
    try:
        container = av.open(str(path), "r")
    except (av.FFmpegError, OSError, ValueError) as exc:
        raise DecodeError(f"is not a recording this can read ({type(exc).__name__})") from exc
    if not container.streams.audio:
        container.close()
        raise DecodeError("holds no audio stream")
    return container


def probe(path: Path) -> float:
    """The recording's length in seconds, from its packets' timestamps.
    Decodes nothing. Raises `DecodeError`, including for one with no sound."""
    av = _av()
    container = _open(Path(path))
    stream = container.streams.audio[0]
    first = last_start = previous = None
    end = 0.0
    # Packet lengths, or the gaps between packet starts where a stream (some
    # browser-recorded webm) carries timestamps but no durations.
    lengths: "list[float]" = []
    try:
        for packet in container.demux(stream):
            if packet.pts is None:
                continue  # the flush packet demux ends with
            begins = float(packet.pts * packet.time_base)
            first = begins if first is None else min(first, begins)
            last_start = begins if last_start is None else max(last_start, begins)
            if packet.duration:
                lengths.append(float(packet.duration * packet.time_base))
                end = max(end, begins + lengths[-1])
            elif previous is not None and begins > previous:
                lengths.append(begins - previous)
            previous = begins
    except av.FFmpegError as exc:
        raise DecodeError(f"is not a recording this can read ({type(exc).__name__})") from exc
    finally:
        container.close()
    if first is None:
        raise DecodeError("holds no audio")
    # The last packet lasts a typical packet even when it does not say so.
    end = max(end, last_start + (statistics.median(lengths) if lengths else 0.0))
    if end <= first:
        raise DecodeError("holds no audio")
    return end - first


def to_wav(source: Path, destination: Path) -> Decoded:
    """Decode `source` to 16 kHz mono 16-bit WAV at `destination`. Raises
    `DecodeError`; a partial `destination` is left for the caller, whose
    temporary session directory is removed on failure."""
    av = _av()
    container = _open(Path(source))
    stream = container.streams.audio[0]
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    frames = packets = bad = 0
    try:
        with wave.open(str(destination), "wb") as out:
            out.setnchannels(CHANNELS)
            out.setsampwidth(SAMPLE_WIDTH_BYTES)
            out.setframerate(SAMPLE_RATE)
            for packet in container.demux(stream):
                packets += 1
                try:
                    decoded = packet.decode()
                except av.InvalidDataError:
                    bad += 1
                    continue
                for audio in decoded:
                    for frame in resampler.resample(audio):
                        frames += _write(out, frame)
            for frame in resampler.resample(None):
                frames += _write(out, frame)
    except av.FFmpegError as exc:
        raise DecodeError(f"could not be decoded ({type(exc).__name__})") from exc
    finally:
        container.close()
    if bad:
        logger.warning("skipped %d of %d audio packets that would not decode", bad, packets)
    if packets and bad > MAX_BAD_PACKET_SHARE * packets:
        raise DecodeError(f"is damaged: {bad} of {packets} audio packets would not decode")
    if frames == 0:
        raise DecodeError("holds no audio")
    return Decoded(seconds=frames / float(SAMPLE_RATE), packets=packets, bad_packets=bad)


def _write(out: "wave.Wave_write", frame) -> int:
    samples = frame.to_ndarray().reshape(-1)
    out.writeframes(samples.astype("<i2", copy=False).tobytes())
    return samples.shape[0]
