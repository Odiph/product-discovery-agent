"""Topics interviewees kept raising, and in how many of those interviews the
interviewer followed up: "In 8 of 12 interviews, interviewees raised the
break between rounds. You followed up in 0."

`themes.py` asks what nobody PREDICTED; this asks what nobody PURSUED, so it
groups every claim, bound to a hypothesis or not -- a "between rounds" claim
filed as contrary evidence against an in-match hypothesis is exactly the one
that must still surface. The grouping is `themes.clusters` itself -- or the
model's grouping by meaning (`topics.py`) through `themes.from_groups` --
with a higher floor: a topic must come up in `MIN_INTERVIEWS` interviews.

**Where a topic was raised.** Each member claim's citation span names its
segments; the turn holding them (`walked_past.turns`) is the occurrence.
Never the quote: `quoted_text` is not read, and `CitedClaim` has no field for
it. Two claims citing one turn are one occurrence.

**Followed up.** Within the next `FOLLOW_UP_WINDOW` substantive interviewer
turns, a question that touches the topic's shared terms or reuses the
offer's own words (`walked_past.echoes`), or -- while the talk is still on
the offer -- points back to it by shape (`walked_past.points_back`: "what do
you mean", "מה זאת אומרת", "when you say"). A late "Why?" after an unrelated
aside is about the aside. Short turns ("Mm, okay.") are not moves and use up
none of the window, as in `walked_past`.

**Prompted.** An offer answering a question about its topic is not an
aside. With a `judge` (`missed --group model`), the model decides that from
the interviewer's own words (`prompt_judge.py`, items from `prompt_items`):
the last interviewer turn before the offer, the substantive ones before it as
context, and the topic's label -- never the offer. Without one, word overlap
decides (`_prompted`): a guide question prompts when its own subject words
are the topic's terms, any other question through shared words. Measured on
the mock interviews, that word rule recognised 52 of 91 guide questions and
caught no pitch, which is why the model rule exists.

**A detector, not a judge**, bounding the misses from below: a shared word
counts as a follow-up, so a "followed up in 0" is a strong claim and a
"followed up in 3" may flatter. Three things never count (measured
2026-11-11): the next question on the interview guide (`is_scripted`), a word
the interviewer uses in most of the project's interviews
(`project_vocabulary`: the product's name), a short Hebrew stem meeting
another word (`walked_past.content_forms`), and a question the critic flagged
as a pitch or leading, where `critique-questions` has run. Pure: no I/O; returns ids, seq numbers,
outcome names and the cluster's own label words, never transcript text. The
per-interview arithmetic is `interview_summary.follow_through`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from app.coach import interview_summary as summary_mod
from app.coach import prompt_judge
from app.coach import themes
from app.coach import walked_past
from app.coach.walked_past import Turn

MIN_INTERVIEWS = 3
FOLLOW_UP_WINDOW = 2
# A word the interviewer uses in more than this share of the project's
# interviews is the project's vocabulary -- the product's name, the guide's
# own subjects -- and naming it is no evidence of engaging an offer. Measured:
# "Claude" was in 12 of 12, the overlay complaint's "window" in 3.
VOCABULARY_SHARE = 0.5
# For "was this already asked about?", only words in nearly every interview
# are the product itself. "voice" was asked in 7 of 12: vocabulary to the
# judge (naming it is no follow-up), but asking about it IS a prompt.
PROMPT_VOCABULARY_SHARE = 0.75
# Below this, "most interviews" is a handful, and a follow-up the interviewer
# happened to repeat could not be told from the vocabulary.
MIN_INTERVIEWS_FOR_VOCABULARY = 6
# A turn holding at least this share of a guide question's content words IS
# that question: the guide moving on, never a follow-up.
SCRIPT_MATCH_SHARE = 0.5
MIN_SCRIPT_WORDS = 2

FOLLOWED = "followed up"
WALKED_PAST = "walked past"
# Not judged -- each its own reason, because each has its own remedy.
MISSING_SEQ = "cited segment not in the transcript"
NO_TRANSCRIPT = "no readable transcript"
ROLES_UNCONFIRMED = "speakers not confirmed"
NOT_INTERVIEWEE = "cites interviewer speech"
NO_QUESTION = "no interviewer turn after it"
_JUDGED = {FOLLOWED: True, WALKED_PAST: False}

STATE_NO_EXTRACTION = "no-extraction"
STATE_NO_TOPIC = "no-topic"
STATE_NOTHING_JUDGED = "nothing-judged"
STATE_ONLY_ASKED = "only-asked"
STATE_RESULT = "result"


@dataclass(frozen=True)
class CitedClaim:
    """A claim with its citation span: `FactRef` plus the `seqs` it leaves
    out on purpose (they are a handle into the transcript). This one never
    leaves the operator's machine -- the command prints seq numbers locally."""

    fact_id: str
    session_id: str
    claim: str
    bearings: "tuple[tuple[str, str], ...]"
    seqs: "tuple[int, ...]"


