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
gate 20 protects. It can be checked by hand, and it misses a topic worded
differently each time; `from_groups` takes the model's grouping instead
(`topics.py`, `--group model`).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Sequence

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
    terms: "frozenset[str]" = frozenset()
    """Every match key two or more members share -- the label is the top
    `LABEL_TERMS` of these. What a question must touch to be ON this theme
    (`missed.py`); never shown, so it can be wider than the label."""


def unbound_themes(refs: Sequence) -> "tuple[Theme, ...]":
    """`refs`: facts as `interview_summary.FactRef` (claim, session_id,
    bearings). Only those with no bearing are grouped."""
    return clusters(refs, include=lambda ref: not ref.bearings, min_interviews=MIN_INTERVIEWS)


def clusters(refs: Sequence, *, include: "Callable[[Any], bool]" = lambda ref: True,
             min_interviews: int = MIN_INTERVIEWS) -> "tuple[Theme, ...]":
    """The grouping itself, over the refs `include` admits; `unbound_themes`
    admits the unbound only, `missed.py` admits every claim (a "between
    rounds" claim bound to an in-match hypothesis as contrary evidence is
    still something interviewees kept raising). The common-word ceiling is
    always counted over ALL the refs, so the two callers agree on what a
    distinctive word is.

    A theme is a CENTRE claim and its direct neighbours, never a chain: with
    connected components, "invoice export" -> "export csv" -> "csv import"
    would drift from invoicing to onboarding inside one theme. Here every
    member shares the threshold with the centre itself. Centres are taken
    most-connected first, ties by position, so the result is deterministic."""
    refs = _with_text(refs)
    candidates = [ref for ref in refs if include(ref)]
    if len(candidates) < 2:
        return ()
    distinctive = _distinctive_words(refs)
    claims = [distinctive(ref.claim) for ref in candidates]
    neighbours = _neighbours(claims)

    order = sorted(range(len(candidates)), key=lambda i: (-len(neighbours[i]), i))
    taken: "set[int]" = set()
    themes = []
    for centre in order:
        if centre in taken:
            continue
        members = [centre] + [j for j in sorted(neighbours[centre]) if j not in taken]
        sessions = tuple(dict.fromkeys(candidates[i].session_id for i in members))
        if len(members) < 2 or len(sessions) < min_interviews:
            continue
        taken.update(members)
        themes.append(Theme(
            label=_label([claims[i] for i in members]),
            fact_ids=tuple(candidates[i].fact_id for i in members),
            sessions=sessions,
            claims=tuple(candidates[i].claim for i in members),
            terms=_shared_keys([claims[i] for i in members]),
        ))
    return tuple(sorted(themes, key=lambda t: (-len(t.sessions), -len(t.fact_ids), t.fact_ids)))


def from_groups(refs: Sequence, groups: Sequence, *, include: "Callable[[Any], bool]" = lambda ref: True,
                min_interviews: int = MIN_INTERVIEWS) -> "tuple[Theme, ...]":
    """Themes from a grouping made elsewhere (`topics.py`, by meaning), held
    to the same rules as `clusters`: `include` admits members, a theme needs
    two members from `min_interviews` interviews, and its `terms` are the
    distinctive keys two members share -- the ceiling counted over ALL the
    refs, as above, so `missed` judges a follow-up on the same kind of word
    either way. `groups`: anything with `label` (str) and `fact_ids`; an id
    not among `refs` is skipped, a claim placed twice stays in its first."""
    refs = _with_text(refs)
    by_id: "dict[str, Any]" = {}
    for ref in refs:
        by_id.setdefault(ref.fact_id, ref)
    distinctive = _distinctive_words(refs)
    taken: "set[str]" = set()
    themes = []
    for group in groups:
        members = [by_id[fact_id] for fact_id in dict.fromkeys(group.fact_ids)
                   if fact_id in by_id and fact_id not in taken and include(by_id[fact_id])]
        sessions = tuple(dict.fromkeys(ref.session_id for ref in members))
        if len(members) < 2 or len(sessions) < min_interviews:
            continue
        taken.update(ref.fact_id for ref in members)
        themes.append(Theme(
            label=(group.label,),
            fact_ids=tuple(ref.fact_id for ref in members),
            sessions=sessions,
            claims=tuple(ref.claim for ref in members),
            terms=_shared_keys([distinctive(ref.claim) for ref in members]),
        ))
    return tuple(sorted(themes, key=lambda t: (-len(t.sessions), -len(t.fact_ids), t.fact_ids)))


def _with_text(refs: Sequence) -> list:
    return [ref for ref in refs if isinstance(getattr(ref, "claim", None), str) and ref.claim.strip()]


def _distinctive_words(refs: Sequence) -> "Callable[[str], list]":
    """A claim's content words with their keys, minus every key more than
    `MAX_TERM_SHARE` of `refs` use (the product's name, its domain)."""
    frequency: Counter = Counter()
    for ref in refs:
        frequency.update({key for _, keys in _words(ref.claim) for key in keys})
    # Below MIN_CLAIMS_FOR_CEILING no word is "too common": in six claims a
    # real theme IS half the corpus, and the share cannot tell it from the
    # product's name.
    ceiling = (max(MIN_INTERVIEWS, int(len(refs) * MAX_TERM_SHARE))
               if len(refs) >= MIN_CLAIMS_FOR_CEILING else len(refs))

    def distinctive(claim: str) -> list:
        return [(word, keys) for word, keys in ((w, {k for k in ks if frequency[k] <= ceiling})
                                                for w, ks in _words(claim)) if keys]

    return distinctive


def match_keys(text: str) -> "frozenset[str]":
    """Every key `text`'s content words match on -- the same keys a claim
    is grouped by, so a question can be tested against `Theme.terms`."""
    return frozenset().union(*(keys for _, keys in _words(text)))


def _shared_keys(member_words) -> "frozenset[str]":
    present: Counter = Counter()
    for words in member_words:
        present.update(set().union(*(keys for _, keys in words)) if words else set())
    return frozenset(key for key, n in present.items() if n >= 2)


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
