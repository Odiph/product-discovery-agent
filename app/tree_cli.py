"""`python -m app tree --project <node>`: the Opportunity Solution Tree for
one node, rendered from what is already on disk. No model call; reads
claims and labels only (never the quotes); writes nothing.

When a FRESH synthesis exists (`synthesize --yes`, cached in
`context/synthesis.json`), the tree shown is the synthesized one
(`app/synthesis_report.py`), followed by the operator's own classifications
(hypothesis kind and parent, `app/coach/ost.py`), marked as such. Otherwise
the operator's tree as before, with the word-group "candidate opportunities"
beside it: those are shown only when there is no synthesis.

The counts move by themselves after every `extract`, because they are read
fresh each run. The operator's STRUCTURE moves only when hypotheses are saved
on the author page -- this command says where, and never does it itself.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from app import config as config_mod
from app.coach import ost as ost_mod
from app.coach import synthesis_view
from app.coach.corpus import CorpusValidationError
from app.synthesis_report import print_tree


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    tree = subparsers.add_parser(
        "tree",
        help="The project's Opportunity Solution Tree: the synthesized one when `synthesize` has made one "
             "for the current claims, then your own classifications; otherwise your classifications with "
             "recurring themes not yet in them (no model call)",
    )
    add_project_argument(tree)


def _author_command(project: str) -> str:
    return "python -m app author" + (f" --project {project}" if project else "")


def _evidence(node: "ost_mod.TreeNode") -> str:
    # The same three numbers `standing` prints, in words: these are INTERVIEW
    # counts, and a row of bare integers invites reading them as claims.
    return (
        f"{node.state}; supports in {node.supporting_interviews}, contradicts in "
        f"{node.contrary_interviews}, unclear in {node.unclear_interviews} "
        f"(touched by {node.total_interviews} interview(s))"
    )


def _print_node(node: "ost_mod.TreeNode", indent: str) -> None:
    print(f"{indent}[{node.hypothesis_id}] {node.statement}")
    print(f"{' ' * len(indent)}    {_evidence(node)}")


def _outcome(tree: "ost_mod.Tree", author: str) -> None:
    if tree.outcome.is_set:
        print(f"OUTCOME: {tree.outcome.text}")
    elif tree.outcome.state == ost_mod.OUTCOME_UNREADABLE:
        print(f"OUTCOME: context/{ost_mod.OUTCOME_FILENAME} exists but could not be read -- repair it, "
              "or set the outcome again in the author page.")
    else:
        print(f"OUTCOME: not set -- write the outcome this work serves in `{author}`.")


def _classified(tree: "ost_mod.Tree", author: str) -> None:
    if tree.status == ost_mod.STATUS_NO_HYPOTHESES:
        print("  No hypotheses yet, so there is no tree to draw.")
        print(f"  Write opportunities and solutions in `{author}`.")
        return
    if tree.status == ost_mod.STATUS_NOT_EXTRACTED:
        print("  Nothing extracted yet: every count below is zero because no interview has been "
              "read, not because none bore on it. Run `python -m app extract <session>`.")
    else:
        print(f"  Evidence from {tree.extracted_interviews} extracted interview(s). Counts are "
              "INTERVIEWS, not claims, exactly as `standing` counts them.")
    print()
    if not tree.opportunities:
        print("  No opportunities classified yet.")
    for opportunity in tree.opportunities:
        _print_node(opportunity, "  OPPORTUNITY ")
        for solution in opportunity.children:
            _print_node(solution, "      SOLUTION ")
        if not opportunity.children:
            print("      (no solutions under this opportunity yet)")
    if tree.unclassified:
        print()
        print("  Unclassified (no kind yet, or a solution with no valid opportunity):")
        for node in tree.unclassified:
            _print_node(node, "    ")
    if tree.problems:
        print()
        print("  Problems the author page will refuse to save until fixed:")
        for problem in tree.problems:
            print(f"    - {problem}")


def _candidates(tree: "ost_mod.Tree", project: str, author: str) -> None:
    print()
    print("Candidate opportunities (not in the tree):")
    if not tree.corpus_exists:
        print("  None yet -- themes come from extracted claims.")
        return
    if not tree.candidates:
        print("  No claim outside every hypothesis recurs across two interviews yet.")
    for number, candidate in enumerate(tree.candidates, start=1):
        label = ", ".join(candidate.label) or "(no shared words)"
        print(f"  {number}. {label} -- in {candidate.interviews} interviews, {len(candidate.claims)} claims")
    if tree.candidates:
        print(f"  Promote one: `{author}` -> Candidate opportunities -> Promote, then write its "
              "statement and falsifier yourself and Save hypotheses. Its claims: `python -m app themes"
              + (f" --project {project}`." if project else "`."))
    print(f"  Or build the tree from every claim in one model call: `{synthesis_view.command(project)}`.")


def render(tree: "ost_mod.Tree", *, project: str, synthesized: "dict | None" = None) -> None:
    author = _author_command(project)
    print(f"Opportunity solution tree -- {project or 'the root context/ and sessions/'}")
    if synthesized is not None:
        print(f"Synthesized from the claims by {synthesized['model']} (`synthesize`); every status is computed "
              "from the cited claims.")
        print_tree(synthesized, set_outcome=author, claims=False)
        print()
        print("YOUR CLASSIFICATIONS (operator: hypothesis kind and parent, from the author page):")
        _classified(tree, author)
        return
    _outcome(tree, author)
    _classified(tree, author)
    _candidates(tree, project, author)


def run(args: argparse.Namespace, apply_project, read_corpus_refs) -> int:
    from benchmark.console import use_utf8_console

    use_utf8_console()
    cfg = apply_project(config_mod.load_config(), args)
    project = getattr(args, "project", None) or ""
    try:
        hypotheses, refs, corpus_exists = read_corpus_refs(cfg, project_label=project)
    except CorpusValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    tree = ost_mod.build_tree(
        hypotheses, refs, outcome=ost_mod.read_outcome(cfg.context_dir),
        corpus_exists=corpus_exists, project=project,
    )
    cached = synthesis_view.cached(Path(cfg.context_dir), project=project, refs=refs, hypotheses=hypotheses)
    render(tree, project=project, synthesized=cached if cached["status"] == "fresh" else None)
    return 0
