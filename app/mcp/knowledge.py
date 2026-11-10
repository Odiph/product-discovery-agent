"""`search_knowledge`: the project knowledge base (app/kb/), read-only, over MCP.

**What crosses the wire is decided per SOURCE TYPE, and speech never does.**
This server's standing promise is that no tool exposes verbatim customer
speech. A knowledge base holds plenty of it -- interview turns, other
recorded conversations, customers' emails -- so a hit from those types
carries its CITATION only (document, title, date, location, and for an
interview the role that spoke), and the operator reads the words on their own
machine with `python -m app kb search`. Research notes and code are the
operator's own material, and only those hits carry a snippet.

Email subjects are customer-written text as much as bodies are, so an email
hit has no title either. Participant names and addresses never cross.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from app.kb import index as kb_index
from app.kb.document import CODE, EMAIL, INTERVIEW, RESEARCH, SOURCE_TYPES
from app.kb.store import KnowledgeStore

TEXT_SAFE_TYPES = frozenset({RESEARCH, CODE})
MAX_LIMIT = 25
MAX_QUERY_CHARS = 500


class KnowledgeArgumentError(ValueError):
    pass


def search(arguments: "Mapping[str, Any]", node) -> "dict[str, Any]":
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise KnowledgeArgumentError(
            f"'query' is required: a non-empty string of at most {MAX_QUERY_CHARS} characters"
        )
    types = arguments.get("source_types")
    if types is not None and (
        not isinstance(types, list) or not types or any(t not in SOURCE_TYPES for t in types)
    ):
        raise KnowledgeArgumentError(f"'source_types' must be a non-empty list drawn from {list(SOURCE_TYPES)}")
    limit = arguments.get("limit", kb_index.DEFAULT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise KnowledgeArgumentError(f"'limit' must be an integer from 1 to {MAX_LIMIT}")

    stored, damaged = KnowledgeStore.for_node(Path(node.node_dir)).scan()
    documents = [item.document for item in stored]
    counts: "dict[str, int]" = {}
    for document in documents:
        counts[document.source_type] = counts.get(document.source_type, 0) + 1
    hits = kb_index.KeywordIndex(documents).search(query, limit=limit, source_types=types)
    return {
        "project": node.path,
        "documents": counts,
        "hits": [_project_hit(hit) for hit in hits],
        # A count, never a name or a parse message: those can carry content.
        "damaged_documents": len(damaged),
        "error": None,
    }


def _project_hit(hit: kb_index.Hit) -> "dict[str, Any]":
    """Field by field, never `asdict(hit)`: the snippet and the speaker name
    are exactly the fields that must not cross for speech."""
    projected: "dict[str, Any]" = {
        "doc_id": hit.doc_id,
        "source_type": hit.source_type,
        "title": None if hit.source_type == EMAIL else hit.title,
        "date": hit.date,
        "location": hit.location,
        "score": hit.score,
        "text": hit.snippet if hit.source_type in TEXT_SAFE_TYPES else None,
    }
    if hit.source_type == INTERVIEW:
        projected["role"] = hit.speaker
    return projected


SCHEMA_PROPERTIES: "dict[str, Any]" = {
    "query": {
        "type": "string",
        "description": "Words to search for, English or Hebrew. Keyword search, not a question.",
    },
    "source_types": {
        "type": "array",
        "items": {"type": "string", "enum": list(SOURCE_TYPES)},
        "description": "Optional. Only these kinds of source.",
    },
    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "default": kb_index.DEFAULT_LIMIT},
}

DESCRIPTION = (
    "Search one project's knowledge base: its own interviews, conversations recorded elsewhere, "
    "emails, research notes and code, added by the operator with `python -m app kb add`. Every "
    "hit cites its document and the exact place in it (turn, line, paragraph). Hits from "
    "interviews, conversations and emails carry NO text -- that is customer speech, read on the "
    "operator's machine -- only research and code hits carry a snippet. Source types are "
    "different kinds of knowing and are never evidence for or against a hypothesis: only "
    "get_standing says where a hypothesis stands. An empty 'documents' means nothing has been "
    "added yet, not that nothing is known."
)

