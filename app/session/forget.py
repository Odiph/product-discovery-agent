"""Erasing one interview: `python -m app forget <session_id>`.

An erasure request names a person, and this tool stores that person's words
in more than one place: the session directory (transcript, room audio,
renders, critiques), the node's context files keyed by `session_id`, and the
knowledge base when `kb add --sessions` copied the transcript in. Deleting the
directory alone -- what the README used to advise -- left the rest behind.

Three rules, each a decision rather than a default:

- **Planned, then applied.** `plan()` only reads; `apply()` deletes exactly
  what the plan names. The CLI prints the plan without `--yes`, so the
  operator sees counts and paths (never a word anyone said) before anything
  goes.
- **Tolerant on load, strict on save.** A file that cannot be parsed is never
  rewritten: a rewrite from a failed parse is how one interview's erasure
  becomes every interview's loss. It is left byte-identical and reported,
  and everything else is still erased -- a damaged log must not keep a
  person's interview on disk.
- **Only this node's data is deleted.** Session ids are start timestamps, so
  the same id at another node may be a DIFFERENT person's interview. Matches
  elsewhere are reported with the command that removes them, never removed
  on a guess.

The corpus is rewritten through `corpus_store.replace_session_facts` (with an
empty replacement), so that module stays the one writer of the fact corpus
and its strict loader is the one that decides whether the file parses.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from app import projects as projects_mod
from app.coach import corpus as coach_corpus
from app.coach import corpus_store
from app.coach.demotion_store import DEMOTIONS_FILENAME
from app.coach.rejection_store import REJECTIONS_FILENAME
from app.kb import digest as kb_digest
from app.kb.store import KnowledgeStore, KnowledgeStoreError
from app.projects import KNOWLEDGE_DIR_NAME
from app.session.reader import list_session_ids

# Named here rather than imported from `app/web/accept.py`: importing the web
# app's module to read one constant would pull the server into a CLI command.
DECLINED_FILENAME = "declined_proposals.json"
# The diagnostic logs whose rows carry a top-level `session_id`. The corpus is
# handled separately (see the module docstring).
ROW_LOG_FILENAMES = (REJECTIONS_FILENAME, DEMOTIONS_FILENAME, DECLINED_FILENAME)
SESSION_ORIGIN_PREFIX = "session:"

# A session id is a directory NAME. `create_session_dir` makes
# `%Y%m%dT%H%M%S[-n]`; this admits that and any plain name, and nothing with
# a separator, a drive or a leading dot. Checked before any path is built.
_SESSION_ID_SHAPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


class SessionIdError(ValueError):
    pass


@dataclass(frozen=True)
class Node:
    """One place sessions are filed: the root, or a project node."""

    label: Optional[str]
    """The `--project` path, or `None` for the root sessions/ and context/."""
    sessions_root: Path
    context_dir: Path
    knowledge_dir: Optional[Path]
    """`None` at the root: the knowledge base belongs to project nodes."""


@dataclass(frozen=True)
class Plan:
    session_id: str
    node: Node
    session_dir: Optional[Path]
    session_files: int
    session_bytes: int
    rows: "dict[str, int]"
    """Context file name -> rows that name this session (only files with any)."""
    kb_doc_ids: "tuple[str, ...]"
    digest_entries: int
    unreadable: "tuple[tuple[str, str], ...]"
    """(path, reason) for every file that could not be checked; never written."""
    elsewhere: "tuple[str, ...]"
    """Human-readable lines for matches at OTHER nodes; reported, not deleted."""
    registered_after: "tuple[str, ...]"
    """Hypothesis ids whose pre-registration boundary names this session."""

    @property
    def found_anything(self) -> bool:
        return bool(self.session_dir or self.rows or self.kb_doc_ids or self.digest_entries)


@dataclass
class Outcome:
    removed: "list[str]" = field(default_factory=list)
    failed: "list[str]" = field(default_factory=list)


def validate_session_id(session_id: str) -> str:
    if not _SESSION_ID_SHAPE.fullmatch(session_id or ""):
        raise SessionIdError(
            f"{session_id!r} is not a session id: give the directory name under sessions/ "
            "(for example 20261101T100000), not a path"
        )
    return session_id


# --- reading -------------------------------------------------------------------


def _read_rows(path: Path) -> "list[Any]":
    """The file as a JSON array, or raises `ValueError`/`OSError`. Strict on
    purpose: this read is what a rewrite is built on."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("not a JSON array")
    return raw


