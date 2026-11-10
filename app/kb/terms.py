"""Tokenising for retrieval and topics, Hebrew-safe.

Hebrew attaches prepositions and conjunctions to the word (`וכשהלקוח` is "and
when the customer"), writes five letters differently at the end of a word, and
pluralises with a suffix. A plain word match therefore misses most of a Hebrew
corpus. Each token is indexed under its surface form plus the forms with one
or two leading particles and a plural suffix removed; a query matches when any
of its forms does, and scores by its best form only, so the extra forms widen
recall without counting a word twice.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterator

_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
_HEBREW_MARKS = re.compile(r"[֑-ׇ]")
_HEBREW_LETTER = re.compile(r"[א-ת]")
_FINAL_LETTERS = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})
_HEBREW_PREFIXES = frozenset("ובהלמשכ")
# Compared AFTER final letters are normalised, so the masculine plural is `ימ`.
_HEBREW_PLURALS = ("ימ", "ות")
# `וכשה` ("and when the") is four particles; each stripped form is ADDED,
# never substituted, so an over-strip costs a little precision, not a miss.
MAX_HEBREW_PARTICLES = 4
MIN_HEBREW_STEM = 3

_STOPWORD_TEXT = """
a about above after again against all also am an and any are aren't as at be because been before being
below between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down
during each few for from further get got had hadn't has hasn't have haven't having he he'd he'll he's her
here here's hers herself him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its
itself just let's like me more most mustn't my myself no nor not now of off on once only or other ought
our ours ourselves out over own really same shan't she she'd she'll she's should shouldn't so some such
than that that's the their theirs them themselves then there there's these they they'd they'll they're
they've this those through to too under until up us very was wasn't we we'd we'll we're we've were
weren't what what's when when's where where's which while who who's whom why why's will with won't would
wouldn't yeah yes you you'd you'll you're you've your yours yourself yourselves okay ok um uh oh
thing things know think mean kind sort lot going gonna want actually maybe probably right well
hmm mhm huh said say says saying one two three whether real never always every much many something
someone anything everything nothing stuff guess sure pretty quite bit little even still back
time times day way first next last else tell told see saw look looked use used start started come came
make made take took give gave put get gets getting go goes went doing done ask asked talk talking
את של על עם זה זאת זו הוא היא הם הן אני אתה את אנחנו אתם לא כן גם רק אבל או אם כי מה מי איך למה
כמו יש אין היה היתה היו להיות עוד כבר כל אז פה שם הזה הזאת האלה אלה אותו אותה אותם שלי שלך שלו
שלה שלנו להם לו לה לי לך אצל בין אחרי לפני כדי מאוד ממש סתם בעצם נגיד כאילו טוב אוקיי יאללה
פשוט כאן יכול יכולה כזה כזאת כאלה בסדר אולי נכון עכשיו הכול הכל דבר משהו מישהו צריך רוצה אומר
אמר אמרתי חושב חושבת יודע יודעת תמיד אפילו איזה איזו ככה הרבה קצת יותר פחות באמת בדיוק שוב אחד
אחת שני שתי עושה לעשות היום אחר אחרת אותי אותך מתי איפה כמה עד רגע בוא בואו תודה אה אמ אהה וואו
הנה שזה שאני שהוא שהיא אותנו לנו בשביל
"""


def normalize(token: str) -> str:
    token = unicodedata.normalize("NFKC", token).lower()
    token = _HEBREW_MARKS.sub("", token).replace("’", "'")
    return token.translate(_FINAL_LETTERS)


# Normalised like every indexed word, or a Hebrew stopword ending in a final
# letter would never match the word it is meant to drop.
STOPWORDS = frozenset(normalize(word) for word in _STOPWORD_TEXT.split())


def words(text: str) -> "list[str]":
    """Surface words in order, normalised but not stemmed."""
    # Niqqud is stripped BEFORE splitting: the marks are not word characters,
    # so `יְצִיאָה` would otherwise split into five fragments.
    text = _HEBREW_MARKS.sub("", text)
    return [w for w in (normalize(m.group(0)) for m in _WORD.finditer(text)) if w]


def forms(word: str) -> "tuple[str, ...]":
    """The forms a normalised word is indexed and queried under."""
    if _HEBREW_LETTER.match(word):
        return _hebrew_forms(word)
    return _english_forms(word)


def index_terms(text: str) -> Iterator[str]:
    for word in words(text):
        yield from forms(word)


def is_topic_word(word: str) -> bool:
    """Checked over every form: `ואז` is "and then", a stopword with a
    particle attached, and must not become a topic."""
    if len(word) < 3 or word.isdigit():
        return False
    candidates = set(forms(word))
    # Down to two letters here, below the indexing floor: `וזה` is `ו` + `זה`.
    if _HEBREW_LETTER.match(word) and word[0] in _HEBREW_PREFIXES:
        candidates.add(word[1:])
        if len(word) > 3 and word[1] in _HEBREW_PREFIXES:
            candidates.add(word[2:])
    return not candidates & STOPWORDS


def _english_forms(word: str) -> "tuple[str, ...]":
    base = word[:-2] if word.endswith("'s") else word
    stem = base
    if len(base) > 4 and base.endswith("ies"):
        stem = base[:-3] + "y"
    elif len(base) > 4 and base.endswith(("ches", "shes", "sses", "xes")):
        stem = base[:-2]
    elif len(base) > 3 and base.endswith("s") and not base.endswith(("ss", "us", "is")):
        stem = base[:-1]
    return (word,) if stem == word else (word, stem)


def _hebrew_forms(word: str) -> "tuple[str, ...]":
    found = [word]
    candidates = [word]
    stripped = word
    for _ in range(MAX_HEBREW_PARTICLES):
        if len(stripped) - 1 >= MIN_HEBREW_STEM and stripped[0] in _HEBREW_PREFIXES:
            stripped = stripped[1:]
            candidates.append(stripped)
        else:
            break
    for candidate in candidates:
        if candidate not in found:
            found.append(candidate)
        if len(candidate) - 2 >= MIN_HEBREW_STEM and candidate.endswith(_HEBREW_PLURALS):
            singular = candidate[:-2]
            # A feminine plural drops a final `ה`: `הזמנות` is `הזמנה`, not `הזמנ`.
            for stem in (singular, singular + "ה") if candidate.endswith("ות") else (singular,):
                if stem not in found:
                    found.append(stem)
    return tuple(found)


_TO_FINAL = {"כ": "ך", "מ": "ם", "נ": "ן", "פ": "ף", "צ": "ץ"}


def display(term: str) -> str:
    """A normalised term as a reader writes it: Hebrew words get their final
    letter back."""
    return " ".join(
        word[:-1] + _TO_FINAL[word[-1]] if len(word) > 1 and word[-1] in _TO_FINAL else word
        for word in term.split(" ")
    )