def cited_claim(fact: Any) -> CitedClaim:
    """Field by field, never a dump: `Fact`'s other field is `quoted_text`."""
    return CitedClaim(
        fact_id=fact.id,
        session_id=fact.session_id,
        claim=fact.claim,
        bearings=tuple((bearing.hypothesis_id, bearing.stance) for bearing in fact.bearings),
        seqs=tuple(fact.seqs),
    )


@dataclass(frozen=True)
class Occurrence:
    session_id: str
    seq: int
    """The first segment the claim cites."""
    outcome: str
    prompted: bool = False
    """The interviewer's last substantive question before it was already
    about the topic (`_prompted`). Unknown -- no transcript -- counts as
    unprompted, so a missing file can never hide an aside."""
    unanswered: bool = False
    """The judge had no answer for the question before it (counted as
    unprompted)."""

    @property
    def followed(self) -> Optional[bool]:
        return _JUDGED.get(self.outcome)


@dataclass(frozen=True)
class Topic:
    label: "tuple[str, ...]"
    fact_ids: "tuple[str, ...]"
    occurrences: "tuple[Occurrence, ...]"
    tally: summary_mod.FollowThrough
    """Over the UNPROMPTED occurrences: the headline's numbers."""
    raised_interviews: int = 0
    """Every interview it came up in, asked or not."""
    asked_only_interviews: int = 0


@dataclass(frozen=True)
class Report:
    interviews: int
    """Interviews with at least one extracted claim -- the "of 12"."""
    topics: "tuple[Topic, ...]"
    """Raised UNPROMPTED in `MIN_INTERVIEWS` or more interviews."""
    asked_topics: "tuple[Topic, ...]" = ()
    """Recurring, but unprompted in fewer: "Raised when you asked". Kept, not
    dropped, so a topic never silently disappears from the report."""

    @property
    def state(self) -> str:
        if not self.interviews:
            return STATE_NO_EXTRACTION
        if not self.topics:
            return STATE_ONLY_ASKED if self.asked_topics else STATE_NO_TOPIC
        if not any(topic.tally.judged_interviews for topic in self.topics):
            return STATE_NOTHING_JUDGED
        return STATE_RESULT