def _matches(row: Any, session_id: str) -> bool:
    return isinstance(row, dict) and row.get("session_id") == session_id


def _count_facts(context_dir: Path, session_id: str) -> int:
    if not (context_dir / coach_corpus.FACTS_FILENAME).is_file():
        return 0
    facts = coach_corpus.load_facts(context_dir, sessions_root=None)
    return sum(1 for fact in facts if fact.session_id == session_id)


def _kb_matches(knowledge_dir: Path, session_id: str) -> "tuple[list[str], list[str]]":
    """(doc ids whose origin is this session, damaged file names)."""
    stored, damaged = KnowledgeStore(knowledge_dir).scan()
    origin = SESSION_ORIGIN_PREFIX + session_id
    return [s.doc_id for s in stored if s.document.origin == origin], list(damaged)


def _session_dir_stats(session_dir: Path) -> "tuple[int, int]":
    files = [p for p in session_dir.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def _registered_after(context_dir: Path, session_id: str) -> "tuple[str, ...]":
    try:
        hypotheses = coach_corpus.load_hypotheses(context_dir, missing_ok=True)
    except coach_corpus.CorpusValidationError:
        return ()  # a report, not an erasure: an unreadable file just goes unmentioned
    return tuple(h.id for h in hypotheses if session_id in h.criterion_registered_after)


def plan(session_id: str, node: Node, *, other_nodes: Sequence[Node] = ()) -> Plan:
    """Everything `apply` would delete. Reads only."""
    session_id = validate_session_id(session_id)
    unreadable: "list[tuple[str, str]]" = []

    # The directory is addressed only if the listing found it: the same
    # allowlist the hub uses for a session id that arrives from a browser.
    session_dir: Optional[Path] = None
    files = size = 0
    if session_id in list_session_ids(node.sessions_root):
        session_dir = node.sessions_root / session_id
        files, size = _session_dir_stats(session_dir)

    rows: "dict[str, int]" = {}
    try:
        count = _count_facts(node.context_dir, session_id)
        if count:
            rows[coach_corpus.FACTS_FILENAME] = count
    except coach_corpus.CorpusValidationError as exc:
        unreadable.append((str(node.context_dir / coach_corpus.FACTS_FILENAME), type(exc).__name__))
    for name in ROW_LOG_FILENAMES:
        path = node.context_dir / name
        if not path.is_file():
            continue
        try:
            count = sum(1 for row in _read_rows(path) if _matches(row, session_id))
        except (OSError, ValueError) as exc:
            unreadable.append((str(path), type(exc).__name__))
            continue
        if count:
            rows[name] = count

    doc_ids: "list[str]" = []
    digest_entries = 0
    if node.knowledge_dir is not None:
        doc_ids, damaged = _kb_matches(node.knowledge_dir, session_id)
        unreadable.extend((str(node.knowledge_dir / "documents" / name), "damaged") for name in damaged)
        try:
            digest_entries = sum(1 for e in kb_digest.load(node.knowledge_dir) if e.doc_id in set(doc_ids))
        except kb_digest.DigestError:
            unreadable.append((str(kb_digest.digest_path(node.knowledge_dir)), "DigestError"))

    return Plan(
        session_id=session_id, node=node, session_dir=session_dir,
        session_files=files, session_bytes=size, rows=rows,
        kb_doc_ids=tuple(doc_ids), digest_entries=digest_entries,
        unreadable=tuple(unreadable),
        elsewhere=_elsewhere(session_id, other_nodes),
        registered_after=_registered_after(node.context_dir, session_id),
    )


def _forget_command(session_id: str, node: Node) -> str:
    suffix = f" --project {node.label}" if node.label else ""
    return f"python -m app forget {session_id}{suffix}"


def _elsewhere(session_id: str, other_nodes: Sequence[Node]) -> "tuple[str, ...]":
    lines: "list[str]" = []
    for other in other_nodes:
        where = f"projects/{other.label}" if other.label else "the root sessions/"
        if session_id in list_session_ids(other.sessions_root):
            lines.append(f"{where} also has a session named {session_id} -- if it is the same "
                         f"interview, run: {_forget_command(session_id, other)}")
        if other.knowledge_dir is None:
            continue
        try:
            doc_ids, _ = _kb_matches(other.knowledge_dir, session_id)
        except OSError:
            continue
        for doc_id in doc_ids:
            lines.append(f"{where} has a knowledge-base copy of a session named {session_id} -- "
                         f"if it is this interview, run: python -m app kb remove {doc_id} --project {other.label}")
    return tuple(lines)


def all_nodes(*, repo_root: Optional[Path] = None) -> "tuple[Node, ...]":
    """Every project node, for the report of matches elsewhere."""
    nodes = []
    for found in projects_mod.list_projects(repo_root=repo_root):
        paths = projects_mod.resolve(found.path, repo_root=repo_root)
        nodes.append(Node(found.path, paths.sessions_root, paths.context_dir,
                          paths.node_dir / KNOWLEDGE_DIR_NAME))
    return tuple(nodes)


# --- writing -------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: object) -> None:
    """Temp file in the same directory, flush, fsync, `os.replace` -- the
    discipline every store here uses. Until `os.replace` runs, `path` was
    never opened for writing."""
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def _strip_rows(path: Path, session_id: str) -> int:
    """Rewrites `path` without this session's rows. Every other item is
    re-serialized unread, unknown fields and all. Re-reads rather than
    trusting the plan's count, so a file changed since is judged as it is."""
    rows = _read_rows(path)
    kept = [row for row in rows if not _matches(row, session_id)]
    if len(kept) != len(rows):
        _atomic_write_json(path, kept)
    return len(rows) - len(kept)


def apply(the_plan: Plan) -> Outcome:
    """Deletes what `the_plan` names. Derived data first and the session
    directory LAST: if anything stops half-way, the directory is still listed,
    so re-running the same command finishes the job."""
    outcome = Outcome()
    sid, node = the_plan.session_id, the_plan.node

    if the_plan.kb_doc_ids and node.knowledge_dir is not None:
        store = KnowledgeStore(node.knowledge_dir)
        for doc_id in the_plan.kb_doc_ids:
            try:
                store.remove(doc_id)
                outcome.removed.append(f"knowledge-base document {doc_id}")
            except (KnowledgeStoreError, OSError) as exc:
                outcome.failed.append(f"knowledge-base document {doc_id}: {type(exc).__name__}")
        if the_plan.digest_entries:
            try:
                entries = kb_digest.load(node.knowledge_dir)
                kept = [e for e in entries if e.doc_id not in set(the_plan.kb_doc_ids)]
                kb_digest.save(node.knowledge_dir, kept)
                outcome.removed.append(f"{len(entries) - len(kept)} coach-digest entr{'y' if len(entries) - len(kept) == 1 else 'ies'}")
            except (kb_digest.DigestError, OSError) as exc:
                outcome.failed.append(f"{kb_digest.digest_path(node.knowledge_dir)}: {type(exc).__name__}")

    if coach_corpus.FACTS_FILENAME in the_plan.rows:
        try:
            corpus_store.replace_session_facts(node.context_dir, sid, ())
            outcome.removed.append(f"{the_plan.rows[coach_corpus.FACTS_FILENAME]} row(s) from {coach_corpus.FACTS_FILENAME}")
        except (coach_corpus.CorpusValidationError, OSError) as exc:
            outcome.failed.append(f"{node.context_dir / coach_corpus.FACTS_FILENAME}: {type(exc).__name__} (left untouched)")
    for name in ROW_LOG_FILENAMES:
        if name not in the_plan.rows:
            continue
        try:
            removed = _strip_rows(node.context_dir / name, sid)
            outcome.removed.append(f"{removed} row(s) from {name}")
        except (OSError, ValueError) as exc:
            outcome.failed.append(f"{node.context_dir / name}: {type(exc).__name__} (left untouched)")

    if the_plan.session_dir is not None:
        outcome_line = _remove_session_dir(the_plan.session_dir)
        (outcome.failed if outcome_line.startswith("could not") else outcome.removed).append(outcome_line)
    return outcome


def _remove_session_dir(session_dir: Path) -> str:
    # A link would make rmtree delete (or refuse) something that is not this
    # interview's own directory; neither is what was asked for.
    if session_dir.is_symlink() or session_dir.is_junction():
        return f"could not delete {session_dir}: it is a link, not a directory -- remove it by hand"
    try:
        shutil.rmtree(session_dir)
    except OSError as exc:
        # Typically a file still open (a recording in progress, a player).
        left = sum(1 for p in session_dir.rglob("*") if p.is_file()) if session_dir.exists() else 0
        return f"could not delete {session_dir} ({type(exc).__name__}); {left} file(s) remain -- close what holds them and run again"
    return f"session directory {session_dir}"
