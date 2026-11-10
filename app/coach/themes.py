"""Unbound themes: what keeps coming up across interviews that no hypothesis
predicted (backlog B3, offline slice).

The talk's reversal -- the feature marked for cutting was the product -- was
a pattern that fit no hypothesis anyone had written. `standing` can never
show one: it only counts claims against hypotheses. This groups the claims
that bear on NO hypothesis and keeps the groups that recur in two or more
interviews; one interviewee's aside is not a theme.

Deterministic and offline: two claims are linked when they share at least
`MIN_SHARED_TERMS` distinctive content words (a word most claims use, such as
the product's own name, does not count); a theme is one claim and the claims
linked to IT (see `unbound_themes`), labelled by the words its claims share most. It
works on the abstracted `claim` only -- never a quote -- so it reads nothing
gate 20 protects. A model pass can name themes better later; this one can be
checked by hand.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from app.kb import terms

MIN_SHARED_TERMS = 2
MIN_INTERVIEWS = 2
# A term in more than this share of ALL the project's claims (bound or not)
# describes the project -- its own name, its domain -- not a theme.
MAX_TERM_SHARE = 0.5
MIN_CLAIMS_FOR_CEILING = 10
LABEL_TERMS = 3
# A stripped form shorter than this is too likely to be a different word.
MIN_STEM = 4
# Words a claim uses to REPORT speech rather than to say what was said.
_REPORTING = frozenset(terms.normalize(w) for w in """
interviewee interviewer participant person people user users customer customers
said says say saying mentioned mentions described describes describe explained explains noted notes
told reported reports stated states thinks thought feels felt believes believed recalls recalled
directly specifically probably possibly maybe usually often sometimes seems seemed appears
""".split())


@dataclass(frozen=True)
class Theme:
    label: "tuple[str, ...]"
    fact_ids: "tuple[str, ...]"
    sessions: "tuple[str, ...]"
    claims: "tuple[str, ...]"


def unbound_themes(refs: Sequence) -> "tuple[Theme, ...]":
    """`refs`: facts as `interview_summary.FactRef` (claim, session_id,
    bearings). Only those with no bearing are grouped.

    A theme is a CENTRE claim and its direct neighbours, never a chain: with
    connected components, "invoice export" -> "export csv" -> "csv import"
    would drift from invoicing to onboarding inside one theme. Here every
    member shares the threshold with the centre itself. Centres are taken
    most-connected first, ties by position, so the result is deterministic."""
    refs = [ref for ref in refs if isinstance(getattr(ref, "claim", None), str) and ref.claim.strip()]
    unbound = [ref for ref in refs if not ref.bearings]
    if len(unbound) < 2:
        return ()
    frequency: Counter = Counter()
    for ref in refs:
        frequency.update({key for _, keys in _words(ref.claim) for key in keys})
    # Below MIN_CLAIMS_FOR_CEILING no word is "too common": in six claims a
    # real theme IS half the corpus, and the share cannot tell it from the
    # product's name.
    ceiling = (max(MIN_INTERVIEWS, int(len(refs) * MAX_TERM_SHARE))
               if len(refs) >= MIN_CLAIMS_FOR_CEILING else len(refs))
    claims = [
        [(word, keys) for word, keys in ((w, {k for k in ks if frequency[k] <= ceiling}) for w, ks in _words(ref.claim))
         if keys]
        for ref in unbound
    ]
    neighbours = _neighbours(claims)

    order = sorted(range(len(unbound)), key=lambda i: (-len(neighbours[i]), i))
    taken: "set[int]" = set()
    themes = []
    for centre in order:
        if centre in taken:
            continue
        members = [centre] + [j for j in sorted(neighbours[centre]) if j not in taken]
        sessions = tuple(dict.fromkeys(unbound[i].session_id for i in members))
        if len(members) < 2 or len(sessions) < MIN_INTERVIEWS:
            continue
        taken.update(members)
        themes.append(Theme(
            label=_label([claims[i] for i in members]),
            fact_ids=tuple(unbound[i].fact_id for i in members),
            sessions=sessions,
            claims=tuple(unbound[i].claim for i in members),
        ))
    return tuple(sorted(themes, key=lambda t: (-len(t.sessions), -len(t.fact_ids), t.fact_ids)))


def _words(claim: str) -> "list[tuple[str, frozenset]]":
    """Each content word with the KEYS it matches on: the word itself and any
    stripped form of four letters or more. Never the shortest form alone --
    `שירות` ("service") stripped to three letters is `שיר` ("song"), and
    `הזמנה`/`הזמנות` would not even meet: two words match when their keys
    overlap."""
    found = []
    for word in terms.words(claim):
        if not terms.is_topic_word(word) or word in _REPORTING:
            continue
        found.append((word, frozenset({word} | {f for f in terms.forms(word) if len(f) >= MIN_STEM})))
    return found


def _shared(a, b) -> int:
    """Words in common, counted from the side with fewer matches, so a claim
    saying both "customers" and "customer" does not count one word twice."""
    keys_a = set().union(*(keys for _, keys in a)) if a else set()
    keys_b = set().union(*(keys for _, keys in b)) if b else set()
    from_a = sum(1 for _, keys in a if keys & keys_b)
    from_b = sum(1 for _, keys in b if keys & keys_a)
    return min(from_a, from_b)


def _neighbours(claims) -> "list[set[int]]":
    """Through an inverted index: only claims sharing a key are compared, so
    the cost follows the overlaps, not every pair."""
    index: "dict[str, set[int]]" = {}
    for i, words in enumerate(claims):
        for _, keys in words:
            for key in keys:
                index.setdefault(key, set()).add(i)
    result: "list[set[int]]" = [set() for _ in claims]
    for i, words in enumerate(claims):
        candidates = set().union(*(index[k] for _, keys in words for k in keys)) if words else set()
        for j in candidates:
            if j > i and _shared(words, claims[j]) >= MIN_SHARED_TERMS:
                result[i].add(j)
                result[j].add(i)
    return result


def _label(member_words) -> "tuple[str, ...]":
    """The words most members use, written as they wrote them; ties broken
    by the word itself so the same corpus always gets the same label."""
    present: Counter = Counter()
    surface: "dict[str, Counter]" = {}
    for words in member_words:
        keys_here = set()
        for word, keys in words:
            for key in keys:
                keys_here.add(key)
                surface.setdefault(key, Counter())[word] += 1
        present.update(keys_here)
    label: "list[str]" = []
    for key, n in sorted(present.items(), key=lambda kv: (-kv[1], -sum(surface[kv[0]].values()), kv[0])):
        if n < 2:
            break
        written = sorted(surface[key].items(), key=lambda wc: (-wc[1], wc[0]))[0][0]
        shown = terms.display(written)
        if shown not in label:
            label.append(shown)
        if len(label) >= LABEL_TERMS:
            break
    return tuple(label)
