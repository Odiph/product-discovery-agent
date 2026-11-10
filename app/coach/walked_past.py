"""Moments the interviewer walked past: the interviewee offered something
worth following, and the next question went somewhere else.

The mirror's promise -- "every gap it caught was a gap I walked
past" -- is a claim about the INTERVIEWER, and this is its offline detector.
No model call: a moment is detected from the transcript's own words, so it is
free to run over every interview a project has.

**What counts as an offer.** An interviewee turn long enough to carry
something (`MIN_OFFER_WORDS`) that holds a concrete signal: a specific past
occasion, a workaround, a cost in time or money, or a stated pain. Those are
exactly what the Mom Test says to dig into; a long turn of opinion with none
of them is not counted.

**What counts as walking past.** The interviewer's next substantive turn
shares no content word with the offer and carries no follow-up marker ("why",
"you said", "tell me more"). Short turns are never counted: "And then?" and
"Which two?" are the best follow-ups an interviewer has, and a two-word
backchannel is not a change of subject. When that next turn opens with an
acknowledgement ("Love it.", "Great."), the moment is marked
`acknowledged` -- the "Love it. Question seven." shape, praised and dropped.

**A detector, not a judge.** It bounds from above, like `uptake.py`: a flagged
moment is worth the operator's look, and some will be fine (the interviewee
had finished; the guide had a hard stop). Unflagged is not proof of a
follow-up. Pure: no I/O, and it returns sequence numbers and signal names,
never text -- a reporting layer that wants the words reads them itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from app.kb import terms

INTERVIEWER = "interviewer"
INTERVIEWEE = "interviewee"
MIN_OFFER_WORDS = 20
# Hebrew says the same in fewer words (particles attach to the word); on the
# one real Hebrew interview the median interviewee turn was five words.
HEBREW_MIN_OFFER_WORDS = 14
MIN_MOVE_WORDS = 4

# Hebrew words are matched WHOLE, allowing up to two attached particles in
# front (`והמחיר`, `בגיליון`): a bare alternation matches inside other words
# (`חבל`, "a pity", inside `חבלן`). Inflections are listed, not guessed.
_HEBREW_PARTICLES = "[והבלכמש]{0,2}"


def _family(english: str, hebrew: "tuple[str, ...]") -> "re.Pattern":
    return re.compile(
        rf"\b(?:{english})\b|(?<!\w){_HEBREW_PARTICLES}(?:{'|'.join(hebrew)})(?!\w)",
        re.IGNORECASE,
    )


# Each signal is a named family, so a report can say WHY a turn was an offer.
_SIGNALS: "dict[str, re.Pattern]" = {
    "past-occasion": _family(
        r"last (?:time|week|month|year|night|friday|monday|tuesday|wednesday|thursday|saturday|sunday)"
        r"|yesterday|this morning|the other day|every (?:time|day|week|morning|night)|each time",
        ("פעם האחרונה", "פעם אחרונה", "אתמול", "שלשום", "בוקר", "כל פעם", "כל יום", "כל שבוע",
         "כל חודש", "שבוע שעבר", "חודש שעבר", "לפני שבוע", "לפני חודש", "לפני כמה", "לפני יומיים",
         "אותו יום", "אותה פעם", "פעם אחת"),
    ),
    "workaround": _family(
        r"by hand|manually|workaround|spreadsheets?|excel|copy[- ]paste|i (?:had|have) to|we (?:had|have) to"
        r"|i (?:built|wrote|made) (?:a|my own)|we (?:built|wrote|made) (?:a|our own)",
        ("ידני", "ידנית", "ידנית", "בידיים", "אקסל", "גיליון", "גליון", "טבלה", "טבלאות", "וואטסאפ",
         "הייתי צריך", "הייתי צריכה", "היינו צריכים", "אני צריך", "אני צריכה", "אנחנו צריכים",
         "נאלצתי", "נאלצנו", "בניתי לעצמי", "עקיפה", "מתקשר", "מתקשרת", "מתקשרים", "מחפש", "מחפשת",
         "מחפשים", "בודק", "בודקת", "בודקים", "משווה", "משווים", "רושם", "רושמת", "רושמים"),
    ),
    "cost": _family(
        r"\d+\s*(?:hours?|minutes?|days?|weeks?|dollars?|bucks|shekels?)|hours|half an hour"
        r"|an hour|paid|pay for|costs?|expensive|\$\s?\d+",
        ("שעות", "דקות", "שקלים", 'ש"ח', "שילמתי", "שילמנו", "משלם", "משלמת", "משלמים", "מחיר",
         "מחירים", "כסף", "תקציב", "אחוז", "אחוזים", "הנחה", "הנחות"),
    ),
    "pain": _family(
        r"annoy\w*|frustrat\w*|hate|painful|pain|stuck|wast\w*|nightmare|drives me|worst|struggl\w*",
        ("מעצבן", "מעצבנת", "מתסכל", "מתסכלת", "שונא", "שונאת", "תקוע", "תקועה", "מבזבז", "מבזבזים",
         "סיוט", "הכי גרוע", "כאב ראש", "בעיה", "בעיות", "בעייתי", "קשה", "מסובך", "מסובכת",
         "לוקח זמן", "לא עובד", "נמאס", "מבאס", "חבל", "טעות", "טעויות", "פספס", "פספסתי", "פספסנו"),
    ),
}
# `₪` is not a word character, so it stands outside the whole-word rule.
_SHEKEL = re.compile("₪")

_FOLLOW_UP = _family(
    r"why|how come|tell me more|say more|what happened|what do you mean|you said|you mentioned"
    r"|go back|back to|walk me through (?:that|it)|what was that like|for example|an example|which one",
    ("למה", "איך זה", "תספר", "תספרי", "ספר לי", "ספרי לי", "תרחיב", "תרחיבי", "מה קרה",
     "מה זאת אומרת", "אמרת", "הזכרת", "הזכרת", "למשל", "דוגמה", "דוגמא", "נחזור"),
)
# A reply that points BACK is a follow-up whatever its words: "What do you do
# during it?", "What would have made that better?", "When you say slow, you
# mean the export?". Looked for near the start, where a back-reference opens a
# question; deep in a long new question "that" is usually just grammar.
# Not "then" or "there": "Okay, then let us move to billing" points nowhere.
_BACK_REFERENCE = _family(
    r"it|that|this|those|these|them|when you say|you say|so you|so your|so it|so that",
    ("את זה", "אותו", "אותה", "אותם", "כשאתה אומר", "כשאת אומרת", "זאת אומרת"),
)
BACK_REFERENCE_WORDS = 10
# "Sounds like the evenings are sacred." -- a reflection, the interviewer
# handing the offer back to check it. Not a bare "So": "So, what is your
# pricing model?" is a new subject with a connective in front.
_REFLECTION = re.compile(
    r"^\W*(?:\w+\W+){0,2}?(?:sounds like|it sounds|meaning|in other words|כלומר|נשמע ש)", re.IGNORECASE
)
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "twenty": "20", "thirty": "30",
    "אחד": "1", "שתיים": "2", "שניים": "2", "שלוש": "3", "ארבע": "4", "חמש": "5", "עשר": "10",
}
_HEBREW = re.compile("[א-ת]")
_ACKNOWLEDGEMENT = re.compile(
    r"^\W*(ok(ay)?|great|cool|nice|perfect|awesome|love it|got it|amazing|right|sure|interesting|thanks"
    r"|אוקיי|אוקי|מעולה|יופי|סבבה|מגניב|אחלה|נהדר|מעניין|תודה)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Turn:
    speaker: str
    seqs: "tuple[int, ...]"
    text: str
    end_s: Optional[float]


@dataclass(frozen=True)
class Moment:
    offer_seqs: "tuple[int, ...]"
    next_seqs: "tuple[int, ...]"
    at_s: Optional[float]
    """When the offer ENDED (`audio_end_s`; the start is fabricated)."""
    signals: "tuple[str, ...]"
    acknowledged: bool


def turns(records: "Iterable[Mapping[str, Any]]") -> "list[Turn]":
    """Segments merged into turns, in `seq` order (file order is not speech
    order: the two sides finalise on separate threads)."""
    # Only well-formed segments: an int `seq` (sorted against each other) and
    # string `text`. A stray record from a crashed write is skipped, not fatal.
    segments = sorted(
        (r for r in records if isinstance(r, Mapping) and r.get("kind") == "segment"
         and isinstance(r.get("seq"), int) and not isinstance(r.get("seq"), bool)
         and r.get("speaker") in (INTERVIEWER, INTERVIEWEE)
         and isinstance(r.get("text"), str) and r["text"].strip()),
        key=lambda r: r["seq"],
    )
    merged: "list[Turn]" = []
    for segment in segments:
        text = segment["text"].strip()
        if merged and merged[-1].speaker == segment["speaker"]:
            last = merged[-1]
            end_s = _seconds(segment.get("audio_end_s"), last.end_s)
            merged[-1] = Turn(last.speaker, last.seqs + (segment["seq"],), f"{last.text} {text}", end_s)
        else:
            merged.append(Turn(segment["speaker"], (segment["seq"],), text, _seconds(segment.get("audio_end_s"), None)))
    return merged


def _seconds(value, fallback: Optional[float]) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return fallback


def offer_signals(text: str) -> "tuple[str, ...]":
    words = text.split()
    hebrew = sum(1 for word in words if _HEBREW.search(word)) * 2 > len(words)
    if len(words) < (HEBREW_MIN_OFFER_WORDS if hebrew else MIN_OFFER_WORDS):
        return ()
    found = [name for name, pattern in _SIGNALS.items() if pattern.search(text)]
    if "cost" not in found and _SHEKEL.search(text):
        found.insert(2 if len(found) >= 2 else len(found), "cost")
    return tuple(name for name in _SIGNALS if name in found)


def detect(records: "Iterable[Mapping[str, Any]]") -> "list[Moment]":
    sequence = turns(records)
    moments: "list[Moment]" = []
    for position, offer in enumerate(sequence):
        if offer.speaker != INTERVIEWEE:
            continue
        signals = offer_signals(offer.text)
        if not signals:
            continue
        reply = _next_substantive_question(sequence, position)
        if reply is None or _follows_up(offer.text, reply.text):
            continue
        moments.append(Moment(
            offer_seqs=offer.seqs,
            next_seqs=reply.seqs,
            at_s=offer.end_s,
            signals=signals,
            acknowledged=bool(_ACKNOWLEDGEMENT.match(reply.text)),
        ))
    return moments


def _next_substantive_question(sequence: "list[Turn]", position: int) -> Optional[Turn]:
    """The interviewer's next turn, unless it is a short probe or a
    backchannel -- in which case the interviewer did NOT move on, and the
    interviewee's continuation is a new offer judged on its own."""
    following = sequence[position + 1] if position + 1 < len(sequence) else None
    if following is None or following.speaker != INTERVIEWER:
        return None
    if len(following.text.split()) < MIN_MOVE_WORDS:
        return None
    return following


def _follows_up(offer: str, reply: str) -> bool:
    if _FOLLOW_UP.search(reply) or _REFLECTION.match(reply):
        return True
    # Past the acknowledgement first: the "it" in "Love it." points at nothing
    # the interviewee said, and the "Love it. Question seven." shape is the
    # one this detector exists for.
    rest = reply[_ACKNOWLEDGEMENT.match(reply).end():] if _ACKNOWLEDGEMENT.match(reply) else reply
    opening = " ".join(rest.split()[:BACK_REFERENCE_WORDS])
    if _BACK_REFERENCE.search(opening):
        return True
    return bool(_content_forms(offer) & _content_forms(reply))


def _content_forms(text: str) -> "set[str]":
    """Content words in every form, plus numbers (so "Three in one evening"
    echoes "about 3 of them"), with -ing/-ed folded ("seen it" / "seeing it"
    is still the same subject)."""
    found: "set[str]" = set()
    for word in terms.words(text):
        if word.isdigit():
            found.add(word)
        elif word in _NUMBER_WORDS:
            found.add(_NUMBER_WORDS[word])
        elif terms.is_topic_word(word):
            found.update(terms.forms(word))
            for suffix in ("ing", "ed"):
                if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                    found.add(word[: -len(suffix)])
    return found
