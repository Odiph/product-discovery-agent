"""Topics interviewees kept raising, and whether the interviewer followed up
(app/coach/missed.py, app/coach/missed_load.py, app/missed_cli.py).

The talk's climax as a number: "In 8 of 12 interviews, interviewees raised
the break between rounds. You followed up in 0." Every fixture below is
hand-built so each count can be checked by eye.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import main as main_mod
from app.coach import interview_summary as summary_mod
from app.coach import missed as missed_mod
from app.coach import missed_load
from app.coach import walked_past as wp

OPENER = "Tell me about your last match night."
OFFER_A = "In the break between rounds I usually open my notes and review the last fight."
MOVE_1 = "Which headset brand do you prefer for evening sessions?"
ASIDE = "A cheap wired one from a market stall."
MOVE_2 = "How many friends join your squad on weekends?"
OFFER_B = "While I sit in the matchmaking queue I check my build status on the phone."
OFFER_B_HE = "כשאני מחכה בתור למשחק אני בודק את הסטטוס של הבילד בטלפון"
ANSWER = "Usually under a minute or so."
MOVE_3 = "What snacks do you keep at the desk?"
SPOKEN_SENTINEL = "spokensentinelzz"

# seq of each turn in `_transcript`: one segment per turn.
SEQ_OFFER_A, SEQ_OFFER_B = 1, 5


def _transcript(reply_b, offer_b=OFFER_B):
    return [("interviewer", OPENER), ("interviewee", OFFER_A + " " + SPOKEN_SENTINEL), ("interviewer", MOVE_1),
            ("interviewee", ASIDE), ("interviewer", MOVE_2), ("interviewee", offer_b),
            ("interviewer", reply_b), ("interviewee", ANSWER), ("interviewer", MOVE_3)]


def _records(turns):
    return [{"kind": "segment", "seq": i, "speaker": sp, "text": tx, "audio_end_s": 10.0 * (i + 1)}
            for i, (sp, tx) in enumerate(turns)]


TRANSCRIPTS = {
    "S1": _transcript("Wait, what do you mean?"),
    "S2": _transcript("רגע, תסביר לי יותר", offer_b=OFFER_B_HE),
    "S3": _transcript("Do you stream your games to anyone?"),
    "S4": _transcript("Do you stream your games to anyone?"),
}

TOPIC_A = [  # the break between rounds: raised in four interviews, walked past in all
    ("a1", "S1", "During the break between rounds she reviews her last fight.", ()),
    ("a2", "S2", "He uses the break between rounds to stretch his wrists.", ()),
    ("a3", "S3", "The break between rounds is when she reads the team chat.", ()),
    # Bound to a hypothesis as CONTRARY evidence, and still a topic.
    ("a4", "S4", "Between rounds, in the short break, he opens his notes.", (("h1", "undermines"),)),
]
TOPIC_B = [  # the matchmaking queue: raised in three, followed up in two
    ("b1", "S1", "He checks build status during the matchmaking queue.", ()),
    ("b2", "S2", "She checks her build status while in the matchmaking queue.", ()),
    ("b3", "S3", "In the matchmaking queue he checks build status on his phone.", ()),
]
TOPIC_C = [  # two interviews only: below the floor
    ("c1", "S1", "She prefers a mechanical keyboard with brown switches.", ()),
    ("c2", "S2", "His mechanical keyboard has brown switches.", ()),
]
NOISE = [
    ("n1", "S3", "Her cat sleeps on the router.", ()),
    ("n2", "S4", "He commutes by ferry.", ()),
]


def _claim(fact_id, session_id, claim, bearings=(), seqs=None):
    if seqs is None:
        seqs = (SEQ_OFFER_A,) if fact_id.startswith("a") else (SEQ_OFFER_B,) if fact_id.startswith("b") else (3,)
    return missed_mod.CitedClaim(fact_id=fact_id, session_id=session_id, claim=claim,
                                 bearings=tuple(bearings), seqs=tuple(seqs))


def _claims(rows=TOPIC_A + TOPIC_B + TOPIC_C + NOISE):
    return [_claim(*row) for row in rows]


def _turns(transcripts=TRANSCRIPTS):
    return {sid: wp.turns(_records(turns)) for sid, turns in transcripts.items()}


def _topic(report, member):
    (topic,) = [t for t in report.topics if member in t.fact_ids]
    return topic


# --- the pure detector --------------------------------------------------------------


def test_a_topic_raised_in_four_interviews_and_walked_past_in_all_is_flagged_first():
    report = missed_mod.find(_claims(), _turns())
    assert report.state == missed_mod.STATE_RESULT
    first = report.topics[0]
    assert set(first.fact_ids) == {"a1", "a2", "a3", "a4"}
    assert set(first.label) >= {"break", "rounds"}
    assert (first.tally.raised_interviews, first.tally.judged_interviews, first.tally.followed_interviews) == (4, 4, 0)
    assert [(o.session_id, o.seq, o.outcome) for o in first.occurrences] == [
        (s, SEQ_OFFER_A, missed_mod.WALKED_PAST) for s in ("S1", "S2", "S3", "S4")]
    assert report.interviews == 4


def test_a_topic_the_interviewer_followed_up_shows_in_how_many():
    topic = _topic(missed_mod.find(_claims(), _turns()), "b1")
    assert (topic.tally.raised_interviews, topic.tally.followed_interviews) == (3, 2)
    assert topic.tally.missed_interviews == 1
    outcomes = {o.session_id: o.outcome for o in topic.occurrences}
    # S1 in English ("what do you mean"), S2 in Hebrew ("תסביר"): neither shares a word with the offer.
    assert outcomes == {"S1": missed_mod.FOLLOWED, "S2": missed_mod.FOLLOWED, "S3": missed_mod.WALKED_PAST}


def test_a_topic_in_two_interviews_is_below_the_floor_and_absent():
    report = missed_mod.find(_claims(), _turns())
    assert not any("c1" in t.fact_ids for t in report.topics)
    assert missed_mod.MIN_INTERVIEWS == 3


def test_the_most_missed_topic_comes_first():
    report = missed_mod.find(_claims(), _turns())
    assert [t.tally.missed_interviews for t in report.topics] == [4, 1]


@pytest.mark.parametrize("reply", [
    "When you say notes, which ones?",
    "Why then, of all moments?",
    "Tell me more about those notes.",
    "מה זאת אומרת?",
    "תסבירי לי למה דווקא אז",
])
def test_follow_up_phrasings_in_english_and_hebrew_count(reply):
    transcripts = {sid: [("interviewer", OPENER), ("interviewee", OFFER_A), ("interviewer", reply),
                         ("interviewee", ASIDE), ("interviewer", MOVE_2)] for sid in ("S1", "S2", "S3", "S4")}
    topic = _topic(missed_mod.find(_claims(TOPIC_A), _turns(transcripts)), "a1")
    assert topic.tally.followed_interviews == 4


def test_a_question_on_the_topics_own_terms_is_a_follow_up_even_two_turns_on():
    # The spoken offer shares no word with the question; only the CLAIMS'
    # shared terms (break, rounds) connect them -- as when the claim is
    # abstracted into English from a Hebrew call.
    offer = "In the pause I usually open my notes and review the last fight."
    transcripts = {sid: [("interviewer", OPENER), ("interviewee", offer), ("interviewer", MOVE_1), ("interviewee", ASIDE),
                         ("interviewer", "Do the breaks feel long enough on a weekend?")]
                   for sid in ("S1", "S2", "S3", "S4")}
    topic = _topic(missed_mod.find(_claims(TOPIC_A), _turns(transcripts)), "a1")
    assert topic.tally.followed_interviews == 4


def test_a_follow_up_past_the_window_is_too_late():
    transcripts = {sid: [("interviewer", OPENER), ("interviewee", OFFER_A), ("interviewer", MOVE_1), ("interviewee", ASIDE),
                         ("interviewer", MOVE_2), ("interviewee", ANSWER),
                         ("interviewer", "Going back, what happens in the break between rounds?")]
                   for sid in ("S1", "S2", "S3", "S4")}
    assert missed_mod.FOLLOW_UP_WINDOW == 2
    topic = _topic(missed_mod.find(_claims(TOPIC_A), _turns(transcripts)), "a1")
    assert (topic.tally.judged_interviews, topic.tally.followed_interviews) == (4, 0)


def test_a_late_back_reference_points_at_the_wrong_turn_and_does_not_count():
    # "Why?" after an unrelated aside is about the aside, not the offer.
    transcripts = {sid: [("interviewer", OPENER), ("interviewee", OFFER_A), ("interviewer", MOVE_1), ("interviewee", ASIDE),
                         ("interviewer", "Why that one and not another?")] for sid in ("S1", "S2", "S3", "S4")}
    topic = _topic(missed_mod.find(_claims(TOPIC_A), _turns(transcripts)), "a1")
    assert (topic.tally.judged_interviews, topic.tally.followed_interviews) == (4, 0)


def test_a_backchannel_does_not_use_up_the_window():
    transcripts = {sid: [("interviewer", OPENER), ("interviewee", OFFER_A), ("interviewer", "Mm, okay."), ("interviewee", ASIDE),
                         ("interviewer", MOVE_1), ("interviewee", ANSWER),
                         ("interviewer", "Do the breaks feel long enough?")]
                   for sid in ("S1", "S2", "S3", "S4")}
    topic = _topic(missed_mod.find(_claims(TOPIC_A), _turns(transcripts)), "a1")
    assert topic.tally.followed_interviews == 4


def test_a_question_reusing_the_offers_own_words_is_a_follow_up():
    # "notes" is the offer's word and in no two claims, so not a topic term.
    transcripts = {sid: [("interviewer", OPENER), ("interviewee", OFFER_A),
                         ("interviewer", "Which notes app do you keep on your phone?")]
                   for sid in ("S1", "S2", "S3", "S4")}
    topic = _topic(missed_mod.find(_claims(TOPIC_A), _turns(transcripts)), "a1")
    assert topic.tally.followed_interviews == 4


def test_a_citation_to_a_missing_seq_is_reported_not_crashed():
    rows = TOPIC_A + [("a5", "S5", "In the break between rounds she refills her water.", ())]
    claims = _claims(rows[:4]) + [_claim(*rows[4], seqs=(99,))]
    transcripts = {**TRANSCRIPTS, "S5": _transcript(MOVE_3)}
    topic = _topic(missed_mod.find(claims, _turns(transcripts)), "a1")
    assert (topic.tally.raised_interviews, topic.tally.judged_interviews) == (5, 4)
    (missing,) = [o for o in topic.occurrences if o.session_id == "S5"]
    assert (missing.seq, missing.outcome) == (99, missed_mod.MISSING_SEQ)


def test_a_session_with_unconfirmed_roles_is_not_judged():
    report = missed_mod.find(_claims(TOPIC_A), _turns(), unconfirmed=frozenset({"S4"}))
    topic = _topic(report, "a1")
    assert topic.tally.judged_interviews == 3
    assert {o.session_id: o.outcome for o in topic.occurrences}["S4"] == missed_mod.ROLES_UNCONFIRMED


def test_a_claim_citing_interviewer_speech_is_not_judged():
    # seq 2 is MOVE_1, the interviewer's; the turn after it is the interviewee's aside.
    claims = _claims(TOPIC_A[:3]) + [_claim(*TOPIC_A[3], seqs=(2,))]
    topic = _topic(missed_mod.find(claims, _turns()), "a1")
    assert {o.session_id: o.outcome for o in topic.occurrences}["S4"] == missed_mod.NOT_INTERVIEWEE
    assert topic.tally.judged_interviews == 3


def test_a_session_with_no_transcript_is_not_judged():
    turns = _turns()
    del turns["S4"]
    topic = _topic(missed_mod.find(_claims(TOPIC_A), turns), "a1")
    assert {o.session_id: o.outcome for o in topic.occurrences}["S4"] == missed_mod.NO_TRANSCRIPT


def test_two_claims_on_one_turn_are_one_occurrence():
    rows = TOPIC_A + [("a9", "S1", "Between rounds, during the break, she opens her notes.", ())]
    topic = _topic(missed_mod.find(_claims(rows), _turns()), "a1")
    assert [o.session_id for o in topic.occurrences].count("S1") == 1


# --- the four states ------------------------------------------------------------------


def test_no_claims_is_its_own_state():
    assert missed_mod.find([], {}).state == missed_mod.STATE_NO_EXTRACTION


def test_no_topic_at_the_floor_is_its_own_state():
    assert missed_mod.find(_claims(TOPIC_C + NOISE), _turns()).state == missed_mod.STATE_NO_TOPIC


def test_topics_with_no_interviewer_turns_are_their_own_state():
    silent = {sid: [("interviewee", OPENER), ("interviewee", OFFER_A)] for sid in ("S1", "S2", "S3", "S4")}
    report = missed_mod.find(_claims(TOPIC_A), _turns(silent))
    assert report.state == missed_mod.STATE_NOTHING_JUDGED
    assert {o.outcome for o in report.topics[0].occurrences} == {missed_mod.NO_QUESTION}


# --- the counting rule lives in interview_summary ---------------------------------------


def test_follow_through_counts_interviews_not_occurrences():
    tally = summary_mod.follow_through([("S1", False), ("S1", True), ("S1", False), ("S2", False), ("S3", None)])
    assert (tally.raised_interviews, tally.judged_interviews, tally.followed_interviews) == (3, 2, 1)
    assert tally.missed_interviews == 1


# --- the projection never holds the quote -----------------------------------------------


def test_the_projection_reads_no_quote():
    class _Fact:
        id, session_id, claim, seqs, bearings = "f1", "S1", "claim", (2, 3), (
            SimpleNamespace(hypothesis_id="h1", stance="supports"),)

        @property
        def quoted_text(self):
            raise AssertionError("the projection read the quote")

    cited = missed_mod.cited_claim(_Fact())
    assert cited == missed_mod.CitedClaim("f1", "S1", "claim", (("h1", "supports"),), (2, 3))


# --- loading from disk, and the command ---------------------------------------------------


def _write_session(root, name, turns, **meta):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "session.json").write_text(json.dumps({"started_at": "2026-09-01T10:00:00", **meta}),
                                            encoding="utf-8")
    (directory / "transcript.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in _records(turns)), encoding="utf-8")


def _write_facts(context, claims):
    context.mkdir(parents=True, exist_ok=True)
    (context / "hypotheses.json").write_text(json.dumps([{"id": "h1", "statement": "x", "falsifier": "y"}]),
                                             encoding="utf-8")
    (context / "facts.json").write_text(json.dumps([
        {"id": c.fact_id, "session_id": c.session_id, "seqs": list(c.seqs), "claim": c.claim,
         "provenance": "evidence", "quoted_text": "verbatimsentinelqq",
         "bearings": [{"hypothesis_id": h, "stance": s} for h, s in c.bearings]}
        for c in claims]), encoding="utf-8")


@pytest.fixture
def node(tmp_path, monkeypatch):
    sessions, context = tmp_path / "sessions", tmp_path / "context"
    for sid, turns in TRANSCRIPTS.items():
        _write_session(sessions, sid, turns)
    _write_facts(context, _claims())
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(sessions))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(context))
    return SimpleNamespace(sessions=sessions, context=context)


def test_the_loader_reads_facts_and_transcripts(node):
    report = missed_load.load(node.context, node.sessions)
    assert [t.tally.missed_interviews for t in report.topics] == [4, 1]


def test_the_loader_trusts_no_unconfirmed_roles(node):
    meta = node.sessions / "S4" / "session.json"
    meta.write_text(json.dumps({"capture": "in-person", "evidence": "pending"}), encoding="utf-8")
    topic = _topic(missed_load.load(node.context, node.sessions), "a1")
    assert topic.tally.judged_interviews == 3


def test_the_command_prints_the_climax_and_no_words(node, capsys, monkeypatch):
    def _no_client():
        raise AssertionError("missed built a model client")

    monkeypatch.setattr(main_mod.reasoning_client, "build_client", _no_client)
    assert main_mod.main(["missed"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith("In 4 of 4"))
    assert "interviewees raised" in lines[first] and "break" in lines[first]
    assert lines[first].endswith("You followed up in 0.")
    assert "  S1 seq 1: walked past" in out
    assert "In 3 of 4 interviews" in out and "You followed up in 2." in out
    assert "  S2 seq 5: followed up" in out
    assert out.index("In 4 of 4") < out.index("In 3 of 4")
    for words in ("verbatimsentinelqq", SPOKEN_SENTINEL, "reviews her last fight", OFFER_A[:20], MOVE_1[:20]):
        assert words not in out


def test_the_command_names_each_empty_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(tmp_path / "context"))
    assert main_mod.main(["missed"]) == 0
    assert "No extracted interviews" in capsys.readouterr().out

    _write_facts(tmp_path / "context", _claims(TOPIC_C + NOISE))
    assert main_mod.main(["missed"]) == 0
    assert "No topic comes up in 3 or more" in capsys.readouterr().out

    _write_facts(tmp_path / "context", _claims(TOPIC_A))
    assert main_mod.main(["missed"]) == 0
    assert "no interviewer turn" in capsys.readouterr().out.lower()


def test_a_corpus_that_fails_validation_is_an_error(tmp_path, monkeypatch, capsys):
    context = tmp_path / "context"
    context.mkdir()
    (context / "facts.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(context))
    assert main_mod.main(["missed"]) == 1
    assert "ERROR" in capsys.readouterr().err


def test_the_mirror_carries_the_climax_as_a_section(node, capsys):
    assert main_mod.main(["mirror"]) == 0
    out = capsys.readouterr().out
    assert "Topics they kept raising" in out
    assert "In 4 of 4 interviews" in out and "You followed up in 0." in out
    assert "verbatimsentinelqq" not in out


def test_the_mirror_without_a_corpus_still_works(tmp_path, monkeypatch, capsys):
    sessions = tmp_path / "sessions"
    _write_session(sessions, "S1", TRANSCRIPTS["S1"])
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(sessions))
    monkeypatch.setenv("APP_CONTEXT_DIR", str(tmp_path / "context"))
    assert main_mod.main(["mirror"]) == 0
    assert "Topics they kept raising" not in capsys.readouterr().out


# --- the seam: a REAL extraction, through the real corpus store, into the loader ---------


def test_a_real_extraction_through_the_corpus_store_reaches_the_loader(tmp_path):
    from app.coach import corpus_store
    from app.coach.extract import EXTRACT_TOOL_NAME, extract_facts
    from app.coach.stub import StubAnthropicClient, tool_use_response
    from app.session.reader import read_session
    from app.session.store import SessionStore

    sessions, context = tmp_path / "sessions", tmp_path / "context"
    context.mkdir()
    for index, (sid, claim) in enumerate(zip(("S1", "S2", "S3"), [row[2] for row in TOPIC_A])):
        store = SessionStore(sessions / sid)
        store.write_metadata({"started_at": f"2026-09-0{index + 1}T10:00:00"})
        for speaker, text in _transcript(MOVE_3):
            store.append_segment(speaker=speaker, text=text, audio_start_s=0.0, audio_end_s=1.0,
                                 ready_wall_s=1.1, detected_language="en", engine="fake")
        store.close()
        segments = read_session(sessions / sid).records
        offer = next(s for s in segments if s.get("kind") == "segment" and s.get("text", "").startswith("In the break"))
        stub = StubAnthropicClient(responses=[tool_use_response(EXTRACT_TOOL_NAME, {"facts": [{
            "claim": claim, "seqs": [offer["seq"]], "provenance": "evidence",
            "quoted_text": "I usually open my notes", "bearings": []}]})])
        transcript = [s for s in _segment_records(sessions / sid)]
        result = extract_facts(stub, session_id=sid, transcript=transcript, hypotheses=(), model="m",
                               max_tokens=100, timeout_s=1.0)
        assert len(result.accepted) == 1, result.rejections
        corpus_store.replace_session_facts(context, sid, result.accepted)

    report = missed_load.load(context, sessions)
    (topic,) = report.topics
    assert (topic.tally.raised_interviews, topic.tally.followed_interviews) == (3, 0)
    assert all(o.outcome == missed_mod.WALKED_PAST for o in topic.occurrences)


def _segment_records(session_dir):
    """The transcript exactly as `extract`'s own CLI hands it to `extract_facts`."""
    from app.session import evidence as evidence_mod
    from app.session.reader import read_session
    from app.session.store import SegmentRecord

    records = read_session(session_dir).records_of_kind("segment")
    return [SegmentRecord(**record) for record in evidence_mod.segment_fields(records)]


