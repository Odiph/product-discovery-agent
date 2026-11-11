"""`missed --group model`: the one paid call that asks the model, for each
recurring topic, whether the interviewer's question right before it already
asked about it (`prompt_judge.py`), cached in `context/prompted.json`.

Used only with the model grouping, whose labels it judges. Without `--yes`:
how many of your questions and topics would be sent, a few examples, the
cost, and nothing called; the report then decides "prompted" by word match
and says so. With `--yes`: one call, the cache written, then the report.
Whatever decides, the report says which rule it was (`Resolution.rule`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from app.coach import missed_load
from app.coach import prompt_judge as judge_mod
from app.coach import prompt_judge_store as store
from app.coach import reasoning_client

WORD_MATCH = "Prompted: by word match between your question and the topic"
EXAMPLES_SHOWN = 3


@dataclass(frozen=True)
class Resolution:
    judge: "Optional[Callable[[judge_mod.PromptItem], Optional[bool]]]"
    """`None`: the word match decides."""
    rule: str
    """Which rule decides "prompted", printed with the report."""
    notes: "tuple[str, ...]" = ()
    exit_code: Optional[int] = None
    """Set only when the command must stop here (an error)."""


def word_match(why: str = "") -> Resolution:
    return Resolution(None, f"{WORD_MATCH}{f' ({why})' if why else ''}.")


def resolve(context_dir, sessions_root, groups: Sequence, claims: Sequence, *, yes: bool) -> Resolution:
    items = missed_load.prompt_items(context_dir, sessions_root, groups=groups, claims=claims)
    if not items:
        return word_match("no recurring topic has a question of yours before it to judge")
    model = reasoning_client.resolve_judge_model()
    state = store.load(context_dir, items, model)
    if state.status == store.FRESH:
        return _judged(state.judgment, items, "cached in")
    why = {store.ABSENT: "no judgment is cached yet",
           store.STALE: f"the cached judgment is stale: {state.reason}",
           store.UNREADABLE: f"the cached judgment is unusable: {state.reason}"}[state.status]
    plan = preview(items, model)
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
        return _error(f"{exc}. Nothing was written; the previous judgment (if any) is unchanged.")
    except (OSError, ValueError) as exc:
        return _error(f"the judgment could not be saved ({type(exc).__name__}: {exc}).")
    judged = _judged(judgment, items, "just made, saved to")
    return Resolution(judged.judge, judged.rule, notes=plan[:1] + _drop_notes(judgment.dropped))


def preview(items: "Sequence[judge_mod.PromptItem]", model: str) -> "tuple[str, ...]":
    """What the call would send, and what it costs."""
    items = judge_mod.unique_items(items)
    request = judge_mod.assemble_request(items, model=model)
    turns = {text for entry in items for text in (entry.question, *entry.earlier)}
    topics = {entry.topic for entry in items}
    lines = [f"One call to {model} to judge whether you had already asked about each topic: {len(items)} "
             f"question-topic pairs, made of {len(turns)} of your own interview turns (your words, as "
             f"transcribed) and {len(topics)} topic labels. Never anything the interviewee said: no answer, "
             f"no claim, no quote. ~{judge_mod.estimate_input_tokens(request):,} input tokens, plus up to "
             f"{judge_mod.DEFAULT_MAX_TOKENS:,} output tokens (estimated at "
             f"{judge_mod.CHARS_PER_TOKEN:.0f} characters a token, +/-15%).",
             f"For example ({min(EXAMPLES_SHOWN, len(items))} of {len(items)}; each sends your question, up to "
             f"{judge_mod.EARLIER_TURNS} of your questions before it, and the topic):"]
    for entry in items[:EXAMPLES_SHOWN]:
        lines.append(f"  topic: {entry.topic}")
        lines.append(f"    your question: {entry.question}")
        lines += [f"    before it: {text}" for text in entry.earlier]
    return tuple(lines)


def _judged(judgment: judge_mod.Judgment, items, how: str) -> Resolution:
    unique = judge_mod.unique_items(items)
    asked = sum(1 for entry in unique if judgment.asked(entry) is True)
    unanswered = sum(1 for entry in unique if judgment.asked(entry) is None)
    tail = f"; {unanswered} left unanswered, counted as not asked" if unanswered else ""
    return Resolution(
        judgment.asked,
        f"Prompted: by the model's reading of your own questions ({judgment.model}, {how} "
        f"context/{store.CACHE_FILENAME}: {asked} of {len(unique)} question-topic pairs asked about the "
        f"topic{tail}).")


def _error(message: str) -> Resolution:
    return Resolution(None, message, exit_code=1)


def _drop_notes(dropped: judge_mod.Dropped) -> "tuple[str, ...]":
    notes = []
    for what, ids in (("unknown id(s) dropped", dropped.unknown_ids),
                      ("id(s) answered twice, the first kept", dropped.repeated_ids),
                      ("id(s) left unanswered, counted as not asked", dropped.unanswered_ids)):
        if ids:
            notes.append(f"The model's answer had {len(ids)} {what}: {', '.join(ids)}")
    return tuple(notes)