def find(
    claims: "Sequence[CitedClaim]",
    turns_by_session: "Mapping[str, Sequence[Turn]]",
    *,
    unconfirmed: "frozenset[str]" = frozenset(),
    groups: "Optional[Sequence[Any]]" = None,
    scripts: "Mapping[str, Sequence[str]]" = {},
    vocabulary: "frozenset[str]" = frozenset(),
    flagged: "Mapping[str, frozenset[int]]" = {},
    judge: "Optional[Callable[[prompt_judge.PromptItem], Optional[bool]]]" = None,
) -> Report:
    """`turns_by_session`: each session's `walked_past.turns`; a session
    absent from it had no readable transcript. `unconfirmed`: sessions whose
    speakers are live guesses -- a follow-up is a claim about who spoke.
    `groups`: the model's topics (`topics.TopicGroup`), used instead of the
    lexical clusters when given; the floor and the judge are the same.
    `scripts`: each session's guide questions (`missed_load.session_scripts`);
    `vocabulary`: `project_vocabulary(turns_by_session)`. `flagged`: each
    session's seqs of questions the critic marked a pitch or leading
    (`missed_load.flagged_seqs`). All three only ever REMOVE evidence of a
    follow-up. `judge`: the model's answer for a `prompt_judge.PromptItem`
    (True, False, or None for no answer); when given, it decides "prompted"
    for every occurrence with an interviewer turn before it, in place of the
    word match (`_prompted`). No answer counts as unprompted."""
    script_sets = {sid: script_keys(texts) for sid, texts in scripts.items()}
    subjects = {sid: script_subjects(items) for sid, items in script_sets.items()}
    prompt_vocabulary = project_vocabulary(turns_by_session, share=PROMPT_VOCABULARY_SHARE)
    claims = [c for c in claims if isinstance(c.seqs, tuple) and c.seqs]
    by_id = {claim.fact_id: claim for claim in claims}
    clusters = (themes.clusters(claims, min_interviews=MIN_INTERVIEWS) if groups is None
                else themes.from_groups(claims, groups, min_interviews=MIN_INTERVIEWS))
    topics, asked = [], []
    for cluster in clusters:
        occurrences = _occurrences([by_id[f] for f in cluster.fact_ids], cluster.terms - vocabulary,
                                   turns_by_session, unconfirmed, script_sets, vocabulary, flagged, subjects,
                                   prompt_terms=cluster.terms - prompt_vocabulary,
                                   prompt_vocabulary=prompt_vocabulary,
                                   judge=judge, label=cluster.label)
        split = summary_mod.split_by_prompt((o.session_id, o.followed, o.prompted) for o in occurrences)
        topic = Topic(label=cluster.label, fact_ids=cluster.fact_ids, occurrences=occurrences,
                      tally=split.unprompted, raised_interviews=split.raised_interviews,
                      asked_only_interviews=split.asked_only_interviews)
        # The floor counts the interviews it came up in UNPROMPTED.
        (topics if split.unprompted.raised_interviews >= MIN_INTERVIEWS else asked).append(topic)
    topics.sort(key=lambda t: (-t.tally.missed_interviews, -t.tally.raised_interviews, t.label))
    asked.sort(key=lambda t: (-t.raised_interviews, t.label))
    return Report(interviews=summary_mod.count_interviews(claims), topics=tuple(topics), asked_topics=tuple(asked))


def prompt_items(claims: "Sequence[CitedClaim]", turns_by_session: "Mapping[str, Sequence[Turn]]",
                 **kwargs: Any) -> "tuple[prompt_judge.PromptItem, ...]":
    """Every item a `judge` passed to `find` with the same arguments would be
    asked, each once: what `missed --group model` sends."""
    asked: "list[prompt_judge.PromptItem]" = []

    def record(item: prompt_judge.PromptItem) -> None:
        asked.append(item)
        return None

    find(claims, turns_by_session, **{**kwargs, "judge": record})
    return prompt_judge.unique_items(asked)


def topic_name(label: "tuple[str, ...]") -> str:
    return ", ".join(label)


def question_turns(sequence: "Sequence[Turn]", position: int) -> "Optional[tuple[Turn, tuple[Turn, ...]]]":
    """The interviewer's last turn before `position`, whatever its length
    ("Anything else?" is what was answered), and up to
    `prompt_judge.EARLIER_TURNS` substantive interviewer turns before it,
    oldest first. `None` when the interviewer had not spoken yet."""
    before = [turn for turn in sequence[:position] if turn.speaker == walked_past.INTERVIEWER]
    if not before:
        return None
    earlier = [turn for turn in before[:-1] if len(turn.text.split()) >= walked_past.MIN_MOVE_WORDS]
    return before[-1], tuple(earlier[-prompt_judge.EARLIER_TURNS:])