# --- precision: what does NOT count as engaging the offer (2026-11-11) -------------------
#
# Measured on the synthetic project: a scripted guide question, a pitch that
# names the product, and "פעם" ("time") meeting "פעמים" ("times") were all
# scored as follow-ups the interviewer never made.

PRODUCT_OFFER = "Honestly Claudictive is what I open while the lobby fills, a minute of nothing."
PRODUCT_PITCH = "Don't you think Claudictive would be amazing with voice in the middle of a fight?"
SIX = ("S1", "S2", "S3", "S4", "S5", "S6")


def _product_transcripts(reply, sessions=SIX):
    # Every interviewer names the product somewhere, as a real guide does.
    return {sid: [("interviewer", "How did you first hear about Claudictive?"), ("interviewee", PRODUCT_OFFER),
                  ("interviewer", reply), ("interviewee", ANSWER), ("interviewer", MOVE_3)] for sid in sessions}


def _lobby_claims(sessions=SIX):
    return [_claim(f"l{i}", sid, "Waiting for the lobby is when she opens it.", seqs=(1,))
            for i, sid in enumerate(sessions)]


def test_the_projects_own_vocabulary_is_what_most_interviewers_say():
    vocabulary = missed_mod.project_vocabulary(_turns(_product_transcripts(MOVE_1)))
    assert "claudictive" in vocabulary
    assert "lobby" not in vocabulary  # only interviewees said it


