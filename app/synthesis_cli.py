"""`python -m app synthesize --project <node> [--yes]`: every interview in the
project, read side by side in one paid model pass (`app/coach/synthesis.py`)
that builds the opportunity solution tree, cached in `context/synthesis.json`.

Without `--yes`: what would be sent (claims, hypothesis statements with their
kind and parent, the outcome, and the previous tree's labels when there is
one), the estimated tokens, and nothing called. With `--yes`: one call, the
cache written, then the tree and the diff against the previous one. A fresh
cache is printed with no call, so a re-run with no new facts costs nothing.
The estimate is tokens, not money, as in every other preview
(`extract_all`'s docstring says why).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

from app import config as config_mod
from app import project_meta
from app.coach import ost as ost_mod
from app.coach import reasoning_client, token_estimate
from app.coach import synthesis as syn
from app.coach import synthesis_store as store
from app.coach import synthesis_view
from app.coach.corpus import CorpusValidationError
from app.synthesis_report import print_tree

EXAMPLES_SHOWN = 3


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    parser = subparsers.add_parser(
        "synthesize",
        help="Build the opportunity solution tree from every extracted claim in one model call: your "
             "outcome, opportunities heard across interviews, solutions with their interview signal, "
             "assumptions, and the next story to ask for "
             f"(needs --yes to spend; cached in context/{store.CACHE_FILENAME})",
    )
    add_project_argument(parser)
    parser.add_argument("--yes", action="store_true",
                        help="make the call; without it `synthesize` only shows what would be sent")


def author_command(project: str) -> str:
    return "python -m app author" + (f" --project {project}" if project else "")


def run(args: argparse.Namespace, apply_project, read_corpus_refs) -> int:
    from benchmark.console import use_utf8_console

    use_utf8_console()
    cfg = apply_project(config_mod.load_config(), args)
    context_dir = Path(cfg.context_dir)
    project = getattr(args, "project", None) or ""
    if project_meta.is_demo_node(context_dir.parent):
        print(project_meta.MOCK_LABEL)
    try:
        hypotheses, refs, corpus_exists = read_corpus_refs(cfg, project_label=project)
    except CorpusValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    items = syn.claim_items(refs)
    if not corpus_exists or not items:
        print("No extracted claims yet: run `python -m app extract <session>` on your interviews first.")
        return 0
    hyps = syn.hypothesis_lines(hypotheses)
    model = reasoning_client.resolve_judge_model(context_dir)
    outcome = syn.outcome_input(ost_mod.read_outcome(context_dir))

    def report(result) -> None:
        print_tree(synthesis_view.view(result, refs, hypotheses), set_outcome=author_command(project))

    state = store.load(context_dir, items, hyps, model, outcome)
    if state.status == store.FRESH:
        print(f"Synthesis by {model}, cached in context/{store.CACHE_FILENAME} (no call made).")
        report(state.synthesis)
        return 0
    if state.status != store.ABSENT:
        print(f"context/{store.CACHE_FILENAME} is {state.status}: {state.reason}.")
    prior = store.previous(context_dir)
    note = reasoning_client.pin_note(context_dir)
    for line in preview(items, hyps, model, outcome=outcome, prior=prior, note=note):
        print(line)
    if not args.yes:
        print(f"Nothing called. Re-run with --yes to synthesize: {synthesis_view.command(project)}")
        return 0
    try:
        result = syn.synthesize(reasoning_client.build_client(), items, hyps, model=model, outcome=outcome,
                                prior=prior)
    except reasoning_client.CoachConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except syn.SynthesisFailure as exc:
        print(f"ERROR: {exc}{note}. Nothing was written; the previous synthesis (if any) is unchanged.",
              file=sys.stderr)
        return 1
    try:
        store.write(context_dir, result, sessions=sorted({i.session_id for i in items}))
    except OSError as exc:
        # The call is paid for: show its result even when it cannot be kept.
        print(f"ERROR: the synthesis could not be saved ({type(exc).__name__}: {exc}); it is shown below "
              f"but the next run will call again.", file=sys.stderr)
        report(result)
        return 1
    print(f"Synthesis by {model}, just made, saved to context/{store.CACHE_FILENAME}.")
    report(result)
    return 0


def preview(items: "Sequence[syn.ClaimItem]", hyps: "Sequence[syn.HypothesisLine]", model: str, *,
            outcome: syn.OutcomeInput = syn.OutcomeInput(), prior: "Optional[syn.PriorTree]" = None,
            note: str = "") -> "tuple[str, ...]":
    request = syn.assemble_request(items, hyps, model=model, outcome=outcome, prior=prior)
    sessions = len({item.session_id for item in items})
    given = "your outcome" if outcome.given else "no outcome (the model will propose one, marked proposed)"
    previous = (f", and the previous tree's {len(prior.nodes)} node label(s) and structure so it stays stable"
                if prior is not None else "")
    lines = [f"One call to {model}{note} to build the opportunity solution tree: {len(items)} claims from "
             f"{sessions} interview(s) (claim text, interview id, hypothesis bearings and an alias each), "
             f"{len(hyps)} hypothesis statement(s) with their kind and parent, {given}{previous}. "
             f"Never a quote and never a transcript. "
             f"~{syn.estimate_input_tokens(request):,} input tokens, plus up to {syn.DEFAULT_MAX_TOKENS:,} "
             f"output tokens ({token_estimate.BASIS}).",
             f"For example ({min(EXAMPLES_SHOWN, len(items))} of {len(items)} claims):"]
    for item in items[:EXAMPLES_SHOWN]:
        bears = ", ".join(f"{s} {h}" for h, s in item.bearings) or "no hypothesis"
        lines.append(f"  [{item.session_id}] {item.claim} ({bears})")
    return tuple(lines)
