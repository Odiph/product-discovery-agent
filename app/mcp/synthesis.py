"""`get_synthesis`: the cached opportunity solution tree, over MCP. Read-only
and free: it serves `context/synthesis.json` when it is fresh for the
project's current claims, hypotheses and outcome, and says how to produce it
otherwise. It never calls a model.

What crosses is what `get_themes` already sends: abstracted claims with
their fact and interview ids, plus the model's node statements, next stories
and assumptions, and statuses and per-interview counts computed by code
(`app/coach/synthesis_view.py`). Never a quote, never a transcript.

`tree_overview` is the same tree for `get_tree`: labels, statuses and
counts, and no claim text at all, as `get_tree` has always been.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from app import project_meta
from app.coach import synthesis_view

DESCRIPTION = (
    "The opportunity solution tree for one project (Teresa Torres's method), as last built by `python -m app "
    "synthesize --yes` (one paid model pass over every extracted claim). 'outcome' is the root: the "
    "operator's, or the model's proposal ('proposed': true). 'tree' holds opportunities (customer needs, "
    "nested through 'children') with 'solutions' under them and 'assumptions' under each solution. Every "
    "status is computed by code from the cited claims in DISTINCT INTERVIEWS, never the model's: an "
    "opportunity is 'heard in N of M interviews', a 'single story' (1), 'recurring' (2) or 'established' "
    "(3+), and 'well_met_for_some' when a claim says something already meets the need; a solution has an "
    "interview 'signal' (leaning for, leaning against, mixed, thin), never a test result; every assumption "
    "is 'untested'. Each node carries its claims grouped by interview, the hypothesis it maps (if any), a "
    "'next_story' to ask for, and 'warnings' (flagged, never dropped; the tree-level ones include a note "
    "while no target opportunity is chosen). 'unplaced_hypotheses' are the operator's hypotheses the tree "
    "does not place (not a need or a solution, or not matched), each with its standing over every "
    "interview (supporting, contrary, unclear and total interviews), so unplaced never means no evidence; "
    "'opinions' are praise and opinions, heard, not evidence; 'diff' is "
    "the change against the previous tree; 'drops' is what the checks removed from the model's answer. "
    "Claims are "
    "abstracted, never quotes. 'status' is fresh, absent, stale, unreadable, no-claims or corpus-unreadable; "
    "a fresh payload also carries 'key' and 'built_from' (the interviews it was built from); "
    "any other status carries a 'how_to' command and no current tree. A stale cache additionally "
    "carries 'last_tree', the previous tree over the claims that still exist: it is OUT OF DATE, never "
    "the current tree. With it come 'last_tree_dropped' (cited claims that are gone), "
    "'last_tree_removed_nodes' (nodes left with no evidence and removed), 'new_sessions' (interviews "
    "since it was built; null when unknown), 'agent_command' and 'agent_prompt' (what to ask an agent "
    "to rebuild it). Mock projects carry 'mock_label'. "
    "Read-only: this tool never calls a model."
)


def get(node, refs: Sequence[Any], hypotheses: Sequence[Any], *, unreadable: bool) -> "dict[str, Any]":
    """`refs` and `hypotheses` as `tools.py`'s loaders return them, for this node."""
    payload = synthesis_view.cached(Path(node.context_dir), project=node.path, refs=refs, hypotheses=hypotheses,
                                    unreadable=unreadable)
    mock = project_meta.is_demo_node(Path(node.context_dir).parent)
    return {"project": node.path, "mock_label": project_meta.MOCK_LABEL if mock else None, **payload}


_SKIPPED = frozenset({"claims_by_interview", "children", "solutions"})


def _node(node: Mapping) -> dict:
    shown = {key: value for key, value in node.items() if key not in _SKIPPED}
    shown["claims"] = sum(len(group["facts"]) for group in node["claims_by_interview"])
    if "children" in node:
        shown["children"] = [_node(child) for child in node["children"]]
        shown["solutions"] = [_node(solution) for solution in node["solutions"]]
    return shown


def tree_overview(node, refs: Sequence[Any], hypotheses: Sequence[Any], *,
                  unreadable: bool) -> "Optional[dict[str, Any]]":
    """The fresh synthesized tree with no claim text, or None when there is none."""
    payload = synthesis_view.cached(Path(node.context_dir), project=node.path, refs=refs, hypotheses=hypotheses,
                                    unreadable=unreadable)
    if payload["status"] != "fresh":
        return None
    return {"model": payload["model"], "total_interviews": payload["total_interviews"],
            "outcome": payload["outcome"], "tree": [_node(n) for n in payload["tree"]],
            "unplaced_hypotheses": payload["unplaced_hypotheses"], "opinions": len(payload["opinions"]),
            "warnings": payload["warnings"], "diff": payload["diff"], "threshold_note": payload["threshold_note"]}
