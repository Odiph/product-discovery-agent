"""The walked-past detector (app/coach/walked_past.py).

The must-NOT-flag cases are the shapes the first draft got wrong on the demo
interview and the rehearsals (2026-10-21): every one was a real follow-up
that shared no content word with the offer -- it pointed back ("during it"),
reflected ("So you're..."), echoed a number ("Three in one evening"), or
quoted ("when you say slow"). The first draft flagged 8 of 16 offers on an
interview scripted to follow up well; these cases are why it now flags none.
"""

from __future__ import annotations

import pytest

from app.coach import walked_past as wp

OFFER = ("Last Tuesday I had to rebuild the whole export by hand in a spreadsheet, it took me about "
         "three hours and honestly it was the most annoying part of my week")


def _records(*turns):
    records, seq = [], 0
    for speaker, text in turns:
        for piece in text.split(" | "):
            records.append({"kind": "segment", "seq": seq, "speaker": speaker, "text": piece,
                            "audio_end_s": float(seq * 5 + 5)})
            seq += 1
    return records


def _detect(reply, offer=OFFER):
    return wp.detect(_records(("interviewer", "How did last week go?"), ("interviewee", offer),
                              ("interviewer", reply)))


def test_an_offer_followed_by_a_new_subject_is_walked_past():
    moments = _detect("Do you ever use the mobile app on the train?")
    assert len(moments) == 1
    assert set(moments[0].signals) >= {"past-occasion", "workaround", "cost", "pain"}
    assert moments[0].acknowledged is False
    assert moments[0].at_s == 10.0


def test_praise_then_a_new_subject_is_marked_acknowledged():
    (moment,) = _detect("Love it. Question seven, how do you choose a new tool?")
    assert moment.acknowledged is True


@pytest.mark.parametrize("reply", [
    "What do you do during it, while you wait?",               # points back
    "What would have made that better for you?",               # points back
    "Right. So you're protecting your evenings from the work.",  # reflection
    "Sounds like the evenings are sacred for you.",          # reflection with no back-reference
    "Three hours, every single time you do the export?",      # echo, and shared words
    "Hmm, three in one afternoon.",                           # number echo
    "And when you say by hand, do you mean typing it?",       # quoting
    "Why was it the most annoying part?",                     # explicit follow-up
    "Tell me more about the rebuild.",                        # explicit follow-up
    "Which export?",                                          # a short probe is never moving on
    "Mm-hm.",                                                 # a backchannel is never moving on
])
def test_follow_ups_that_share_no_obvious_word_are_not_flagged(reply):
    assert _detect(reply) == []


def test_a_long_opinion_with_no_concrete_signal_is_not_an_offer():
    opinion = ("I think in general tools like this could be quite useful for a lot of people, it "
               "depends on the team and what they are trying to do and how they like to work")
    assert wp.offer_signals(opinion) == ()
    assert _detect("Do you ever use the mobile app on the train?", offer=opinion) == []


def test_a_short_turn_is_not_an_offer_however_concrete():
    assert wp.offer_signals("Last Tuesday, by hand, three hours.") == ()


def test_hebrew_offers_need_fewer_words_and_hebrew_follow_ups_count():
    offer = "בפעם האחרונה הייתי צריך לעשות את כל ההזמנה ידנית בגיליון וזה לקח לי שעות שלמות"
    assert "workaround" in wp.offer_signals(offer)
    assert len(offer.split()) < wp.MIN_OFFER_WORDS
    assert len(_detect("איך אתה בוחר ספק חדש בדרך כלל היום?", offer=offer)) == 1
    assert _detect("למה זה לקח כל כך הרבה זמן לדעתך?", offer=offer) == []


def test_fragments_are_joined_into_turns_in_seq_order_not_file_order():
    records = _records(("interviewee", OFFER.replace(", ", " | ", 2)),
                       ("interviewer", "Do you ever use the mobile app on the train?"))
    records.reverse()
    (moment,) = wp.detect(records)
    assert moment.offer_seqs == (0, 1)


def test_the_moment_carries_sequence_numbers_never_text():
    (moment,) = _detect("Do you ever use the mobile app on the train?")
    assert all(isinstance(value, (tuple, float, bool)) for value in vars(moment).values())


@pytest.mark.parametrize("reply", [
    "So, what is your current pricing model for the enterprise tier?",   # a connective, not a reflection
    "Okay, then let us move to the next section about billing.",          # "then" points nowhere
])
def test_a_new_subject_behind_a_connective_is_still_walked_past(reply):
    assert len(_detect(reply)) == 1


def test_hebrew_signal_words_match_whole_words_only():
    # `חבל` ("a pity") inside `חבלן` ("a saboteur") is not pain.
    assert "pain" not in wp.offer_signals("הוא היה חבלן בצבא " * 4)
    assert "pain" in wp.offer_signals("וזה פשוט חבל על הזמן כל פעם מחדש " * 2)
    assert "cost" in wp.offer_signals("והמחיר היה גבוה מדי בשבילנו " * 3)
    assert "cost" in wp.offer_signals("it was ₪400 and that is a lot for a small team like ours " * 2)


@pytest.mark.parametrize("reply", ["רגע, תסביר לי יותר בבקשה", "תסבירי לי איך זה עובד אצלך"])
def test_asking_to_explain_in_hebrew_is_a_follow_up(reply):
    assert wp.points_back(reply)
    assert _detect(reply) == []


# --- short Hebrew stems (2026-11-11) ---------------------------------------------------


def test_a_short_hebrew_word_does_not_echo_through_a_stripped_form():
    # "פעם" ("once/time") and "פעמים" ("times") met on the stripped `פעמ`:
    # every "how many times a week" question became a follow-up.
    assert not wp.echoes("כל פעם ששמרתי נפתח החלון", "כמה פעמים בשבוע את משתמשת?")


def test_the_same_short_hebrew_word_still_echoes():
    assert wp.echoes("כל פעם ששמרתי נפתח החלון", "רגע, באיזו פעם זה קרה?")


def test_a_long_hebrew_stem_still_meets_its_plural():
    assert wp.echoes("ההזמנה הגיעה מאוחר מדי", "כמה הזמנות כאלה היו?")


def test_echo_ignores_the_words_it_is_told_to():
    assert wp.echoes("Claudictive opens in the lobby", "Is Claudictive fast?")
    assert not wp.echoes("Claudictive opens in the lobby", "Is Claudictive fast?", ignore=frozenset({"claudictive"}))
