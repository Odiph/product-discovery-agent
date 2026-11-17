"""The synthesized opportunity solution tree, printed: `synthesize` prints it
with each node's claims, `tree` without them. Reads only the projection
(`app/coach/synthesis_view.py`), so every status and count is the code's.

Outcome first, then the tree indented (opportunities, their children, their
solutions, each solution's assumptions), then the hypotheses the tree does
not place, each with its standing in interviews, the opinions footnote, the
warnings, the changes since the previous tree and what the checks dropped.
"""

from __future__ import annotations

from typing import Mapping, Sequence

STEP = "    "
UNPLACED_HEADING = "Your hypotheses the tree does not place (not a need or a solution, or not matched)"


def _outcome(shown: Mapping, set_it: str) -> None:
    outcome = shown["outcome"]
    if outcome["proposed"]:
        text = outcome["text"] or "(none proposed)"
        print(f"OUTCOME (proposed by the model, not yours): {text}")
        print(f"{STEP}Set your own outcome in `{set_it}`; the next synthesis keeps it.")
    else:
        print(f"OUTCOME: {outcome['text']}")


def _claims(node: Mapping, indent: str) -> None:
    for group in node["claims_by_interview"]:
        for fact in group["facts"]:
            print(f"{indent}[{group['session_id']}] {fact['claim']} ({fact['bearing'].replace('_', ' ')})")


def _common(node: Mapping, indent: str, *, claims: bool) -> None:
    hypothesis = node["hypothesis"]
    if hypothesis:
        print(f"{indent}maps your hypothesis {hypothesis['hypothesis_id']}: {hypothesis['statement']}")
    if node.get("reframed_from"):
        print(f"{indent}reframed from: {node['reframed_from']}")
    if node["next_story"]:
        print(f"{indent}next story to ask for: {node['next_story']}")
    for warning in node["warnings"]:
        print(f"{indent}! {warning['message']}")
    if claims:
        _claims(node, indent + "  ")


def _assumption(assumption: Mapping, indent: str) -> None:
    leap = "; leap of faith" if assumption["leap_of_faith"] else ""
    print(f"{indent}assumption [{assumption['type']}, {assumption['importance']} importance, "
          f"{assumption['status']}]: {assumption['text']} (evidence in {assumption['evidence_interviews']} "
          f"interview(s){leap})")


def _solution(node: Mapping, indent: str, *, claims: bool) -> None:
    print(f"{indent}SOLUTION [{node['id']}] {node['statement']} (origin: {node['origin']})")
    inner = indent + STEP
    print(f"{inner}interview signal: {node['signal']} (for in {node['for_interviews']}, against in "
          f"{node['against_interviews']}; {node['touching_interviews']} interview(s) touch it)")
    _common(node, inner, claims=claims)
    for assumption in node["assumptions"]:
        _assumption(assumption, inner)


def _opportunity(node: Mapping, indent: str, *, claims: bool) -> None:
    print(f"{indent}OPPORTUNITY [{node['id']}] {node['statement']}")
    inner = indent + STEP
    met = (f"; well met for some (in {node['well_met_interviews']})" if node["well_met_for_some"] else "")
    absent = (f"; {node['not_experienced_interviews']} said they do not have it"
              if node["not_experienced_interviews"] else "")
    print(f"{inner}{node['status']}: {node['heard']}{met}{absent}")
    _common(node, inner, claims=claims)
    for child in node["children"]:
        _opportunity(child, inner, claims=claims)
    for solution in node["solutions"]:
        _solution(solution, inner, claims=claims)


def _diff(diff: Mapping) -> None:
    if not any(diff[part] for part in diff):
        print("No change to the tree's structure since the previous synthesis.")
        return
    print("Changes since the previous tree:")
    for entry in diff["added"]:
        print(f"  added {entry['kind']} [{entry['id']}] {entry['statement']}")
    for entry in diff["removed"]:
        print(f"  removed {entry['kind']} [{entry['id']}] {entry['statement']}")
    for entry in diff["moved"]:
        print(f"  moved {entry['kind']} [{entry['id']}] {entry['statement']}: from {entry['before']} "
              f"to {entry['after']}")
    for entry in diff["renamed"]:
        print(f"  renamed {entry['kind']} [{entry['id']}] from \"{entry['before']}\" to \"{entry['statement']}\"")


def _footer(shown: Mapping, *, claims: bool) -> None:
    if shown["unplaced_hypotheses"]:
        print(f"{UNPLACED_HEADING}:")
        for h in shown["unplaced_hypotheses"]:
            print(f"  {h['hypothesis_id']}{' (' + h['kind'] + ')' if h['kind'] else ''}: {h['statement']} "
                  f"(for in {h['supporting_interviews']}, against in {h['contrary_interviews']}, unclear in "
                  f"{h['unclear_interviews']} interview(s))")
        print()
    if shown["opinions"] and claims:
        print("Heard, not evidence (opinions and praise, never nodes):")
        for fact in shown["opinions"]:
            print(f"  [{fact['session_id']}] {fact['claim']}")
        print()
    elif shown["opinions"]:
        sessions = len({fact["session_id"] for fact in shown["opinions"]})
        print(f"Heard, not evidence: {len(shown['opinions'])} opinion or praise claim(s) from {sessions} "
              "interview(s), never nodes (`synthesize` lists them).\n")
    if shown["warnings"]:
        print("Warnings about the whole tree:")
        for warning in shown["warnings"]:
            print(f"  ! {warning['message']}")
        print()


def print_tree(shown: Mapping, *, set_outcome: str, claims: bool = True) -> None:
    _outcome(shown, set_outcome)
    nodes = [node for node in _all(shown["tree"])]
    solutions = sum(len(node["solutions"]) for node in nodes)
    print(f"{len(nodes)} opportunit{'y' if len(nodes) == 1 else 'ies'} and {solutions} solution(s), from "
          f"{shown['total_interviews']} interview(s). Counts are INTERVIEWS, not claims.\n")
    if not shown["tree"]:
        print("  No opportunity survived the checks.\n")
    for node in shown["tree"]:
        _opportunity(node, "  ", claims=claims)
        print()
    _footer(shown, claims=claims)
    if shown["diff"] is not None:
        _diff(shown["diff"])
        print()
    lines = shown["drops"]["lines"]
    if lines:
        print(f"Dropped from the model's answer by the checks: {'; '.join(lines)}.\n")
    print(shown["threshold_note"])


def _all(tree: "Sequence[Mapping]") -> "list[Mapping]":
    found: "list[Mapping]" = []
    for node in tree:
        found.append(node)
        found.extend(_all(node["children"]))
    return found