def test_vocabulary_needs_enough_interviews_to_mean_anything():
    assert missed_mod.MIN_INTERVIEWS_FOR_VOCABULARY == 6
    assert missed_mod.project_vocabulary(_turns(_product_transcripts(MOVE_1, sessions=SIX[:5]))) == frozenset()


def test_naming_the_product_is_not_engaging_the_offer():
    groups = (SimpleNamespace(label="lobby", fact_ids=tuple(f"l{i}" for i in range(6))),)
    turns = _turns(_product_transcripts(PRODUCT_PITCH))
    report = missed_mod.find(_lobby_claims(), turns, groups=groups,
                             vocabulary=missed_mod.project_vocabulary(turns))
    assert report.topics[0].tally.followed_interviews == 0


def test_a_real_echo_still_counts_beside_the_vocabulary():
    groups = (SimpleNamespace(label="lobby", fact_ids=tuple(f"l{i}" for i in range(6))),)
    # Asked in two interviews of six: a follow-up, not the project's vocabulary.
    transcripts = {**_product_transcripts(PRODUCT_PITCH),
                   **_product_transcripts("How long does the lobby usually take to fill?", sessions=SIX[:2])}
    turns = _turns(transcripts)
    assert "lobby" not in missed_mod.project_vocabulary(turns)
    report = missed_mod.find(_lobby_claims(), turns, groups=groups,
                             vocabulary=missed_mod.project_vocabulary(turns))
    assert report.topics[0].tally.followed_interviews == 2


