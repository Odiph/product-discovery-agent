"""Keyword retrieval (BM25) over a project's knowledge base, and the topic
terms each document is about.

Built in memory from the stored documents on every call: a project's
knowledge is hundreds of documents, not millions, and an index rebuilt from
the source of truth cannot go stale. Embeddings are a later layer on top of
this one (BGE-M3, once measured on our own Hebrew and English), not a
replacement for it.

A hit always cites one section -- the turn, line or paragraph that matched
best -- never just the document.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from app.kb import terms
from app.kb.document import Document, Section

CHUNK_CHARS = 900
BM25_K1 = 1.2
BM25_B = 0.75
SNIPPET_CHARS = 240
DEFAULT_LIMIT = 10
DEFAULT_PER_DOCUMENT = 2
TOPICS_PER_DOCUMENT = 8
# A form derived by stripping (a particle, a plural) is a weaker match than
# the word as written: `משלוח` stripped is `לוח`, a different word.
DERIVED_FORM_WEIGHT = 0.6
MIN_BIGRAM_COUNT = 2
# A word said once is not what a document is about -- unless the document is tiny.
MIN_TOPIC_COUNT = 2
SHORT_DOCUMENT_WORDS = 80


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    sections: "tuple[Section, ...]"

    @property
    def text(self) -> str:
        return " ".join(section.text for section in self.sections)


@dataclass(frozen=True)
class Hit:
    doc_id: str
    source_type: str
    title: str
    date: Optional[str]
    location: str
    speaker: Optional[str]
    snippet: str
    score: float


def chunk(document: Document) -> "list[Chunk]":
    """Consecutive sections up to CHUNK_CHARS; a longer section stands alone
    (BM25's length normalisation already discounts it)."""
    chunks: "list[Chunk]" = []
    current: "list[Section]" = []
    size = 0
    for section in document.sections:
        if current and size + len(section.text) > CHUNK_CHARS:
            chunks.append(Chunk(document.doc_id, tuple(current)))
            current, size = [], 0
        current.append(section)
        size += len(section.text) + 1
    if current:
        chunks.append(Chunk(document.doc_id, tuple(current)))
    return chunks


class KeywordIndex:
    def __init__(self, documents: Iterable[Document]) -> None:
        self._documents = {document.doc_id: document for document in documents}
        self._chunks: "list[Chunk]" = []
        self._chunk_terms: "list[Counter]" = []
        self._postings: "dict[str, list[int]]" = defaultdict(list)
        self._chunk_lengths: "list[int]" = []
        for document in self._documents.values():
            for piece in chunk(document):
                words = terms.words(piece.text)
                counts = Counter(form for word in words for form in terms.forms(word))
                position = len(self._chunks)
                self._chunks.append(piece)
                self._chunk_terms.append(counts)
                # Length in WORDS: counting the extra forms would make a
                # Hebrew chunk look two to three times longer than an English
                # one with the same number of words.
                self._chunk_lengths.append(len(words))
                for term in counts:
                    self._postings[term].append(position)
        lengths = self._chunk_lengths
        self._lengths = lengths
        self._average_length = (sum(lengths) / len(lengths)) if lengths else 0.0

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def search(
        self,
        query: str,
        *,
        limit: int = DEFAULT_LIMIT,
        per_document: int = DEFAULT_PER_DOCUMENT,
        source_types: Optional[Sequence[str]] = None,
    ) -> "list[Hit]":
        query_words = [w for w in dict.fromkeys(terms.words(query)) if w not in terms.STOPWORDS]
        if not query_words or not self._chunks:
            return []
        allowed = set(source_types) if source_types else None
        scores: "dict[int, float]" = defaultdict(float)
        for word in query_words:
            best: "dict[int, float]" = {}
            for rank, form in enumerate(terms.forms(word)):
                weight = 1.0 if rank == 0 else DERIVED_FORM_WEIGHT
                for position, score in self._score_form(form).items():
                    score *= weight
                    if score > best.get(position, 0.0):
                        best[position] = score
            for position, score in best.items():
                scores[position] += score
        hits: "list[Hit]" = []
        taken: Counter = Counter()
        for position, score in sorted(scores.items(), key=lambda item: (-item[1], item[0])):
            piece = self._chunks[position]
            document = self._documents[piece.doc_id]
            if allowed is not None and document.source_type not in allowed:
                continue
            if taken[piece.doc_id] >= per_document:
                continue
            taken[piece.doc_id] += 1
            section = _best_section(piece, query_words)
            hits.append(Hit(
                doc_id=piece.doc_id,
                source_type=document.source_type,
                title=document.title,
                date=document.date,
                location=section.location,
                speaker=section.speaker,
                snippet=_snippet(section.text, query_words),
                score=round(score, 4),
            ))
            if len(hits) >= limit:
                break
        return hits

    def _score_form(self, form: str) -> "dict[int, float]":
        postings = self._postings.get(form)
        if not postings:
            return {}
        total = len(self._chunks)
        idf = math.log(1 + (total - len(postings) + 0.5) / (len(postings) + 0.5))
        scored = {}
        for position in postings:
            frequency = self._chunk_terms[position][form]
            norm = BM25_K1 * (1 - BM25_B + BM25_B * self._lengths[position] / (self._average_length or 1))
            scored[position] = idf * frequency * (BM25_K1 + 1) / (frequency + norm)
        return scored


def _best_section(piece: Chunk, query_words: "list[str]") -> Section:
    wanted = [set(terms.forms(word)) for word in query_words]

    def matched(section: Section) -> int:
        present = set(terms.index_terms(section.text))
        return sum(1 for word_forms in wanted if word_forms & present)

    return max(piece.sections, key=lambda section: (matched(section), -piece.sections.index(section)))


def _snippet(text: str, query_words: "list[str]") -> str:
    if len(text) <= SNIPPET_CHARS:
        return text
    # Found in a normalised copy, sliced from the original: normalising drops
    # niqqud, so the copy is shorter and its offsets must be mapped back.
    folded, origin = _folded_with_offsets(text)
    found = [folded.find(form) for word in query_words for form in terms.forms(word)]
    positions = [origin[p] for p in found if p >= 0]
    positions = [p for p in positions if p >= 0]
    start = max(0, min(positions) - SNIPPET_CHARS // 3) if positions else 0
    end = min(len(text), start + SNIPPET_CHARS)
    start = max(0, end - SNIPPET_CHARS)
    # Snap inward to whole words, so a snippet never opens on "...n, so I".
    if start > 0:
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < end else start
    if end < len(text):
        space = text.rfind(" ", start, end)
        end = space if space > start else end
    snippet = text[start:end].strip()
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def _folded_with_offsets(text: str) -> "tuple[str, list[int]]":
    pieces, origin = [], []
    for position, character in enumerate(text):
        folded = terms.normalize(character)
        pieces.append(folded)
        origin.extend([position] * len(folded))
    return "".join(pieces), origin


def topics(documents: Sequence[Document], *, per_document: int = TOPICS_PER_DOCUMENT) -> "dict[str, list[str]]":
    """The terms each document is most about, relative to the rest of the
    project (tf-idf over words and recurring two-word phrases). Shown in the
    surface form the document itself uses most."""
    vocabularies = {document.doc_id: _topic_counts(document) for document in documents}
    document_frequency: Counter = Counter()
    for counts in vocabularies.values():
        document_frequency.update(counts.keys())
    total = len(vocabularies)
    result: "dict[str, list[str]]" = {}
    for document in documents:
        counts = vocabularies[document.doc_id]
        weighted = {
            term: count * math.log(1 + total / document_frequency[term]) * (1.5 if " " in term else 1.0)
            for term, count in counts.items()
        }
        ranked = sorted(weighted.items(), key=lambda item: (-item[1], item[0]))
        chosen: "list[str]" = []
        for term, _ in ranked:
            words = set(term.split(" "))
            if any(words <= set(other.split(" ")) or set(other.split(" ")) <= words for other in chosen):
                continue
            chosen.append(term)
            if len(chosen) >= per_document:
                break
        result[document.doc_id] = [terms.display(term) for term in chosen]
    return result


def project_topics(documents: Sequence[Document], *, limit: int = 20) -> "list[tuple[str, int]]":
    """What the project keeps coming back to: terms that several documents
    use repeatedly, as (term, number of documents). Ranked by how many
    documents, then by how much they are used; a term only one document uses
    is that document's topic, not the project's."""
    document_frequency: Counter = Counter()
    usage: Counter = Counter()
    for document in documents:
        counts = _topic_counts(document)
        document_frequency.update(counts.keys())
        usage.update(counts)
    shared = [term for term, n in document_frequency.items() if n >= 2]
    ranked = sorted(shared, key=lambda term: (-document_frequency[term], -usage[term], term))
    phrases = {term for term in ranked if " " in term}
    # A word inside a shared phrase is shown as the phrase, once.
    covered = {word for phrase in phrases for word in phrase.split(" ")}
    chosen = [term for term in ranked if " " in term or term not in covered][:limit]
    return [(terms.display(term), document_frequency[term]) for term in chosen]


def _topic_counts(document: Document) -> Counter:
    counts: Counter = Counter()
    bigrams: Counter = Counter()
    for section in document.sections:
        words = terms.words(section.text)
        for word in words:
            if terms.is_topic_word(word):
                counts[word] += 1
        for left, right in zip(words, words[1:]):
            if terms.is_topic_word(left) and terms.is_topic_word(right):
                bigrams[f"{left} {right}"] += 1
    counts.update({phrase: n for phrase, n in bigrams.items() if n >= MIN_BIGRAM_COUNT})
    if sum(counts.values()) < SHORT_DOCUMENT_WORDS:
        return counts
    return Counter({term: n for term, n in counts.items() if n >= MIN_TOPIC_COUNT})
