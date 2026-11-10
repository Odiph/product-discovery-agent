"""`--group` for `missed` and `themes`: which grouping a report uses, and the
one paid call that makes the model's.

- `auto` (the default): the model's grouping if `context/topics.json` is
  fresh for these claims and the current extract model, else the lexical one
  -- and a stale or unreadable cache is SAID, never quietly ignored.
- `model`: the cache if fresh; otherwise, without `--yes`, what would be sent
  (claims, estimated tokens, model) and nothing else; with `--yes`, one call,
  the cache written, then the report.
- `lexical`: shared words, cache or not.

Whatever is chosen, the command's first line says so (`describe`).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Optional, Sequence

from app.coach import reasoning_client
from app.coach import topics as topics_mod
from app.coach import topics_store

AUTO, MODEL, LEXICAL = "auto", "model", "lexical"
_DROPS_SHOWN = 10


@dataclass(frozen=True)
class Resolution:
    groups: "Optional[tuple[topics_mod.TopicGroup, ...]]"
    """`None`: use the lexical grouping."""
    headline: str
    """The first line of output: which grouping, and why."""
    notes: "tuple[str, ...]" = ()
    exit_code: Optional[int] = None
    """Set when the command must stop here (estimate shown, or an error)."""


def add_arguments(parser: argparse.ArgumentParser, *, command: str) -> None:
    parser.add_argument(
        "--group", choices=(AUTO, MODEL, LEXICAL), default=AUTO,
        help=f"how claims are grouped into topics: {MODEL!r} asks the extract model once to group them by "
             f"meaning (needs --yes to spend; cached in context/{topics_store.CACHE_FILENAME}), {LEXICAL!r} by "
             f"shared words, {AUTO!r} (default) the cached model grouping if still fresh, else shared words",
    )
    parser.add_argument("--yes", action="store_true",
                        help=f"with --group {MODEL}: make the call; without it `{command}` only shows what "
                             f"would be sent")


def resolve(context_dir, claims: Sequence, *, mode: str, yes: bool) -> Resolution:
    lines = topics_mod.claim_lines(claims)
    model = reasoning_client.resolve_extract_model()
    if mode == LEXICAL:
        return Resolution(None, "Grouping: by shared words (--group lexical).")
    state = topics_store.load(context_dir, lines, model)
    if state.status == topics_store.FRESH:
        return Resolution(state.grouping.topics, _model_headline(state.grouping, "cached in"))
    if mode == AUTO:
        return Resolution(None, _lexical_headline(state))
    return _run(context_dir, lines, model, state, yes=yes)


def _run(context_dir, lines, model, state, *, yes: bool) -> Resolution:
    request = topics_mod.assemble_request(lines, model=model)
    why = {topics_store.ABSENT: "no grouping is cached yet",
           topics_store.STALE: f"the cached grouping is stale: {state.reason}",
           topics_store.UNREADABLE: f"the cached grouping is unusable: {state.reason}"}[state.status]
    if not lines:
        return Resolution(None, "Grouping: by model -- there are no extracted claims to group.", exit_code=0)
    plan = (f"One call to {model}: {len(lines)} claims (claim text, interview id and an alias each; never "
            f"quotes), ~{topics_mod.estimate_input_tokens(request):,} input tokens, plus up to "
            f"{topics_mod.DEFAULT_MAX_TOKENS:,} output tokens (estimated at "
            f"{topics_mod.CHARS_PER_TOKEN:.0f} characters a token, +/-15%).")
    if not yes:
        return Resolution(None, f"Grouping: by model -- not run ({why}).",
                          notes=(plan, "Nothing called. Re-run with --yes to group them."), exit_code=0)
    try:
        client = reasoning_client.build_client()
        grouping = topics_mod.group_claims(client, lines, model=model)
        topics_store.write(context_dir, grouping)
    except reasoning_client.CoachConfigError as exc:
        return _error(str(exc))
    except topics_mod.GroupingFailure as exc:
        return _error(f"{exc}. Nothing was written; the previous grouping (if any) is unchanged.")
    except (OSError, ValueError) as exc:
        return _error(f"the grouping could not be saved ({type(exc).__name__}: {exc}).")
    return Resolution(grouping.topics, _model_headline(grouping, "just made, saved to"),
                      notes=(plan,) + _drop_notes(grouping.dropped))


def describe(resolution: Resolution) -> None:
    """Prints the headline (stdout, first) and the notes; errors to stderr."""
    if resolution.exit_code not in (None, 0):
        print(f"ERROR: {resolution.headline}", file=sys.stderr)
        return
    print(resolution.headline)
    for note in resolution.notes:
        print(f"  {note}")


def _error(message: str) -> Resolution:
    return Resolution(None, message, exit_code=1)


def _model_headline(grouping: topics_mod.Grouping, how: str) -> str:
    return (f"Grouping: by model {grouping.model} ({how} context/{topics_store.CACHE_FILENAME}, "
            f"{len(grouping.topics)} topic(s)).")


def _lexical_headline(state: topics_store.CacheState) -> str:
    if state.status == topics_store.ABSENT:
        return "Grouping: by shared words. To group by meaning: --group model."
    return (f"Grouping: by shared words -- context/{topics_store.CACHE_FILENAME} is {state.status} "
            f"({state.reason}), so it was not used. Re-run with --group model --yes to regroup.")


def _drop_notes(dropped: topics_mod.Dropped) -> "tuple[str, ...]":
    notes = []
    for count, what, items in (
        (len(dropped.unknown_ids), "unknown claim id(s) dropped", dropped.unknown_ids),
        (len(dropped.repeated_ids), "claim(s) placed in two topics, kept in the first", dropped.repeated_ids),
        (len(dropped.empty_topics), "topic(s) dropped as empty or unlabelled", dropped.empty_topics),
    ):
        if count:
            shown = ", ".join(items[:_DROPS_SHOWN]) + (" ..." if count > _DROPS_SHOWN else "")
            notes.append(f"The model's answer had {count} {what}: {shown}")
    return tuple(notes)