SCRIPTED = "How many times a week do you open your notes?"


def test_a_scripted_guide_question_is_never_a_follow_up():
    # It reuses "notes", the offer's own word -- and is still the next question on the guide.
    transcripts = {sid: [("interviewer", OPENER), ("interviewee", OFFER_A), ("interviewer", SCRIPTED)]
                   for sid in ("S1", "S2", "S3", "S4")}
    claims, turns = _claims(TOPIC_A), _turns(transcripts)
    assert _topic(missed_mod.find(claims, turns), "a1").tally.followed_interviews == 4
    scripts = {sid: ("How many times per week do you open your notes app?",) for sid in transcripts}
    topic = _topic(missed_mod.find(claims, turns, scripts=scripts), "a1")
    assert (topic.tally.judged_interviews, topic.tally.followed_interviews) == (4, 0)


def test_a_question_only_loosely_like_a_guide_item_is_not_scripted():
    assert not missed_mod.is_scripted("Which notes do you open first?",
                                      missed_mod.script_keys(["How many times per week do you open your notes app?"]))
    assert missed_mod.is_scripted("כמה פעמים בשבוע אתה משתמש בזה?",
                                  missed_mod.script_keys(["כמה פעמים בשבוע את/ה משתמש/ת בClaudictive?"]))


