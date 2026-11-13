"""`missed --group model`: the one paid call that asks the model, for each
occurrence of a recurring topic, whether your next turns followed up on it
(`follow_judge.py`), cached in `context/followed.json`.

Used only with the model grouping, whose labels it judges. Without `--yes`:
how many of your turns and topics would be sent, a few examples, the cost,
and nothing called; the report then decides by word match and says so. With
`--yes`: one call, the cache written, then the report. Whatever decides, the
report says which rule it was (`Resolution.rule`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from app.coach import follow_judge as judge_mod
from app.coach import follow_judge_store as store
from app.coach import missed_load
from app.coach import reasoning_client, token_estimate

WORD_MATCH = "Followed up: by word match between your next questions and the topic"
EXAMPLES_SHOWN = 3


@dataclass(frozen=True)
class Resolution:
    judge: "Optional[Callable[[judge_mod.FollowItem], Optional[bool]]]"
    """`None`: the word match decides."""
    rule: str
    """Which rule decides "followed up", printed with the report."""
    notes: "tuple[str, ...]" = ()
    exit_code: Optional[int] = None
    """Set only when the command must stop here (an error)."""


def word_match(why: str = "") -> Resolution:
    return Resolution(None, f"{WORD_MATCH}{f' ({why})' if why else ''}.")


def resolve(context_dir, sessions_root, groups: Sequence, claims: Sequence, *, yes: bool) -> Resolution:
    items = missed_load.follow_items(context_dir, sessions_root, groups=groups, claims=claims)
    if not items:
        return word_match("no recurring topic has a turn of yours after it to judge")
    model = reasoning_client.resolve_judge_model(context_dir)
    state = store.load(context_dir, items, model)
    if state.status == store.FRESH:
        return _judged(state.judgment, items, "cached in")
    why = {store.ABSENT: "no judgment is cached yet",
           store.STALE: f"the cached judgment is stale: {state.reason}",
           store.UNREADABLE: f"the cached judgment is unusable: {state.reason}"}[state.status]
    note = reasoning_client.pin_note(context_dir)
    plan = preview(items, model, note=note)
    if not yes:
        return Resolution(None, f"{WORD_MATCH} -- the model was not asked ({why}).",
                          notes=plan + ("Nothing called. Re-run with --yes to have the model judge them.",))
    try:
        client = reasoning_client.build_client()
        judgment = judge_mod.judge(client, items, model=model)
        store.write(context_dir, judgment)
    except reasoning_client.CoachConfigError as exc:
        return _error(str(exc))
    except judge_mod.JudgeFailure as exc:
        return _error(f"{exc}{note}. Nothing was written; the previous judgment (if any) is unchanged.")
    except (OSError, ValueError) as exc:
        return _error(f"the judgment could not be saved ({type(exc).__name__}: {exc}).")
    judged = _judged(judgment, items, "just made, saved to")
    return Resolution(judged.judge, judged.rule, notes=plan[:1] + _drop_notes(judgment.dropped))


def preview(items: "Sequence[judge_mod.FollowItem]", model: str, *, note: str = "") -> "tuple[str, ...]":
    """What the call would send, and what it costs."""
    items = judge_mod.unique_items(items)
    request = judge_mod.assemble_request(items, model=model)
    turns = {text for entry in items for _, text in entry.turns}
    topics = {entry.topic for entry in items}
    lines = [f"One call to {model}{note} to judge whether you followed up on each topic: {len(items)} "
             f"topic occurrences, made of {len(turns)} of your own interview turns (your words, as "
             f"transcribed) and {len(topics)} topic labels. Never anything the interviewee said: no answer, "
             f"no claim, no quote. ~{judge_mod.estimate_input_tokens(request):,} input tokens, plus up to "
             f"{judge_mod.DEFAULT_MAX_TOKENS:,} output tokens "
             f"({token_estimate.BASIS}).",
             f"For example ({min(EXAMPLES_SHOWN, len(items))} of {len(items)}; each sends the topic and your "
             f"next turns after it was raised):"]
    for entry in items[:EXAMPLES_SHOWN]:
        lines.append(f"  topic: {entry.topic}")
        lines += [f"    your turn {n} after it: {text}" for n, text in entry.turns]
    return tuple(lines)


def _judged(judgment: judge_mod.Judgment, items, how: str) -> Resolution:
    unique = judge_mod.unique_items(items)
    followed = sum(1 for entry in unique if judgment.followed(entry) is True)
    unanswered = sum(1 for entry in unique if judgment.followed(entry) is None)
    tail = f"; {unanswered} left unanswered, decided by word match" if unanswered else ""
    return Resolution(
        judgment.followed,
        f"Followed up: by the model's reading of your own next turns ({judgment.model}, {how} "
        f"context/{store.CACHE_FILENAME}: {followed} of {len(unique)} topic occurrences followed up{tail}).")


def _error(message: str) -> Resolution:
    return Resolution(None, message, exit_code=1)


def _drop_notes(dropped: judge_mod.Dropped) -> "tuple[str, ...]":
    notes = []
    for what, ids in (("unknown id(s) dropped", dropped.unknown_ids),
                      ("id(s) answered twice, the first kept", dropped.repeated_ids),
                      ("id(s) left unanswered, decided by word match", dropped.unanswered_ids)):
        if ids:
            notes.append(f"The model's follow-up answer had {len(ids)} {what}: {', '.join(ids)}")
    return tuple(notes)