def project_vocabulary(turns_by_session: "Mapping[str, Sequence[Turn]]", *,
                       share: float = VOCABULARY_SHARE) -> "frozenset[str]":
    """Every form (echo and topic-term alike) the interviewer uses in more
    than `VOCABULARY_SHARE` of the interviews. Counted per interview, not per
    turn: the guide's scripted turns dominate a per-turn count, while the
    product's name is said once or twice an interview -- but in every one."""
    used: "list[set[str]]" = []
    for sequence in turns_by_session.values():
        keys: "set[str]" = set()
        for turn in sequence:
            if turn.speaker == walked_past.INTERVIEWER:
                keys |= walked_past.content_forms(turn.text) | themes.match_keys(turn.text)
        used.append(keys)
    if len(used) < MIN_INTERVIEWS_FOR_VOCABULARY:
        return frozenset()
    counts: "dict[str, int]" = {}
    for keys in used:
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    return frozenset(key for key, n in counts.items() if n > share * len(used))


def script_keys(texts: "Sequence[str]") -> "tuple[tuple[frozenset[str], ...], ...]":
    """Each guide question as one set of match keys per content word; a
    question of fewer than `MIN_SCRIPT_WORDS` content words is too short to
    recognise and is left out."""
    return tuple(words for _, words in _script_items(texts))


def _script_items(texts):
    items = []
    for text in texts:
        if isinstance(text, str):
            words = tuple(keys for keys in (themes.match_keys(w) for w in text.split()) if keys)
            if len(words) >= MIN_SCRIPT_WORDS:
                items.append((text, words))
    return items


def is_scripted(text: str, items: "tuple[tuple[frozenset[str], ...], ...]") -> bool:
    return _script_index(text, items) is not None


def _script_index(text: str, items) -> Optional[int]:
    keys = themes.match_keys(text)
    for index, item in enumerate(items):
        if sum(1 for word in item if word & keys) >= SCRIPT_MATCH_SHARE * len(item):
            return index
    return None


def script_subjects(items: "tuple[tuple[frozenset[str], ...], ...]") -> "tuple[frozenset[str], ...]":
    """What each guide question is ABOUT: its words no other guide question
    uses. "Would you pay for Claudictive?" is about paying; the product's
    name is in half the guide and prompts nothing."""
    subjects = []
    for index, item in enumerate(items):
        others = frozenset().union(*(word for j, other in enumerate(items) if j != index for word in other))
        subjects.append(frozenset().union(*(word for word in item if not word & others)))
    return tuple(subjects)


def _judged(sequence, position: int, judge, label: "tuple[str, ...]") -> "tuple[bool, bool]":
    """(prompted, unanswered) by the model's judgment of the interviewer's
    own turns (`question_turns`); the offer is never part of it."""
    found = question_turns(sequence, position)
    if found is None:
        return False, False
    question, earlier = found
    answer = judge(prompt_judge.item(question.text, (t.text for t in earlier), topic_name(label)))
    return answer is True, answer is None


def _prompted(sequence, position: int, terms: "frozenset[str]", scripted, subjects,
              vocabulary: "frozenset[str]") -> bool:
    """By word overlap: whether the interviewer's last substantive question
    before the offer -- past backchannels and the interviewee's own turns --
    was already about the topic. A guide question prompts only when its own
    subject (`script_subjects`) is one of the topic's terms; any other
    question prompts through the topic's terms or the offer's words, the
    project's vocabulary excluded."""
    offer = sequence[position]
    question = next((turn for turn in reversed(sequence[:position]) if turn.speaker == walked_past.INTERVIEWER
                     and len(turn.text.split()) >= walked_past.MIN_MOVE_WORDS), None)
    if question is None:
        return False
    item = _script_index(question.text, scripted)
    if item is not None:
        # Against the TOPIC's words, never the offer's: an answer says the
        # question's phrasing back ("usually...") whatever it is about.
        return bool(subjects[item] & terms)
    return bool(themes.match_keys(question.text) & terms) or walked_past.echoes(
        offer.text, question.text, ignore=vocabulary)