def test_a_point_back_marker_right_after_the_offer_still_counts_with_a_survey():
    transcripts = {sid: [("interviewer", OPENER), ("interviewee", OFFER_A), ("interviewer", "Wait, what do you mean?")]
                   for sid in ("S1", "S2", "S3", "S4")}
    scripts = {sid: (SCRIPTED,) for sid in transcripts}
    topic = _topic(missed_mod.find(_claims(TOPIC_A), _turns(transcripts), scripts=scripts), "a1")
    assert topic.tally.followed_interviews == 4


def test_the_loader_reads_the_session_snapshot_else_the_project_survey(node):
    (node.context / "survey.json").write_text(json.dumps([{"id": "s1", "order": 0, "text": MOVE_2}]),
                                              encoding="utf-8")
    meta = node.sessions / "S3" / "session.json"
    meta.write_text(json.dumps({"started_at": "2026-09-01T10:00:00",
                                "context_survey": [{"id": "x", "order": 0, "text": MOVE_1}]}), encoding="utf-8")
    scripts = missed_load.session_scripts(node.context, node.sessions, ["S1", "S3"])
    assert scripts == {"S1": (MOVE_2,), "S3": (MOVE_1,)}


def test_an_unreadable_project_survey_means_no_scripts_not_a_crash(node):
    (node.context / "survey.json").write_text("{not json", encoding="utf-8")
    assert missed_load.session_scripts(node.context, node.sessions, ["S1"]) == {"S1": ()}


