"""Everything `prep` reads to build its plan, in one place, so the command
and the `author` page's draft panel (`prep_draft_cli.panel`) build the SAME
gaps and so key the same question draft. Reads only; calls no model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app import missed_cli
from app.coach import interview_summary as summary_mod
from app.coach import mirror_load
from app.coach import prep as prep_mod
from app.coach import prep_load
from app.coach import prep_tree
from app.coach.context import ContextValidationError, load_survey
from app.coach.corpus import CorpusValidationError
from app.mirror_cli import FLAG_LABELS


@dataclass(frozen=True)
class Gathered:
    plan: prep_mod.Prep
    survey: "tuple"
    hypotheses: "tuple"
    habits: "tuple"
    reading: prep_load.Reading
    reconstructed: "tuple[str, ...]"
    read_by_model: "tuple[str, ...]"
    unconfirmed: "tuple[str, ...]"
    raised: Any
    """`missed_cli.Cached`, or None when its corpus would not load."""


def read_survey(context_dir: Path) -> "tuple":
    try:
        return load_survey(context_dir)
    except ContextValidationError:
        return ()


def read_corpus(context_dir: Path, *, project_label: str = "") -> "tuple[tuple, tuple]":
    """(hypotheses, quote-free fact refs) through the SAME reader the `prep`
    command is handed (`app.main._read_corpus_refs`), so the page and the
    command cannot key the draft differently. Lazy: `app.main` imports the
    command modules. Raises `CorpusValidationError`."""
    from app.main import _read_corpus_refs

    hypotheses, refs, _ = _read_corpus_refs(SimpleNamespace(context_dir=Path(context_dir)),
                                            project_label=project_label)
    return tuple(hypotheses), tuple(refs)


def gather(context_dir: Path, sessions_root: Path, hypotheses, refs, *, label: str = "") -> Gathered:
    survey = read_survey(context_dir)
    reading = prep_load.model_reading(context_dir, sessions_root, survey)
    guides, asked_in, unconfirmed, untracked, reconstructed = prep_load.interviews_and_coverage(
        sessions_root, survey=survey, reading=reading.asked)
    read_by_model = [s for s in reconstructed if s in (reading.asked or {})]
    extracted = {ref.session_id for ref in refs}
    mirror = mirror_load.load(sessions_root)
    try:
        raised = missed_cli.cached_report(context_dir, sessions_root)
    except CorpusValidationError:
        raised = None  # `missed` reports the error; prep still has the rest to say
    plan = prep_mod.build(
        survey=survey,
        asked_in=asked_in,
        guides=guides,
        standings=[summary_mod.standing(h, refs, project=label) for h in hypotheses],
        habits=mirror.habits,
        walked_past_signals=[signal for row in mirror.sessions for m in row.walked_past for signal in m.signals],
        unextracted=[s for s in guides if s not in extracted and s not in unconfirmed],
        flag_labels=FLAG_LABELS,
        untracked=untracked,
        reconstructed=reconstructed,
        read_by_model=read_by_model,
        raised_from=raised.report.topics if raised is not None else (),
        extracted_interviews=raised.report.interviews if raised is not None else 0,
        tree=prep_tree.load(context_dir, refs, hypotheses),
    )
    return Gathered(plan=plan, survey=tuple(survey), hypotheses=tuple(hypotheses), habits=tuple(mirror.habits),
                    reading=reading, reconstructed=tuple(reconstructed), read_by_model=tuple(read_by_model),
                    unconfirmed=tuple(unconfirmed), raised=raised)
