"""`python -m app prep --project <node>`: what to change before the next
interview, each change with its reason. Reads only; calls no model; writes
nothing (change the guide in `python -m app author`, which offers the same
survey proposals to apply; `app/coach/prep_load.py` is shared by both).
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from app import config as config_mod
from app import missed_cli
from app.coach import mirror_load
from app.coach import missed as missed_mod
from app.coach import interview_summary as summary_mod
from app.coach import prep as prep_mod
from app.coach import prep_load
from app.coach.context import ContextValidationError, load_survey
from app.coach.corpus import CorpusValidationError
from app.mirror_cli import FLAG_LABELS


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    prep = subparsers.add_parser(
        "prep",
        help="Before the next interview: which hypotheses still have no answer, which questions were "
             "never reached, and which habits to avoid -- each with its reason (no model call, writes nothing)",
    )
    add_project_argument(prep)


def run(args: argparse.Namespace, apply_project, read_corpus_refs) -> int:
    from benchmark.console import use_utf8_console

    use_utf8_console()
    cfg = apply_project(config_mod.load_config(), args)
    label = getattr(args, "project", None) or ""
    try:
        hypotheses, refs, _ = read_corpus_refs(cfg, project_label=label)
    except CorpusValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        survey = load_survey(cfg.context_dir)
    except ContextValidationError:
        survey = ()

    reading = prep_load.model_reading(cfg.context_dir, cfg.sessions_root, survey)
    guides, asked_in, unconfirmed, untracked, reconstructed = prep_load.interviews_and_coverage(
        cfg.sessions_root, survey=survey, reading=reading.asked)
    read_by_model = [s for s in reconstructed if s in (reading.asked or {})]
    interviews = list(guides)
    extracted = {ref.session_id for ref in refs}
    mirror = mirror_load.load(cfg.sessions_root)
    try:
        raised = missed_cli.cached_report(cfg.context_dir, cfg.sessions_root)
    except CorpusValidationError:
        raised = None  # `missed` reports the error; prep still has the rest to say
    plan = prep_mod.build(
        survey=survey,
        asked_in=asked_in,
        guides=guides,
        standings=[summary_mod.standing(h, refs, project=label) for h in hypotheses],
        habits=mirror.habits,
        walked_past_signals=[signal for row in mirror.sessions for m in row.walked_past for signal in m.signals],
        unextracted=[s for s in interviews if s not in extracted and s not in unconfirmed],
        flag_labels=FLAG_LABELS,
        untracked=untracked,
        reconstructed=reconstructed,
        read_by_model=read_by_model,
        raised_from=raised.report.topics if raised is not None else (),
        extracted_interviews=raised.report.interviews if raised is not None else 0,
    )
    _print(plan, has_hypotheses=bool(hypotheses), has_survey=bool(survey),
           known=_already_known(plan.gaps, cfg.context_dir.parent), raised=raised)
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
        print(f"\n{len(unconfirmed)} in-person interview(s) wait for confirmed speakers before they can be "
              f"extracted: python -m app diarize-after <session>, then confirm-speakers  ({', '.join(unconfirmed)})")
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


def _print(plan: prep_mod.Prep, *, has_hypotheses: bool, has_survey: bool, known=None, raised=None) -> None:
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

    print("\nNothing was changed. Edit the guide in `python -m app author`. New questions for the gaps are "
          "yours to word: this command does not call a model.")