def test_a_topic_term_that_is_project_vocabulary_is_not_engagement():
    # The claims themselves name the product, so it is one of the topic's terms.
    claims = [_claim(f"l{i}", sid, "Waiting for the lobby is when she opens Claudictive.", seqs=(1,))
              for i, sid in enumerate(SIX)]
    groups = (SimpleNamespace(label="lobby", fact_ids=tuple(f"l{i}" for i in range(6))),)
    turns = _turns(_product_transcripts(PRODUCT_PITCH))
    vocabulary = missed_mod.project_vocabulary(turns)
    (theme,) = missed_mod.themes.from_groups(claims, groups, min_interviews=3)
    assert "claudictive" in theme.terms & vocabulary
    report = missed_mod.find(claims, turns, groups=groups, vocabulary=vocabulary)
    assert report.topics[0].tally.followed_interviews == 0


# --- a question the critic flagged as a pitch or leading is never a follow-up ------------

PITCH_ON_TOPIC = "Wouldn't a timer for the break between rounds be amazing?"


def test_a_flagged_pitch_that_echoes_the_topic_is_walked_past():
    transcripts = {sid: [("interviewer", OPENER), ("interviewee", OFFER_A), ("interviewer", PITCH_ON_TOPIC)]
                   for sid in ("S1", "S2", "S3", "S4")}
    claims, turns = _claims(TOPIC_A), _turns(transcripts)
    assert _topic(missed_mod.find(claims, turns), "a1").tally.followed_interviews == 4
    flagged = {"S1": frozenset({2}), "S2": frozenset({2})}
    topic = _topic(missed_mod.find(claims, turns, flagged=flagged), "a1")
    assert (topic.tally.judged_interviews, topic.tally.followed_interviews) == (4, 2)
    assert {o.session_id: o.outcome for o in topic.occurrences}["S1"] == missed_mod.WALKED_PAST


def _write_critique(session_dir, turns):
    (session_dir / "questions_critique.json").write_text(json.dumps({"session_id": session_dir.name, "turns": turns}),
                                                         encoding="utf-8")


def _critique_turn(seq, **flags):
    judgment = {"band": "clear_violation", "is_leading": False, "is_pitch": False, **flags}
    return {"index": 0, "seqs": [seq], "text": "not read", "judgment": judgment}


def test_the_loader_reads_pitch_and_leading_flags_by_seq(node):
    # Topic B was followed up in S1 and S2, both at seq 6.
    _write_critique(node.sessions / "S1", [_critique_turn(6, is_pitch=True)])
    _write_critique(node.sessions / "S2", [_critique_turn(6, is_leading=True)])
    assert _topic(missed_load.load(node.context, node.sessions), "b1").tally.followed_interviews == 0


@pytest.mark.parametrize("payload", [
    [_critique_turn(6)],                                   # judged, but clean
    [_critique_turn(4, is_pitch=True)],                    # a different turn
    [{"seqs": [6], "judgment": None}],                     # the critic was not reached
    [{"seqs": "6", "judgment": {"is_pitch": True}}],       # malformed row
    [{"seqs": [6, "7"], "judgment": {"is_pitch": True}}],  # a bad seq: the row is skipped whole
    [{"seqs": [True], "judgment": {"is_pitch": True}}],    # a bool is not a seq
    "not a list",
])
def test_an_unflagged_unrelated_or_malformed_critique_changes_nothing(node, payload):
    _write_critique(node.sessions / "S1", payload)
    assert _topic(missed_load.load(node.context, node.sessions), "b1").tally.followed_interviews == 2


def test_an_unreadable_critique_file_changes_nothing(node):
    (node.sessions / "S1" / "questions_critique.json").write_text("{not json", encoding="utf-8")
    assert _topic(missed_load.load(node.context, node.sessions), "b1").tally.followed_interviews == 2


