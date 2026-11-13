"""`python -m app extract --all [--yes] [--force]`: every interview in a node
that has not been extracted yet, each through the SAME single-session path
`extract <session>` runs (passed in from `app/main.py`), so `--all` cannot
extract differently from the command a reader already trusts.

**What "already extracted" means, stated exactly.** Extraction leaves no
record of having run (see `app/web/review.py::_extraction_status`); what it
leaves is rows keyed by `session_id` in `facts.json`, `rejections.json` and
`demotions.json`. A session with a row in any of them was extracted. A session
whose extraction produced nothing at all -- no fact, no rejection, no
demotion -- is indistinguishable from one never run, and `--all` will offer it
again. That costs one call; inventing a marker would be a second record of the
same fact that could disagree with the first.

**The estimate is tokens, not money.** The request a session would send is
assembled exactly (`assemble_extract_request`) and sized by
`app.coach.token_estimate`, shared with every other preview. No price is printed: the extraction model is configurable
(`EXTRACT_MODEL`, `COACH_BASE_URL`), and a dollar figure for the wrong model
would be the most confident wrong number on the screen.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from app.coach import corpus as coach_corpus
from app.coach import corpus_store as coach_corpus_store
from app.coach import demotion_store as coach_demotion_store
from app.coach import reasoning_client, token_estimate
from app.coach import rejection_store as coach_rejection_store
from app.coach.extract import assemble_extract_request
from app.session import evidence as evidence_mod
from app.session.reader import MalformedRecordError, list_session_ids, read_session
from app.session.store import SegmentRecord

OK = "extracted"
REJECTIONS = "extracted-with-rejections"
FAILED = "failed"


class _Skip(Exception):
    """A session `--all` will not pay for, with the operator-facing reason."""


def extracted_session_ids(context_dir: Path) -> "set[str]":
    """Every session with a row in the corpus or either extraction log.
    Raises `CorpusValidationError` for a corpus that does not parse --
    `extract` would refuse to run over it anyway."""
    ids: "set[str]" = set(coach_corpus_store.session_ids_with_facts(context_dir))
    for row in coach_rejection_store.load_rejections(context_dir) + coach_demotion_store.load_demotions(context_dir):
        if isinstance(row.get("session_id"), str):
            ids.add(row["session_id"])
    return ids


def _segments(session_dir: Path) -> "tuple[SegmentRecord, ...]":
    try:
        meta = evidence_mod.read_meta(session_dir)
    except evidence_mod.EvidenceStateError as exc:
        raise _Skip(str(exc)) from exc
    if not isinstance(meta, dict):
        raise _Skip("session.json is not an object")
    refusal = evidence_mod.extract_refusal(meta)
    if refusal is not None:
        raise _Skip(refusal)
    try:
        result = read_session(session_dir, transcript_filename=evidence_mod.transcript_filename_for(meta))
        segments = tuple(
            SegmentRecord(**record)
            for record in evidence_mod.segment_fields(result.records_of_kind("segment"))
        )
    except (MalformedRecordError, ValueError, TypeError, OSError) as exc:
        raise _Skip(f"the transcript cannot be read ({type(exc).__name__})") from exc
    if not segments:
        raise _Skip("no transcript segments (a device test or an aborted start?)")
    return segments


def _estimate_tokens(segments, hypotheses, *, max_tokens: int) -> int:
    request = assemble_extract_request(
        transcript=segments, hypotheses=hypotheses,
        model=reasoning_client.resolve_extract_model(), max_tokens=max_tokens,
    )
    return token_estimate.estimate(request)


def run(args: argparse.Namespace, cfg, extract_session: Callable[..., str]) -> int:
    try:
        done = set() if args.force else extracted_session_ids(cfg.context_dir)
        hypotheses = coach_corpus.load_hypotheses(cfg.context_dir, missing_ok=True)
    except coach_corpus.CorpusValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    pending: "list[tuple[str, int]]" = []
    # Oldest first: imported and live interviews are named by when they took
    # place, so this is the order they happened in.
    for session_id in reversed(list_session_ids(cfg.sessions_root)):
        if session_id.startswith(".") or session_id in done:
            continue
        try:
            segments = _segments(cfg.sessions_root / session_id)
        except _Skip as exc:
            print(f"skipped {session_id}: {exc}", file=sys.stderr)
            continue
        pending.append((session_id, _estimate_tokens(segments, hypotheses, max_tokens=cfg.coach_extract_max_tokens)))

    if not pending:
        print("Nothing to extract: every interview here is already extracted"
              + ("." if not args.force else " (or has nothing to extract)."))
        return 0

    total = sum(tokens for _, tokens in pending)
    print(f"{len(pending)} interview(s) to extract, one vendor call each "
          f"(model {reasoning_client.resolve_extract_model()}):")
    for session_id, tokens in pending:
        print(f"  {session_id}  ~{tokens:,} input tokens")
    print(f"  total ~{total:,} input tokens, plus up to {cfg.coach_extract_max_tokens:,} output tokens each "
          f"({token_estimate.BASIS})")
    if not args.yes:
        print("Nothing called. Re-run with --yes to extract them.")
        return 0

    try:
        client = reasoning_client.build_client()
    except reasoning_client.CoachConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outcomes: "list[tuple[str, str]]" = []
    for session_id, _ in pending:
        print(f"\n== {session_id}")
        try:
            outcome = extract_session(cfg, cfg.sessions_root / session_id, client=client)
        except Exception as exc:  # noqa: BLE001 -- one failed session must not cost the remaining ones
            print(f"ERROR {session_id}: extraction failed ({type(exc).__name__}); continuing with the rest",
                  file=sys.stderr)
            outcome = FAILED
        outcomes.append((session_id, outcome))

    print("\nExtract --all summary:")
    for session_id, outcome in outcomes:
        print(f"  {session_id}: {outcome}")
    counts = {name: sum(1 for _, o in outcomes if o == name) for name in (OK, REJECTIONS, FAILED)}
    print(f"  {counts[OK] + counts[REJECTIONS]} extracted ({counts[REJECTIONS]} with rejections), "
          f"{counts[FAILED]} failed")
    # The single command's rule, kept: a run that deleted a fact is worth a
    # nonzero exit too, not only one that never reached the vendor.
    return 1 if counts[FAILED] or counts[REJECTIONS] else 0
