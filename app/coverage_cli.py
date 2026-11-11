"""`python -m app coverage --project <node> [--yes]`: which guide questions
the interviews WITHOUT a live coverage record (imported, or recorded with
the coach off) really asked, read by the model from your own turns
(`coverage_judge.py`), cached in `context/coverage.json` for `prep`.

Without `--yes`: what would be sent (how many interviews and turns, a few
example turns, the survey) and the cost; nothing called. With `--yes`: one
call, the cache written, and the questions found per interview. `prep`
never calls the model: it reads this cache when fresh.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from app import config as config_mod
from app.coach import coverage_judge as judge_mod
from app.coach import coverage_store as store
from app.coach import prep_load
from app.coach import reasoning_client
from app.coach.context import ContextValidationError, load_survey

EXAMPLES_SHOWN = 3


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    coverage = subparsers.add_parser(
        "coverage",
        help="For interviews with no live coverage record (imported, coach off): ask the model once which "
             "guide questions you asked, for `prep` (sends your own turns only; needs --yes to spend)",
    )
    add_project_argument(coverage)
    coverage.add_argument("--yes", action="store_true", help="make the call; without it, only show what "
                                                             "would be sent")


def run(args: argparse.Namespace, apply_project) -> int:
    from benchmark.console import use_utf8_console

    use_utf8_console()
    cfg = apply_project(config_mod.load_config(), args)
    try:
        survey = load_survey(cfg.context_dir)
    except ContextValidationError as exc:
        print(f"ERROR: the survey cannot be read ({exc}).", file=sys.stderr)
        return 1
    questions = judge_mod.questions(survey)
    turns = prep_load.untracked_turns(cfg.sessions_root)
    if not questions:
        print("No survey yet: write one in `python -m app author`; there is nothing to look for.")
        return 0
    if not turns:
        print("Every interview has a live coverage record (or there is none yet): nothing to read.")
        return 0
    model = reasoning_client.resolve_judge_model()
    state = store.load(cfg.context_dir, questions, turns, model)
    if state.status == store.FRESH:
        print(f"Coverage: already read by {model} (cached in context/{store.CACHE_FILENAME}); nothing called.")
        _print_found(state.coverage, questions)
        return 0
    why = {store.ABSENT: "nothing is cached yet",
           store.STALE: f"the cached reading is stale: {state.reason}",
           store.UNREADABLE: f"the cached reading is unusable: {state.reason}"}[state.status]
    for line in preview(questions, turns, model):
        print(line)
    if not args.yes:
        print(f"Nothing called ({why}). Re-run with --yes to read them.")
        return 0
    try:
        client = reasoning_client.build_client()
        coverage = judge_mod.read(client, questions, turns, model=model)
        store.write(cfg.context_dir, coverage, {qid for qid, _ in questions})
    except reasoning_client.CoachConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except judge_mod.CoverageFailure as exc:
        print(f"ERROR: {exc}. Nothing was written; the previous reading (if any) is unchanged.", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"ERROR: the reading could not be saved ({type(exc).__name__}: {exc}).", file=sys.stderr)
        return 1
    print(f"Coverage: read by {model}, saved to context/{store.CACHE_FILENAME}.")
    for what, ids in (("unknown id(s) dropped", coverage.dropped.unknown_ids),
                      ("turn(s) answered twice, the first kept", coverage.dropped.repeated_turns)):
        if ids:
            print(f"  The model's answer had {len(ids)} {what}: {', '.join(ids)}")
    _print_found(coverage, questions)
    return 0


def preview(questions, turns, model: str) -> "tuple[str, ...]":
    request = judge_mod.assemble_request(questions, turns, model=model)
    rows = judge_mod.sessions(turns)
    count = sum(len(t) for _, t in rows)
    lines = [f"One call to {model} to read which guide questions you asked: {len(rows)} interview(s) with no "
             f"live coverage record, {count} of your own turns (your words, as transcribed) and the "
             f"{len(questions)} survey questions. Never anything the interviewee said. "
             f"~{judge_mod.estimate_input_tokens(request):,} input tokens, plus up to "
             f"{judge_mod.DEFAULT_MAX_TOKENS:,} output tokens (estimated at "
             f"{judge_mod.CHARS_PER_TOKEN:.0f} characters a token, +/-15%).",
             f"For example, the first {min(EXAMPLES_SHOWN, len(rows[0][1]))} turns of {rows[0][0]}:"]
    lines += [f"  {text}" for text in rows[0][1][:EXAMPLES_SHOWN]]
    return tuple(lines)


def _print_found(coverage: judge_mod.Coverage, questions) -> None:
    total = len(questions)
    for sid, ids in coverage.asked:
        print(f"  {sid}: {len(ids)} of {total} guide questions found ({', '.join(ids) or 'none'})")
    print("`prep` now counts these as asked. A question not found is still \"check by hand\", never "
          "\"never asked\": the model's recall on your interviews is not measured.")