# --- unprompted: what interviewees raised WITHOUT being asked (2026-11-11) ---------------
#
# "You never followed up" means nothing about an answer to "what do you think
# of voice input?". The headline counts the interviews where the topic came
# up unprompted; the rest is listed, counted, under "Raised when you asked".

ASKED_ABOUT = "What do you do in the break between rounds?"


def _asked_transcript(question, offer=OFFER_A, reply=MOVE_1):
    return [("interviewer", question), ("interviewee", offer), ("interviewer", reply),
            ("interviewee", ASIDE), ("interviewer", MOVE_2)]


def test_an_offer_answering_a_question_on_the_topic_is_prompted():
    transcripts = {"S1": _asked_transcript(ASKED_ABOUT), **{s: _asked_transcript(OPENER) for s in ("S2", "S3", "S4")}}
    topic = _topic(missed_mod.find(_claims(TOPIC_A), _turns(transcripts)), "a1")
    assert {o.session_id: o.prompted for o in topic.occurrences} == {"S1": True, "S2": False, "S3": False, "S4": False}
    assert (topic.tally.raised_interviews, topic.raised_interviews, topic.asked_only_interviews) == (3, 4, 1)


def test_a_backchannel_and_the_interviewees_own_turns_do_not_hide_the_question():
    transcripts = {sid: [("interviewer", ASKED_ABOUT), ("interviewee", ASIDE), ("interviewer", "Mm, okay."),
                         ("interviewee", OFFER_A), ("interviewer", MOVE_1)] for sid in ("S1", "S2", "S3", "S4")}
    claims = [_claim(*row, seqs=(3,)) for row in TOPIC_A]
    report = missed_mod.find(claims, _turns(transcripts))
    assert report.topics == ()
    (asked,) = report.asked_topics
    assert (asked.raised_interviews, asked.asked_only_interviews, asked.tally.raised_interviews) == (4, 4, 0)
    assert report.state == missed_mod.STATE_ONLY_ASKED


def test_the_floor_counts_unprompted_interviews():
    # Raised in four, unprompted in two: below the floor, listed as asked.
    transcripts = {**{s: _asked_transcript(ASKED_ABOUT) for s in ("S1", "S2")},
                   **{s: _asked_transcript(OPENER) for s in ("S3", "S4")}}
    report = missed_mod.find(_claims(TOPIC_A), _turns(transcripts))
    assert not any("a1" in t.fact_ids for t in report.topics)
    (asked,) = [t for t in report.asked_topics if "a1" in t.fact_ids]
    assert (asked.raised_interviews, asked.tally.raised_interviews) == (4, 2)


def test_follow_ups_are_counted_over_the_unprompted_occurrences_only():
    # S1 was asked about it AND followed it up: that is not a follow-up of an aside.
    transcripts = {"S1": _asked_transcript(ASKED_ABOUT, reply="Why then, of all moments?"),
                   **{s: _asked_transcript(OPENER) for s in ("S2", "S3", "S4")}}
    topic = _topic(missed_mod.find(_claims(TOPIC_A), _turns(transcripts)), "a1")
    assert (topic.tally.raised_interviews, topic.tally.followed_interviews) == (3, 0)


GUIDE = ("What do you think of the break timer in Claudictive?", "Would you pay for Claudictive?",
         "Would you recommend Claudictive to a friend?")


def test_a_guide_question_prompts_its_own_subject():
    transcripts = {"S1": _asked_transcript(GUIDE[0], offer="It would let me rest my wrists properly."),
                   **{s: _asked_transcript(OPENER) for s in ("S2", "S3", "S4")}}
    claims = [_claim("a1", "S1", "During the break between rounds she rests her wrists.")] + _claims(TOPIC_A[1:])
    scripts = {sid: GUIDE for sid in transcripts}
    topic = _topic(missed_mod.find(claims, _turns(transcripts), scripts=scripts), "a1")
    assert {o.session_id: o.prompted for o in topic.occurrences}["S1"] is True


def test_a_guide_question_does_not_prompt_through_the_word_every_guide_question_shares():
    # "Claudictive" is in all three guide questions: it is the product, not the subject.
    offer = "Honestly I open Claudictive in the break between rounds."
    transcripts = {sid: _asked_transcript(GUIDE[1], offer=offer) for sid in ("S1", "S2", "S3", "S4")}
    claims = [_claim(f, s, c + " Claudictive.") for f, s, c, _ in TOPIC_A]
    scripts = {sid: GUIDE for sid in transcripts}
    topic = _topic(missed_mod.find(claims, _turns(transcripts), scripts=scripts), "a1")
    assert not any(o.prompted for o in topic.occurrences)


def test_the_guide_subject_is_the_words_no_other_question_uses():
    items = missed_mod.script_keys(GUIDE)
    subjects = missed_mod.script_subjects(items)
    assert "timer" in subjects[0] and "claudictive" not in subjects[0]
    assert "pay" in subjects[1] and "recommend" in subjects[2]


