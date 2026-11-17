"""`python -m app prep --draft [--yes]`: the one paid call that words new
questions for the gaps `prep` shows (`app/coach/prep_draft.py`), cached in
`context/prep_draft.json`.

Without `--yes`: what would be sent, a few of the gaps, the token estimate,
and nothing called. With `--yes`: one call, the cache written, the drafts
printed under each gap, and every question the code check dropped, with its
reason. A re-run with unchanged inputs reads the cache and calls nothing.

`panel` is the same draft for the `author` page's prep panel: it reads the
cache, never builds a client.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app import prep_gather, project_meta, projects
from app.coach import prep_draft as draft_mod
from app.coach import prep_draft_store as store
from app.coach import reasoning_client, token_estimate
from app.coach.context import BRIEF_FILENAME
from app.coach.corpus import CorpusValidationError
from app.mirror_cli import FLAG_LABELS

logger = logging.getLogger(__name__)

COMMAND = "python -m app prep --draft"
EXAMPLES_SHOWN = 3
NO_GAPS = "no-gaps"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Resolution:
    draft: Optional[draft_mod.Draft]
    """A fresh draft to show under the gaps; None when there is none."""
    notes: "tuple[str, ...]" = ()
    error: str = ""
    """Set only when the command must stop with an error."""


def operator_brief(context_dir: Path) -> "tuple[str, ...]":
    """The text of the brief items the operator wrote, read from the brief
    file alone. Never `load_brief`: that merges facts retrieved from the
    interviews into the brief for the live coach, and those carry what
    interviewees said. Unreadable or malformed: nothing."""
    try:
        raw = json.loads((Path(context_dir) / BRIEF_FILENAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ()
    if not isinstance(raw, list):
        return ()
    return tuple(entry["text"] for entry in raw if isinstance(entry, dict) and isinstance(entry.get("text"), str))


def inputs_for(context_dir: Path, gathered: prep_gather.Gathered) -> draft_mod.DraftInputs:
    plan = gathered.plan
    return draft_mod.inputs(
        gaps=[draft_mod.DraftGap(g.hypothesis_id, g.kind, g.statement, g.reason) for g in plan.gaps],
        survey=[(item.id, item.text) for item in sorted(gathered.survey, key=lambda i: i.order)],
        brief=operator_brief(context_dir),
        hypotheses=[(h.id, h.statement) for h in gathered.hypotheses],
        avoid=[FLAG_LABELS.get(h.flag, h.flag) for h in gathered.habits],
        topics=[topic.label for topic in plan.raised],
    )


def resolve(context_dir: Path, drafted: draft_mod.DraftInputs, *, yes: bool) -> Resolution:
    if not drafted.gaps:
        return Resolution(None, ("No gap to draft questions for: nothing was sent.",))
    model = reasoning_client.resolve_judge_model(context_dir)
    state = store.load(context_dir, drafted, model)
    if state.status == store.FRESH:
        return Resolution(state.draft, (f"Drafted questions: by {model}, cached in context/{store.CACHE_FILENAME}; "
                                        f"nothing called.",) + drop_lines(state.draft))
    why = {store.ABSENT: "no draft is cached yet",
           store.STALE: f"the cached draft is stale: {state.reason}",
           store.UNREADABLE: f"the cached draft is unusable: {state.reason}"}[state.status]
    note = reasoning_client.pin_note(context_dir)
    plan = preview(drafted, model, note=note)
    if not yes:
        return Resolution(None, plan + (f"Nothing called ({why}). Re-run with --yes to draft them.",))
    try:
        client = reasoning_client.build_client()
        draft = draft_mod.draft(client, drafted, model=model)
    except reasoning_client.CoachConfigError as exc:
        return Resolution(None, error=str(exc))
    except draft_mod.JudgeFailure as exc:
        return Resolution(None, error=f"{exc}{note}. Nothing was written; the previous draft (if any) is unchanged.")
    try:
        store.write(context_dir, draft)
        saved = f"saved to context/{store.CACHE_FILENAME}"
    except (OSError, ValueError) as exc:
        # Paid for already: show it anyway, and say it is not kept.
        saved = (f"NOT saved ({type(exc).__name__}: {exc}), so the next run calls again, and `author` "
                 f"cannot offer these")
    return Resolution(draft, plan[:1] + (f"Drafted questions: by {model}, {saved}.",) + drop_lines(draft))


def preview(drafted: draft_mod.DraftInputs, model: str, *, note: str = "") -> "tuple[str, ...]":
    """What the call would send, and what it costs."""
    request = draft_mod.assemble_request(drafted, model=model)
    gaps = drafted.gaps
    lines = [f"One call to {model}{note} to draft up to {draft_mod.PER_GAP} new questions for each of the "
             f"{len(gaps)} gap(s) above. Sent: each gap (its hypothesis and why it is a gap), your "
             f"{len(drafted.survey)} survey question(s), {len(drafted.brief)} brief item(s), "
             f"{len(drafted.hypotheses)} hypothesis statement(s), {len(drafted.avoid)} habit label(s) to avoid "
             f"and {len(drafted.topics)} topic label(s). Never anything an interviewee said: no transcript, no "
             f"claim, no quote. ~{draft_mod.estimate_input_tokens(request):,} input tokens, plus up to "
             f"{draft_mod.DEFAULT_MAX_TOKENS:,} output tokens ({token_estimate.BASIS}).",
             f"For example ({min(EXAMPLES_SHOWN, len(gaps))} of {len(gaps)} gaps, as sent):"]
    for gap in gaps[:EXAMPLES_SHOWN]:
        lines.append(f"  gap {gap.gap_id} [{gap.kind}]: {gap.statement}")
        lines.append(f"    why it is a gap: {gap.reason}")
    return tuple(lines)


def drop_lines(draft: draft_mod.Draft) -> "tuple[str, ...]":
    if not draft.dropped:
        return ()
    return (f"Dropped {len(draft.dropped)} of the model's question(s) by the code check:",) + tuple(
        f"  [{d.gap_id or '?'}] {d.text or '(blank)'} -- {d.reason}" for d in draft.dropped)


def project_command(context_dir: Path, *, repo_root: Optional[Path] = None) -> str:
    """`COMMAND` with the `--project` that names this node, so the page can
    offer a line that runs as pasted. The bare command outside the tree."""
    root = (Path(repo_root) if repo_root else projects.REPO_ROOT) / projects.PROJECTS_DIR_NAME
    try:
        relative = Path(context_dir).parent.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return COMMAND
    return f"{COMMAND} --project {relative.as_posix()}" if relative.parts else COMMAND


def _gap_fields(gap) -> dict:
    return {"gap_id": gap.hypothesis_id, "kind": gap.kind, "statement": gap.statement,
            "falsifier": gap.falsifier, "for": gap.support, "against": gap.contrary,
            "unclear": gap.unclear, "interviews": gap.interviews}


def panel(context_dir: Path, sessions_root: Path) -> dict:
    """The cached draft for the `author` page: read-only, never a model call.
    `state` is a cache status, `no-gaps`, or `unavailable` (a corpus that
    will not load); `command` is what makes or refreshes a draft."""
    context_dir = Path(context_dir)
    base = {"command": COMMAND, "project_command": project_command(context_dir), "questions": [],
            "gaps": [], "reason": "",
            "mock_label": project_meta.MOCK_LABEL if project_meta.is_demo_node(context_dir.parent) else None}
    try:
        hypotheses, refs = prep_gather.read_corpus(context_dir)
        gathered = prep_gather.gather(context_dir, Path(sessions_root), hypotheses, refs)
        drafted = inputs_for(context_dir, gathered)
        if not drafted.gaps:
            return {**base, "state": NO_GAPS}
        state = store.load(context_dir, drafted, reasoning_client.resolve_judge_model(context_dir))
    except CorpusValidationError as exc:
        return {**base, "state": UNAVAILABLE, "reason": f"the corpus will not load ({type(exc).__name__})"}
    except Exception as exc:  # noqa: BLE001 -- an optional panel must never take /api/prep down with it
        logger.warning("prep draft panel unavailable: %s", type(exc).__name__)
        return {**base, "state": UNAVAILABLE, "reason": f"the draft could not be read ({type(exc).__name__})"}
    if state.status != store.FRESH:
        return {**base, "state": state.status, "reason": state.reason}
    statements = {gap.gap_id: gap.statement for gap in drafted.gaps}
    answered = {q.gap_id for q in state.draft.questions}
    gaps = [_gap_fields(g) for g in gathered.plan.gaps if g.hypothesis_id in answered]
    return {**base, "state": store.FRESH, "gaps": gaps, "questions": [
        {"gap_id": q.gap_id, "statement": statements.get(q.gap_id, ""), "text": q.text, "why": q.why}
        for q in state.draft.questions]}
