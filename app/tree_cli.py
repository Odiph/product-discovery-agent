"""`python -m app tree --project <node>`: the Opportunity Solution Tree for
one node, rendered from what is already on disk (`app/coach/ost.py`). No
model call; reads claims and labels only (never the quotes); writes nothing.

The counts move by themselves after every `extract`, because they are read
fresh each run. The STRUCTURE moves only when the operator saves hypotheses on
the author page -- this command says where, and never does it itself.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from app import config as config_mod
from app.coach import ost as ost_mod
from app.coach.corpus import CorpusValidationError


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    tree = subparsers.add_parser(
        "tree",
        help="The project's Opportunity Solution Tree: outcome, opportunities, solutions, each "
             "with its per-interview evidence, plus recurring themes not yet in it (no model call)",
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


def render(tree: "ost_mod.Tree", *, project: str) -> None:
    author = _author_command(project)
    print(f"Opportunity solution tree -- {project or 'the root context/ and sessions/'}")
    if tree.outcome.is_set:
        print(f"OUTCOME: {tree.outcome.text}")
    elif tree.outcome.state == ost_mod.OUTCOME_UNREADABLE:
        print(f"OUTCOME: context/{ost_mod.OUTCOME_FILENAME} exists but could not be read -- repair it, "
              "or set the outcome again in the author page.")
    else:
        print(f"OUTCOME: not set -- write the outcome this work serves in `{author}`.")

    if tree.status == ost_mod.STATUS_NO_HYPOTHESES:
        print("  No hypotheses yet, so there is no tree to draw.")
        print(f"  Write opportunities and solutions in `{author}`.")
    else:
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

    print()
    print("Candidate opportunities (not in the tree):")
    if not tree.corpus_exists:
        print("  None yet -- themes come from extracted claims.")
        return
    if not tree.candidates:
        print("  No claim outside every hypothesis recurs across two interviews yet.")
        return
    for number, candidate in enumerate(tree.candidates, start=1):
        label = ", ".join(candidate.label) or "(no shared words)"
        print(f"  {number}. {label} -- in {candidate.interviews} interviews, {len(candidate.claims)} claims")
    print(f"  Promote one: `{author}` -> Candidate opportunities -> Promote, then write its "
          "statement and falsifier yourself and Save hypotheses. Its claims: `python -m app themes"
          + (f" --project {project}`." if project else "`."))


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
    render(tree, project=project)
    return 0
