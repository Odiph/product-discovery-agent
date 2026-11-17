"""A code repository as knowledge: what is built, not every source line.

The document is the repository's own prose (READMEs, `docs/`, top-level
Markdown) plus one generated section summarising the tree -- the languages by
file count, the top-level layout and the manifest's own description. That is
what an interviewer needs to know about the product ("is that already
built?"), and it keeps a large repository from drowning every search.
"""

from __future__ import annotations

import json
import tomllib
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from app.kb import secret_scan
from app.kb.document import CODE, Document, Section
from app.kb.written import _paragraphs

_SKIPPED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    "dist", "build", "target", ".next", ".tox", ".mypy_cache", ".pytest_cache",
    "site-packages", "vendor", ".idea", ".vscode",
})
_PROSE_SUFFIXES = frozenset({".md", ".markdown", ".rst", ".txt"})
_DOC_DIRS = ("docs", "doc", "documentation")
MAX_PROSE_FILES = 60
MAX_PROSE_BYTES = 400_000
MAX_WALKED_FILES = 50_000
TOP_LANGUAGES = 8


def is_repository(path: Path) -> bool:
    return path.is_dir() and any((path / marker).exists() for marker in (".git", "pyproject.toml", "package.json"))


def from_repository(root: Path) -> Document:
    return read_repository(root)[0]


def read_repository(root: Path) -> "tuple[Document, tuple[tuple[str, str], ...]]":
    """The document, and the prose files refused for holding a secret, as
    (path, reason). One runbook with a key pasted in costs that file, not the
    repository: the rest of its prose is still the operator's own."""
    root = Path(root).resolve()
    sections = [Section(text=_tree_summary(root), location="summary")]
    refused: "list[tuple[str, str]]" = []
    for prose in _prose_files(root):
        relative = prose.relative_to(root).as_posix()
        refusal = secret_scan.name_refusal(prose)
        if refusal:
            refused.append((str(prose), refusal))
            continue
        try:
            text = prose.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = [Section(text=section.text, location=f"{relative}:{section.location.split()[-1]}")
                 for section in _paragraphs(text)]
        refusal = secret_scan.document_refusal(
            Document(source_type=CODE, origin=str(prose), title=relative, sections=tuple(found))
        )
        if refusal:
            refused.append((str(prose), refusal))
            continue
        sections.extend(found)
    document = Document(source_type=CODE, origin=str(root), title=f"Repository {root.name}", sections=tuple(sections))
    return document, tuple(refused)


def _walk(root: Path) -> Iterable[Path]:
    count = 0
    stack = [root]
    while stack and count < MAX_WALKED_FILES:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not _inside(root, entry):
                continue
            if entry.is_dir():
                if entry.name not in _SKIPPED_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
            elif entry.is_file():
                count += 1
                yield entry


def _inside(root: Path, path: Path) -> bool:
    """A cloned repository can hold `README.md -> ~/secrets.txt` or a `docs`
    link to a home folder. Nothing reached through a link is read -- an NTFS
    junction included, which `is_symlink()` does not see (Python 3.12)."""
    if path.is_symlink() or path.is_junction():
        return False
    try:
        return path.resolve().is_relative_to(root)
    except OSError:
        return False


def _prose_files(root: Path) -> "list[Path]":
    top = sorted(
        p for p in root.iterdir()
        if _inside(root, p) and p.is_file() and p.suffix.lower() in _PROSE_SUFFIXES
    )
    readmes = sorted(
        p for p in _walk(root)
        if p.name.lower().startswith("readme") and p.suffix.lower() in _PROSE_SUFFIXES and p.parent != root
    )
    docs = [
        p for name in _DOC_DIRS if _inside(root, root / name) and (root / name).is_dir()
        for p in sorted(_walk(root / name)) if p.suffix.lower() in _PROSE_SUFFIXES
    ]
    chosen: "list[Path]" = []
    total = 0
    for path in [*top, *readmes, *docs]:
        if path in chosen or len(chosen) >= MAX_PROSE_FILES or not _inside(root, path):
            continue
        size = path.stat().st_size
        if total + size > MAX_PROSE_BYTES:
            continue
        chosen.append(path)
        total += size
    return chosen


def _tree_summary(root: Path) -> str:
    suffixes: Counter = Counter()
    for path in _walk(root):
        if path.suffix:
            suffixes[path.suffix.lower()] += 1
    top_dirs = sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and p.name not in _SKIPPED_DIRS and not p.name.startswith(".")
    )
    parts = [f"Repository {root.name}."]
    description = _manifest_description(root)
    if description:
        parts.append(description)
    if suffixes:
        languages = ", ".join(f"{suffix} ({count})" for suffix, count in suffixes.most_common(TOP_LANGUAGES))
        parts.append(f"Files by type: {languages}.")
    if top_dirs:
        parts.append(f"Top-level directories: {', '.join(top_dirs)}.")
    return " ".join(parts)


def _manifest_description(root: Path) -> Optional[str]:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        except (tomllib.TOMLDecodeError, OSError):
            project = {}
        if project.get("description"):
            return f"{project.get('name', root.name)}: {project['description']}"
    package = root / "package.json"
    if package.is_file():
        try:
            manifest = json.loads(package.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            manifest = {}
        if isinstance(manifest, dict) and manifest.get("description"):
            return f"{manifest.get('name', root.name)}: {manifest['description']}"
    return None