def _occurrences(members, terms, turns_by_session, unconfirmed, script_sets=None,
                 vocabulary: "frozenset[str]" = frozenset(),
                 flagged: "Optional[Mapping[str, frozenset[int]]]" = None,
                 subjects: "Optional[Mapping[str, tuple]]" = None, *,
                 prompt_terms: "frozenset[str]" = frozenset(),
                 prompt_vocabulary: "frozenset[str]" = frozenset(),
                 judge=None,
                 label: "tuple[str, ...]" = ()) -> "tuple[Occurrence, ...]":
    seen: "dict[tuple[str, Any], Occurrence]" = {}
    for claim in members:
        prompted = unanswered = False
        seq = min(claim.seqs)
        sequence = turns_by_session.get(claim.session_id)
        position = _turn_holding(sequence, claim.seqs) if sequence else None
        if claim.session_id in unconfirmed:
            key, outcome = (claim.session_id, seq), ROLES_UNCONFIRMED
        elif sequence is None:
            key, outcome = (claim.session_id, seq), NO_TRANSCRIPT
        elif position is None:
            key, outcome = (claim.session_id, seq), MISSING_SEQ
        else:
            scripted = (script_sets or {}).get(claim.session_id, ())
            key, outcome = (claim.session_id, ("turn", position)), _judge(
                sequence, position, terms, scripted, vocabulary, (flagged or {}).get(claim.session_id, frozenset()))
            if outcome == NOT_INTERVIEWEE:
                pass
            elif judge is not None:
                prompted, unanswered = _judged(sequence, position, judge, label)
            else:
                prompted = _prompted(sequence, position, prompt_terms, scripted,
                                     (subjects or {}).get(claim.session_id, ()), prompt_vocabulary)
        if key not in seen or seq < seen[key].seq:
            seen[key] = Occurrence(session_id=claim.session_id, seq=seq, outcome=outcome, prompted=prompted,
                                   unanswered=unanswered)
    return tuple(sorted(seen.values(), key=lambda o: (o.session_id, o.seq)))


def _turn_holding(sequence: "Sequence[Turn]", seqs: "tuple[int, ...]") -> Optional[int]:
    wanted = set(seqs)
    for position, turn in enumerate(sequence):
        if wanted & set(turn.seqs):
            return position
    return None


def _judge(sequence: "Sequence[Turn]", position: int, terms: "frozenset[str]",
           scripted: "tuple[tuple[frozenset[str], ...], ...]" = (),
           vocabulary: "frozenset[str]" = frozenset(), flagged: "frozenset[int]" = frozenset()) -> str:
    """`terms` arrive with the vocabulary already removed."""
    offer = sequence[position]
    if offer.speaker != walked_past.INTERVIEWEE:
        return NOT_INTERVIEWEE
    still_on_offer, moves = True, 0
    for turn in sequence[position + 1:]:
        on_topic = (bool(themes.match_keys(turn.text) & terms)
                    or walked_past.echoes(offer.text, turn.text, ignore=vocabulary))
        if turn.speaker == walked_past.INTERVIEWEE:
            # The interviewee carrying on about it keeps a "Why?" pointing here.
            still_on_offer = still_on_offer and on_topic
            continue
        # The next guide question is the guide moving on, whatever words it
        # happens to share with the offer.
        # A pitch or a leading question puts the interviewer's idea in the
        # offer's place, even when it names the offer's words: the critic's
        # flag (by seq, from `critique-questions`) outranks the word match.
        not_engaging = is_scripted(turn.text, scripted) or bool(flagged & set(turn.seqs))
        if not not_engaging and (
                on_topic or (still_on_offer and walked_past.points_back(turn.text))):
            return FOLLOWED
        if len(turn.text.split()) < walked_past.MIN_MOVE_WORDS:
            continue
        moves += 1
        still_on_offer = False
        if moves >= FOLLOW_UP_WINDOW:
            return WALKED_PAST
    return WALKED_PAST if moves else NO_QUESTION
