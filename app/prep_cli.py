"""`python -m app prep --project <node>`: what to change before the next
interview, each change with its reason. Reads only; calls no model; writes
nothing (change the guide in `python -m app author`, which offers the same
survey proposals to apply; `app/coach/prep_load.py` is shared by both).

`--draft [--yes]` (`app/prep_draft_cli.py`) adds new questions for the gaps,
worded by the model in one cached call; without `--draft` this command's
output is byte-identical to what it printed before the flag existed.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from pathlib import Path

from app import config as config_mod
from app import prep_draft_cli, prep_gather, project_meta
from app.coach import missed as missed_mod
from app.coach import prep as prep_mod
from app.coach import prep_draft as draft_mod
from app.coach.corpus import CorpusValidationError


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    prep = subparsers.add_parser(
        "prep",
        help="Before the next interview: which hypotheses still have no answer, the holes in the "
             "opportunity tree, which questions were never reached, and which habits to avoid -- each with its reason (no model call, writes nothing; "
             "--draft words new questions for the gaps)",
    )
    add_project_argument(prep)
    prep.add_argument("--draft", action="store_true",
                      help="also draft up to two Mom Test questions per gap (one paid call with --yes, cached "
                           "in context/prep_draft.json); without --yes, only show what would be sent")
    prep.add_argument("--yes", action="store_true", help="with --draft: make the call")


def run(args: argparse.Namespace, apply_project, read_corpus_refs) -> int:
    from benchmark.console import use_utf8_console

    use_utf8_console()
    drafting = bool(getattr(args, "draft", False))
    if getattr(args, "yes", False) and not drafting:
        print("ERROR: --yes needs --draft: plain prep never calls a model.", file=sys.stderr)
        return 2
    cfg = apply_project(config_mod.load_config(), args)
    label = getattr(args, "project", None) or ""
    try:
        hypotheses, refs, _ = read_corpus_refs(cfg, project_label=label)
    except CorpusValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    gathered = prep_gather.gather(cfg.context_dir, cfg.sessions_root, hypotheses, refs, label=label)
    plan, survey, raised = gathered.plan, gathered.survey, gathered.raised
    reading, reconstructed, read_by_model = gathered.reading, gathered.reconstructed, gathered.read_by_model
    unconfirmed = gathered.unconfirmed
    resolution = None
    if drafting:
        if project_meta.is_demo_node(Path(cfg.context_dir).parent):
            print(project_meta.MOCK_LABEL)
        resolution = prep_draft_cli.resolve(cfg.context_dir, prep_draft_cli.inputs_for(cfg.context_dir, gathered),
                                            yes=args.yes)
        if resolution.error:
            print(f"ERROR: {resolution.error}", file=sys.stderr)
            return 1
    _print(plan, has_hypotheses=bool(hypotheses), has_survey=bool(survey),
           known=_already_known(plan.gaps, cfg.context_dir.parent), raised=raised,
           drafts=resolution.draft if resolution else None, drafting=drafting)
    by_words = len(reconstructed) - len(read_by_model)
    if read_by_model and survey:
        print(f"\n{len(read_by_model)} interview(s) had no live coverage record (imported, or the coach was "
              f"off): which questions they asked is from the model's reading of the transcript "
              f"(context/coverage.json, made by `python -m app coverage`; prep itself calls no model).")
    if by_words and survey:
        print(f"\n{by_words} interview(s) had no live coverage record (imported, or the coach was "
              f"off), so which questions they asked was reconstructed: this matches each of your turns "
              f"against the guide's wording, and misses a question you asked in other words. "
              f"`python -m app coverage` has the model read them instead.")
    if reading.note:
        print(f"\n{reading.note}")
    if unconfirmed:
        # `extract` refuses these until their speakers are confirmed, so they
        # must not be in the "run extract" line above.
        print(f"\n{len(unconfirmed)} interview(s) on one recording (in-person, or imported as audio) wait for confirmed speakers before they can be "
              f"extracted: python -m app diarize-after <session>, then confirm-speakers  ({', '.join(unconfirmed)})")
    if resolution is not None and resolution.notes:
        print()
        for line in resolution.notes:
            print(line)
    return 0


def _already_known(gaps, node_dir) -> "dict[str, list]":
    """For each gap, where the knowledge base (`kb`) already talks about it --
    an email, a research note, the code, another recorded conversation --
    so the next interview does not spend a question on what is on file.
    Interviews are left out: they are what `standing` already counts. A hit
    must share `MIN_KNOWN_WORDS` content words with the hypothesis (all of
    them, for a shorter statement, and never fewer than two), or one common
    word would tie every gap to everything."""
    from app.kb import index as kb_index
    from app.kb import terms
    from app.kb.document import INTERVIEW, SOURCE_TYPES
    from app.kb.store import KnowledgeStore

    stored, _ = KnowledgeStore.for_node(node_dir).scan()
    if not stored or not gaps:
        return {}
    index = kb_index.KeywordIndex(item.document for item in stored)
    others = [t for t in SOURCE_TYPES if t != INTERVIEW]
    known: "dict[str, list]" = {}
    for gap in gaps:
        wanted = [set(terms.forms(w)) for w in terms.words(gap.statement) if terms.is_topic_word(w)]
        need = max(2, min(MIN_KNOWN_WORDS, len(wanted)))
        if len(wanted) < need:
            continue
        hits = []
        for hit in index.search(gap.statement, limit=KNOWN_PER_GAP * 3, per_document=1, source_types=others):
            present = set(terms.index_terms(hit.snippet))
            if sum(1 for forms in wanted if forms & present) >= need:
                hits.append(hit)
            if len(hits) >= KNOWN_PER_GAP:
                break
        if hits:
            known[gap.hypothesis_id] = hits
    return known


KNOWN_PER_GAP = 2
MIN_KNOWN_WORDS = 3


def _print(plan: prep_mod.Prep, *, has_hypotheses: bool, has_survey: bool, known=None, raised=None,
           drafts=None, drafting: bool = False) -> None:
    print(f"Prep for the next interview -- from {plan.interviews} interview(s) so far.\n")
    if plan.unextracted:
        print(f"! {len(plan.unextracted)} interview(s) not extracted yet, so the hypothesis gaps below "
              f"leave them out: python -m app extract <session>  ({', '.join(plan.unextracted)})\n")

    print("What you still don't know:")
    if not has_hypotheses:
        print("  No hypotheses yet: write some in `python -m app author`, or nothing can be a gap.")
    elif not plan.gaps:
        print("  Every hypothesis has a criterion and evidence from several interviews.")
    for gap in plan.gaps:
        print(f"  [{gap.kind}] {gap.hypothesis_id}: {gap.statement}")
        print(f"      {gap.reason}")
        for hit in (known or {}).get(gap.hypothesis_id, ()):
            print(f"      on file: [{hit.source_type}] {hit.title} -- {hit.location}  ({hit.doc_id})")
        for question in drafts.for_gap(gap.hypothesis_id) if drafts is not None else ():
            if draft_mod.in_survey(question.text, (item.text for item in plan.items)):
                continue
            print(f"      ask: {question.text}")
            print(f"        why: {question.why}")

    _print_tree(plan.tree)

    print("\nThe guide:")
    if not has_survey:
        print("  No survey yet: write one in `python -m app author`.")
    for item in plan.items:
        marker = ">" if item.action == prep_mod.MOVE_EARLIER else " "
        print(f" {marker} {item.order + 1:>2}. {item.text}")
        print(f"       {item.action}: {item.reason}")

    if raised is not None and raised.report.interviews:
        print("\nWhat they keep raising that you did not ask about:")
        print(f"  {raised.grouping}")
        print(f"  {raised.prompted}")
        print(f"  {raised.followed}")
        if not plan.raised:
            print(f"  Nothing: no topic came up unprompted in {missed_mod.MIN_INTERVIEWS} or more "
                  f"interviews and was walked past more often than followed up.")
        for topic in plan.raised:
            print(f"  > {topic.label}")
            print(f"      {topic.reason}")
        if plan.raised:
            print("  Add a question in `python -m app author`; per interview: `python -m app missed`.")

    if plan.avoid or plan.follow:
        print("\nYou, last time and before:")
        for line in plan.avoid:
            print(f"  avoid {line}")
        for line in plan.follow:
            print(f"  {line}")

    if drafting:
        print("\nNothing was changed in the guide. Edit it in `python -m app author`, which offers each drafted "
              "question with Add to survey; nothing is saved until you press Save survey.")
        return
    print("\nNothing was changed. Edit the guide in `python -m app author`. New questions for the gaps are "
          "yours to word: this command does not call a model.")


def _print_tree(tree) -> None:
    """The opportunity tree's holes, each with the tree's own next-story question."""
    if not tree.holes and not tree.note:
        return
    print("\nHoles in your opportunity tree:")
    if tree.note:
        print(f"  {tree.note}")
    for hole in tree.holes:
        print(f"  [{hole.status}] {hole.node_id} ({hole.kind}): {hole.statement}")
        print(f"      {hole.reason}")
        if hole.ask:
            print(f"      ask: {hole.ask}")
    if tree.more:
        print(f"  ...and {tree.more} more: see the tree in the hub (`python -m app hub`).")
