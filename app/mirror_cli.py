"""`python -m app mirror --project <node>`: what you keep doing as an
interviewer, across every interview in the project.

No model call. It reads the question critiques `critique-questions` already
wrote, and finds walked-past moments from the transcripts themselves. Your
own questions and the interviewee's words are printed only with `--show`,
and only to this terminal.
"""

from __future__ import annotations

import argparse
from typing import Callable, Optional

from app import config as config_mod
from app import missed_cli
from app.coach import mirror as mirror_mod
from app.coach import mirror_load
from app.coach import missed as missed_mod
from app.coach.corpus import CorpusValidationError

FLAG_LABELS = {
    "leading": "leading",
    "hypothetical_or_future_tense": "hypothetical / future",
    "pitch": "pitching",
    "opinion_seeking": "opinion-seeking",
    "confirmation_only": "yes/no confirmation",
    "off_topic": "off-topic",
}
SHOW_CHARS = 160


def add_parser(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    mirror = subparsers.add_parser(
        "mirror",
        help="Your habits as an interviewer across every interview: recurring question flags, "
             "the trend from early to late, and offers you walked past (no model call)",
    )
    mirror.add_argument("--show", action="store_true",
                        help="also print the words of each walked-past moment (this terminal only)")
    add_project_argument(mirror)


def run(args: argparse.Namespace, apply_project) -> int:
    from benchmark.console import use_utf8_console

    use_utf8_console()
    cfg = apply_project(config_mod.load_config(), args)
    report = mirror_load.load(cfg.sessions_root)
    if not report.sessions:
        print("No interviews with speech in this project yet.")
        if report.unreadable:
            print(f"{len(report.unreadable)} session(s) could not be read: {', '.join(report.unreadable)}")
        return 0
    _print_sessions(report)
    _print_habits(report)
    _print_trend(report.trend)
    _print_walked_past(report, cfg.sessions_root if args.show else None)
    _print_missed_topics(cfg)
    if report.unreadable:
        print(f"\n{len(report.unreadable)} session(s) could not be read and are left out: "
              f"{', '.join(report.unreadable)}")
    if report.uncritiqued:
        print(f"\n{len(report.uncritiqued)} interview(s) have no question critique yet, so their questions "
              f"are not in the habits or the trend. `critique-questions --all` judges them "
              f"(calls the reasoning vendor).")
    return 0


def _print_sessions(report: mirror_mod.Mirror) -> None:
    print(f"{'interview':18} {'date':10} {'questions':>9} {'unsure':>6} {'clean':>6}  {'flags':30} "
          f"{'offers':>6} {'walked past':>11}")
    for row in report.sessions:
        if row.critiqued:
            rate = f"{row.clean_rate:.0%}" if row.clean_rate is not None else "-"
            flags = ", ".join(f"{FLAG_LABELS[k]} {n}" for k, n in row.flags.items() if n) or "none"
            judged = str(row.judged)
            unsure = "-" if row.uncertain is None else str(row.uncertain)
        else:
            rate, flags, judged, unsure = "-", "(not critiqued)", "-", "-"
        print(f"{row.session_id:18} {row.date or '-':10} {judged:>9} {unsure:>6} {rate:>6}  {flags[:30]:30} "
              f"{row.offers:>6} {len(row.walked_past):>11}")
    print("clean = clean out of the questions the critic could decide; 'unsure' (mostly follow-ups it "
          "saw without what was said before them) are left out.")


def _print_habits(report: mirror_mod.Mirror) -> None:
    critiqued = sum(1 for s in report.sessions if s.critiqued)
    print("\nHabits (a flag in two or more interviews):")
    if critiqued < mirror_mod.MIN_SESSIONS_FOR_HABIT:
        print(f"  needs at least {mirror_mod.MIN_SESSIONS_FOR_HABIT} critiqued interviews; this project has {critiqued}.")
        return
    if not report.habits:
        print("  none -- no flag recurs across interviews.")
    for habit in report.habits:
        print(f"  {FLAG_LABELS[habit.flag]}: in {habit.sessions} of {critiqued} interviews, {habit.total} questions")


def _print_trend(trend: Optional[mirror_mod.Trend]) -> None:
    print("\nEarlier vs later:")
    if trend is None:
        print(f"  needs at least {mirror_mod.MIN_SESSIONS_FOR_TREND} critiqued interviews.")
        return
    print(f"  clean questions: {trend.earlier_clean_rate:.0%} in the first {trend.earlier_sessions} -> "
          f"{trend.later_clean_rate:.0%} in the last {trend.later_sessions}")
    for flag, label in FLAG_LABELS.items():
        before, after = trend.earlier_flag_rates.get(flag), trend.later_flag_rates.get(flag)
        if before is not None and after is not None and (before or after):
            print(f"  {label}: {before:.0%} -> {after:.0%} of questions")


def _print_walked_past(report: mirror_mod.Mirror, show_from) -> None:
    print(f"\nWalked past: {report.walked_past_total} of {report.offers_total} offers "
          f"(an interviewee turn with a concrete occasion, workaround, cost or pain, "
          f"followed by a question on something else). A detector, not a verdict: look at each.")
    for row in report.sessions:
        if not row.walked_past:
            continue
        texts = mirror_load.turn_texts(show_from / row.session_id) if show_from is not None else {}
        for moment in row.walked_past:
            when = _clock(moment.at_s)
            praised = "  (acknowledged, then moved on)" if moment.acknowledged else ""
            print(f"  {row.session_id} at {when}: {', '.join(moment.signals)}{praised}")
            if texts:
                print(f"      they said: {_clip(texts.get(moment.offer_seqs, ''))}")
                print(f"      you asked: {_clip(texts.get(moment.next_seqs, ''))}")


def _print_missed_topics(cfg) -> None:
    """The `missed` headlines, one per topic: walked-past moments are single
    turns, this is the same failure seen across interviews. Silent when no
    claims are extracted -- the mirror does not need a corpus to work.
    Cached only (`missed_cli.cached_report`): the mirror never calls a model."""
    try:
        cached = missed_cli.cached_report(cfg.context_dir, cfg.sessions_root)
    except CorpusValidationError:
        print("\nTopics they kept raising: the extracted claims could not be read; run `missed` for the error.")
        return
    if cached.report.state == missed_mod.STATE_NO_EXTRACTION:
        return
    print(f"\nTopics they kept raising (in {missed_mod.MIN_INTERVIEWS}+ interviews; per interview: "
          f"`python -m app missed`):")
    print(f"  {cached.grouping}")
    print(f"  {cached.prompted}")
    missed_cli.print_report(cached.report, indent="  ", details=False)


def _clip(text: str) -> str:
    return text if len(text) <= SHOW_CHARS else text[:SHOW_CHARS].rsplit(" ", 1)[0] + " …"


def _clock(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes:02d}:{rest:02d}"