def test_the_split_is_counted_per_interview_in_interview_summary():
    split = summary_mod.split_by_prompt([("S1", False, True), ("S1", True, False), ("S2", None, False),
                                         ("S3", False, True), ("S3", False, True)])
    assert (split.raised_interviews, split.asked_only_interviews) == (3, 1)
    assert (split.unprompted.raised_interviews, split.unprompted.judged_interviews,
            split.unprompted.followed_interviews) == (2, 1, 1)


def test_the_command_headlines_unprompted_and_lists_the_asked(node, capsys):
    # S1 and S2 now answer a question about the break: topic A is unprompted in S3 and S4 only.
    for sid in ("S1", "S2"):
        _write_session_turns(node.sessions / sid, _asked_transcript(ASKED_ABOUT) + TRANSCRIPTS[sid][5:])
    assert main_mod.main(["missed"]) == 0
    out = capsys.readouterr().out
    assert "In 3 of 4 interviews, interviewees raised" in out and "without being asked. You followed up in 2." in out
    tail = out[out.index("Raised when you asked"):]
    assert "in 4 interviews, unprompted in 2" in tail and "break" in tail


def _write_session_turns(directory, turns):
    (directory / "transcript.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in _records(turns)), encoding="utf-8")


def test_a_word_the_guide_keeps_asking_about_still_prompts_but_the_product_name_does_not():
    # "voice": asked in four of six interviews -- vocabulary to the judge, a subject to the prompt.
    # "Claudictive": in all six -- the product, which prompts nothing.
    sessions = {sid: [("interviewer", "How did you first hear about Claudictive?"),
                      ("interviewee", "From a friend at work, a while ago."),
                      ("interviewer", "And what about voice, would that change things for Claudictive?" if i < 4
                       else "Which headset brand do you prefer for evening sessions?"),
                      ("interviewee", "Voice would be great for Claudictive during the lobby."),
                      ("interviewer", MOVE_3)] for i, sid in enumerate(SIX)}
    claims = [_claim(f"v{i}", sid, "Voice input would help him in the lobby.", seqs=(3,)) for i, sid in enumerate(SIX)]
    groups = (SimpleNamespace(label="voice", fact_ids=tuple(f"v{i}" for i in range(6))),)
    turns = _turns(sessions)
    vocabulary = missed_mod.project_vocabulary(turns)
    assert {"voice", "claudictive"} <= vocabulary
    assert missed_mod.project_vocabulary(turns, share=missed_mod.PROMPT_VOCABULARY_SHARE) >= {"claudictive"}
    assert "voice" not in missed_mod.project_vocabulary(turns, share=missed_mod.PROMPT_VOCABULARY_SHARE)
    report = missed_mod.find(claims, turns, groups=groups, vocabulary=vocabulary)
    (topic,) = report.asked_topics or report.topics
    assert {o.session_id: o.prompted for o in topic.occurrences} == {sid: i < 4 for i, sid in enumerate(SIX)}


def test_an_answer_echoing_the_guide_questions_phrasing_is_not_prompted():
    # "What do you mostly do with it?" -- the reply says "mostly" back, and is about the break.
    guide = ("What do you mostly do with Claudictive?", "Would you pay for Claudictive?")
    assert "mostly" in missed_mod.script_subjects(missed_mod.script_keys(guide))[0]
    offer = "Mostly, honestly, in the break between rounds I open it and review the last fight."
    transcripts = {sid: _asked_transcript(guide[0], offer=offer) for sid in ("S1", "S2", "S3", "S4")}
    scripts = {sid: guide for sid in transcripts}
    topic = _topic(missed_mod.find(_claims(TOPIC_A), _turns(transcripts), scripts=scripts), "a1")
    assert not any(o.prompted for o in topic.occurrences)


def test_a_claim_citing_interviewer_speech_is_never_prompted():
    transcripts = {sid: [("interviewer", ASKED_ABOUT), ("interviewee", ASIDE),
                         ("interviewer", "Do the breaks between rounds feel long to you?"), ("interviewee", ANSWER)]
                   for sid in ("S1", "S2", "S3", "S4")}
    claims = [_claim(*row, seqs=(2,)) for row in TOPIC_A]
    report = missed_mod.find(claims, _turns(transcripts))
    (topic,) = report.topics
    assert {o.outcome for o in topic.occurrences} == {missed_mod.NOT_INTERVIEWEE}
    assert not any(o.prompted for o in topic.occurrences)


def test_a_follow_up_on_a_prompted_mention_still_counts_for_that_interview():
    # The overlay control: the first mention answers "what bothers you?"
    # (prompted) and is followed up; it comes back unasked at "anything
    # else?" and is walked past. The interviewer did not walk past the topic.
    split = summary_mod.split_by_prompt([
        ("S1", True, True), ("S1", False, False),
        ("S2", False, False),
        ("S3", True, True),
    ])
    assert split.raised_interviews == 3 and split.asked_only_interviews == 1
    assert split.unprompted.raised_interviews == 2
    assert split.unprompted.followed_interviews == 1
