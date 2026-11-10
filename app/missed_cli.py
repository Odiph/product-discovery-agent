"""`python -m app missed --project <node>`: the topics interviewees kept
raising, and in how many of those interviews you followed up.

No model call by default. Reads the extracted claims (never the quotes) and
the transcripts; prints the topic's label, counts and seq numbers -- never
what anyone said. `--group model --yes` makes the one call that groups the
claims by meaning and writes `context/topics.json` (`grouping_cli`); nothing
else is ever written.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from app import config as config_mod
from app import grouping_cli
from app.coach import missed as missed_mod
from app.coach import missed_load
from app.coach.corpus import CorpusValidationError


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    missed = subparsers.add_parser(
        "missed",
        help=f"Topics interviewees raised in {missed_mod.MIN_INTERVIEWS} or more interviews, and in how "
             f"many you followed up (no model call unless --group model --yes)",
    )
    add_project_argument(missed)
    grouping_cli.add_arguments(missed, command="missed")


def run(args: argparse.Namespace, apply_project) -> int:
    from benchmark.console import use_utf8_console

    use_utf8_console()
    cfg = apply_project(config_mod.load_config(), args)
    try:
        claims = missed_load.read_claims(cfg.context_dir)
        resolution = grouping_cli.resolve(cfg.context_dir, claims, mode=args.group, yes=args.yes)
        grouping_cli.describe(resolution)
        if resolution.exit_code is not None:
            return resolution.exit_code
        report = missed_load.load(cfg.context_dir, cfg.sessions_root, groups=resolution.groups, claims=claims)
    except CorpusValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print_report(report)
    return 0


def print_report(report: missed_mod.Report, *, indent: str = "", details: bool = True) -> None:
    state = report.state
    if state == missed_mod.STATE_NO_EXTRACTION:
        print(f"{indent}No extracted interviews yet: run `python -m app extract <session>` first.")
        return
    if state == missed_mod.STATE_ONLY_ASKED:
        print(f"{indent}No topic comes up unprompted in {missed_mod.MIN_INTERVIEWS} or more of the "
              f"{report.interviews} extracted interview(s) yet.")
        _print_asked(report, indent)
        return
    if state == missed_mod.STATE_NO_TOPIC:
        print(f"{indent}No topic comes up in {missed_mod.MIN_INTERVIEWS} or more of the "
              f"{report.interviews} extracted interview(s) yet.")
        return
    if state == missed_mod.STATE_NOTHING_JUDGED:
        print(f"{indent}{len(report.topics)} topic(s) recur, but no interview has an interviewer turn after "
              f"them that could be judged (no transcript, unconfirmed speakers, or no interviewer turn).")
        details = True
    for topic in report.topics:
        if state == missed_mod.STATE_RESULT:
            print(indent + headline(topic, report.interviews))
        else:
            print(f"{indent}{_label(topic)}:")
        if details:
            for occurrence in topic.occurrences:
                asked = " (right after you asked about it; not counted)" if occurrence.prompted else ""
                print(f"{indent}  {occurrence.session_id} seq {occurrence.seq}: {occurrence.outcome}{asked}")
    _print_asked(report, indent)


def _print_asked(report: missed_mod.Report, indent: str) -> None:
    """Counts only. What interviewees said because the guide asked is not a
    missed aside, but leaving it out would make a topic vanish unexplained."""
    if not report.asked_topics:
        return
    print(f"{indent}Raised when you asked (unprompted in fewer than {missed_mod.MIN_INTERVIEWS} interviews):")
    for topic in report.asked_topics:
        print(f"{indent}  {_label(topic)}: in {topic.raised_interviews} interviews, "
              f"unprompted in {topic.tally.raised_interviews}")


def headline(topic: missed_mod.Topic, interviews: int) -> str:
    tally = topic.tally
    unjudged = tally.raised_interviews - tally.judged_interviews
    tail = f" ({unjudged} could not be judged)" if unjudged else ""
    return (f"In {tally.raised_interviews} of {interviews} interviews, interviewees raised {_label(topic)} "
            f"without being asked. "
            f"You followed up in {tally.followed_interviews}.{tail}")


def _label(topic: missed_mod.Topic) -> str:
    return ", ".join(topic.label) or "(no shared words)"
