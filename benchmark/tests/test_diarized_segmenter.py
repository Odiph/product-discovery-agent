"""`DiarizedSegmenter`: finalized, speaker-tagged tokens in; one Segment per turn out.

Why it exists: with diarization on, end-of-turn detection has to be OFF --
measured on a real one-microphone meeting, endpoint detection dropped
diarization agreement from 87% to 56% -- so the `<end>` marker the two-stream
path relies on never arrives. Turns have to be cut from the tokens themselves:
a change of speaker, a pause, or a turn running long enough that the coach
should see it before it ends.
"""

from __future__ import annotations

from benchmark.engines.diarized import DiarizedSegmenter


def tok(text, start_ms, end_ms, speaker="1", language="en"):
    return {"text": text, "start_ms": start_ms, "end_ms": end_ms, "speaker": speaker, "language": language}


def seg(**kw):
    return DiarizedSegmenter(**{"gap_s": 0.8, "max_s": 12.0, "idle_flush_s": 1.5, **kw})


def test_a_change_of_speaker_closes_the_turn():
    s = seg()
    out = s.feed([tok("Hi", 0, 300, "1"), tok(" there", 300, 600, "1"), tok("Hello", 700, 1000, "2")],
                 ready_wall_s=5.0, now=5.0)
    assert [(x.text, x.speaker_label) for x in out] == [("Hi there", "1")]
    assert out[0].speech_start_s == 0.0 and out[0].audio_end_s == 0.6
    assert out[0].ready_wall_s == 5.0


def test_the_open_turn_is_held_until_something_closes_it():
    s = seg()
    assert s.feed([tok("Hi", 0, 300)], ready_wall_s=1.0, now=1.0) == []
    rest = s.flush(ready_wall_s=2.0)
    assert [(x.text, x.speaker_label) for x in rest] == [("Hi", "1")]


def test_a_pause_of_at_least_gap_s_closes_the_turn_even_for_the_same_speaker():
    s = seg()
    out = s.feed([tok("one", 0, 400), tok(" two", 500, 900), tok(" three", 1800, 2100)], ready_wall_s=3.0, now=3.0)
    assert [x.text for x in out] == ["one two"]


def test_a_pause_just_under_gap_s_does_not():
    s = seg()
    out = s.feed([tok("one", 0, 400), tok(" two", 1199, 1500)], ready_wall_s=2.0, now=2.0)
    assert out == []


def test_a_long_monologue_is_cut_at_max_s_so_the_coach_sees_it_before_it_ends():
    s = seg(max_s=5.0)
    words = [tok(f" w{i}", i * 400, i * 400 + 350) for i in range(20)]  # 8 s, no pauses
    out = s.feed(words, ready_wall_s=9.0, now=9.0)
    assert len(out) == 1
    assert out[0].audio_end_s - out[0].speech_start_s <= 5.0
    assert out[0].speaker_label == "1"


def test_a_stale_open_turn_is_flushed_by_tick_after_idle_flush_s():
    s = seg()
    s.feed([tok("Hi", 0, 300)], ready_wall_s=1.0, now=10.0)
    assert s.tick(ready_wall_s=1.2, now=11.0) == []
    out = s.tick(ready_wall_s=1.6, now=11.6)
    assert [x.text for x in out] == ["Hi"]
    assert s.tick(ready_wall_s=3.0, now=20.0) == []


def test_endpoint_markers_and_empty_tokens_are_ignored():
    s = seg()
    s.feed([tok("Hi", 0, 300), {"text": "<end>", "start_ms": 0, "end_ms": 0}, tok("", 300, 300)],
           ready_wall_s=1.0, now=1.0)
    assert [x.text for x in s.flush(ready_wall_s=1.0)] == ["Hi"]


def test_a_token_with_no_speaker_joins_the_current_turn():
    s = seg()
    s.feed([tok("Hi", 0, 300, "2"), {"text": ",", "start_ms": 300, "end_ms": 320, "language": "en"}],
           ready_wall_s=1.0, now=1.0)
    out = s.flush(ready_wall_s=1.0)
    assert [(x.text, x.speaker_label) for x in out] == [("Hi,", "2")]


def test_language_is_the_character_weighted_majority_via_the_injected_rule():
    s = DiarizedSegmenter(gap_s=0.8, max_s=12.0, idle_flush_s=1.5,
                          language_of=lambda toks: "he" if any(t.get("language") == "he" for t in toks) else "en")
    s.feed([tok("ok", 0, 200, language="en"), tok(" שלום", 200, 600, language="he")], ready_wall_s=1.0, now=1.0)
    assert s.flush(ready_wall_s=1.0)[0].detected_language == "he"


def test_turns_across_several_feeds_keep_their_boundaries():
    s = seg()
    a = s.feed([tok("A1", 0, 300, "1")], ready_wall_s=1.0, now=1.0)
    b = s.feed([tok(" A2", 350, 600, "1"), tok("B1", 700, 900, "2")], ready_wall_s=2.0, now=2.0)
    c = s.flush(ready_wall_s=3.0)
    assert a == []
    assert [(x.text, x.speaker_label) for x in b + c] == [("A1 A2", "1"), ("B1", "2")]
