"""The knowledge base on disk: one JSON file per document under
`projects/<node>/knowledge/documents/`, written atomically.

Identity is (source type, origin), so adding the same file twice is a no-op
when its content is unchanged and a replacement when it changed. The whole
`projects/` tree is git-ignored, which is what keeps an indexed email or a
customer's transcript out of the repository.
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.kb.document import DOC_ID_LENGTH, Document
from app.projects import KNOWLEDGE_DIR_NAME

DOCUMENTS_DIR_NAME = "documents"

ADDED = "added"
UPDATED = "updated"
UNCHANGED = "unchanged"


class KnowledgeStoreError(ValueError):
    pass


@dataclass(frozen=True)
class StoredDocument:
    doc_id: str
    content_hash: str
    document: Document


class KnowledgeStore:
    def __init__(self, knowledge_dir: Path) -> None:
        self._dir = Path(knowledge_dir) / DOCUMENTS_DIR_NAME

    @classmethod
    def for_node(cls, node_dir: Path) -> "KnowledgeStore":
        return cls(Path(node_dir) / KNOWLEDGE_DIR_NAME)

    def put(self, document: Document) -> str:
        path = self._path(document.doc_id)
        if path.is_file():
            try:
                existing = self._read(path)
            except KnowledgeStoreError:
                existing = None  # damaged: re-adding the source is the repair
            # A type the operator confirmed stays confirmed when the same file
            # is later re-added by guess (a folder re-add, an edit): same id
            # means same type and origin, and only `kb remove` un-confirms it.
            if existing is not None and existing.document.explicit_type and not document.explicit_type:
                document = dataclasses.replace(document, explicit_type=True)
            # Same content is unchanged -- unless this add CONFIRMS a guess.
            if existing is not None and existing.content_hash == document.content_hash and (
                existing.document.explicit_type == document.explicit_type
            ):
                return UNCHANGED
            outcome = UPDATED
        else:
            outcome = ADDED
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(document.to_record(), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return outcome

    def all(self) -> "list[StoredDocument]":
        return self.scan()[0]

    def scan(self) -> "tuple[list[StoredDocument], list[str]]":
        """Every readable document, and the file names of damaged ones. One
        damaged file must not take the whole knowledge base offline."""
        if not self._dir.is_dir():
            return [], []
        stored, damaged = [], []
        for path in sorted(self._dir.glob("*.json")):
            try:
                stored.append(self._read(path))
            except KnowledgeStoreError:
                damaged.append(path.name)
        stored.sort(key=lambda s: (s.document.source_type, s.document.date or "", s.document.title))
        return stored, damaged

    def get(self, doc_ref: str) -> StoredDocument:
        return self._read(self._path(self.resolve_id(doc_ref)))

    def remove(self, doc_ref: str) -> StoredDocument:
        doc_id = self.resolve_id(doc_ref)
        path = self._path(doc_id)
        stored = self._read(path)
        path.unlink()
        return stored

    def resolve_id(self, doc_ref: str) -> str:
        """A full id, or a prefix of at least four characters that names
        exactly one document -- refused when ambiguous, never guessed."""
        ref = (doc_ref or "").strip().lower()
        if len(ref) < 4 or len(ref) > DOC_ID_LENGTH or not all(c in "0123456789abcdef" for c in ref):
            raise KnowledgeStoreError(f"{doc_ref!r} is not a document id (see `kb list`)")
        matches = [p.stem for p in self._dir.glob(f"{ref}*.json")] if self._dir.is_dir() else []
        if not matches:
            raise KnowledgeStoreError(f"no document {doc_ref!r} in this project's knowledge base")
        if len(matches) > 1:
            raise KnowledgeStoreError(f"{doc_ref!r} matches {len(matches)} documents; give more of the id")
        return matches[0]

    def _path(self, doc_id: str) -> Path:
        return self._dir / f"{doc_id}.json"

    @staticmethod
    def _read(path: Path) -> StoredDocument:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            return StoredDocument(record["doc_id"], record["content_hash"], Document.from_record(record))
        except (ValueError, KeyError, TypeError) as exc:
            raise KnowledgeStoreError(f"{path.name} in the knowledge base is damaged: {exc}") from exc

