"""The knowledge base's tokenising, retrieval and topics (app/kb/terms.py,
app/kb/index.py)."""

from __future__ import annotations

import pytest

from app.kb import index as kb_index
from app.kb import terms
from app.kb.document import CONVERSATION, EMAIL, RESEARCH, Document, Section


def _doc(origin, *texts, source_type=RESEARCH, title=None, speaker=None):
    return Document(
        source_type=source_type,
        origin=origin,
        title=title or origin,
        sections=tuple(Section(text=t, location=f"line {i}", speaker=speaker) for i, t in enumerate(texts, 1)),
    )


# --- terms ---------------------------------------------------------------------------


def test_hebrew_particles_finals_and_plurals_all_reach_the_bare_word():
    # "and when the customers" -> customer; the final mem of the plural is
    # normalised, so the stem is the same letters a reader types.
    assert "לקוח" in terms.forms(terms.normalize("והלקוחות"))
    assert "לקוח" in terms.forms(terms.normalize("לקוחים"))
    assert "לקוח" in terms.forms(terms.normalize("וכשהלקוחות"))
    assert terms.normalize("שלום") == terms.normalize("שלומ")


def test_a_short_hebrew_word_keeps_its_first_letter():
    # `בית` is "house", not `ב` + `ית`: stripping below three letters would
    # turn ordinary words into nonsense stems that match everything.
    assert terms.forms("בית") == ("בית",)


def test_english_plurals_fold_and_ss_words_do_not():
    assert "customer" in terms.forms("customers")
    assert "company" in terms.forms("companies")
    assert terms.forms("process") == ("process",)


def test_a_stopword_with_a_particle_attached_is_not_a_topic_word():
    assert not terms.is_topic_word(terms.normalize("וזה"))
    assert not terms.is_topic_word(terms.normalize("ואז"))
    assert terms.is_topic_word(terms.normalize("הדיסק"))


def test_display_restores_hebrew_final_letters():
    assert terms.display(terms.normalize("מוצרים")) == "מוצרים"
    assert terms.display("export flow") == "export flow"


# --- retrieval -----------------------------------------------------------------------


def test_a_hit_cites_the_section_that_matched_not_the_first_one():
    document = _doc("a", "Intro paragraph about nothing.", "The export broke and we used paper.", "Closing.")
    hits = kb_index.KeywordIndex([document]).search("export")
    assert len(hits) == 1
    assert hits[0].location == "line 2"
    assert "export broke" in hits[0].snippet


def test_a_hebrew_query_finds_the_word_with_particles_attached():
    document = _doc("he", "וכשהלקוחות התקשרו, אף אחד לא ענה.", "שורה אחרת לגמרי.")
    hits = kb_index.KeywordIndex([document]).search("לקוח")
    assert [h.location for h in hits] == ["line 1"]


def test_extra_forms_never_count_one_word_twice():
    # "customers" is indexed under two forms; a chunk holding it once must
    # score its BEST form, not the sum of both.
    plural = _doc("p", "customers")
    index = kb_index.KeywordIndex([plural, _doc("s", "customer"), _doc("z", "zebra")])
    best = max(index._score_form("customers")[0], index._score_form("customer")[0])
    hits = {h.doc_id: h.score for h in index.search("customers")}
    assert hits[plural.doc_id] == pytest.approx(best, abs=1e-3)


def test_more_query_words_matched_ranks_higher():
    both = _doc("both", "the export broke during onboarding")
    one = _doc("one", "the export was fine")
    hits = kb_index.KeywordIndex([one, both]).search("export onboarding")
    assert hits[0].doc_id == both.doc_id


def test_per_document_cap_and_source_type_filter():
    long_doc = _doc("long", *(f"export number {i} " + "filler " * 200 for i in range(6)))
    mail = _doc("mail", "about the export", source_type=EMAIL)
    index = kb_index.KeywordIndex([long_doc, mail])
    hits = index.search("export", per_document=2)
    assert sum(1 for h in hits if h.doc_id == long_doc.doc_id) == 2
    only_mail = index.search("export", source_types=[EMAIL])
    assert [h.doc_id for h in only_mail] == [mail.doc_id]


def test_a_query_of_only_stopwords_returns_nothing_rather_than_everything():
    index = kb_index.KeywordIndex([_doc("a", "the and of it")])
    assert index.search("the and") == []


def test_the_speaker_of_the_matching_turn_is_cited():
    conversation = Document(
        source_type=CONVERSATION, origin="c", title="call",
        sections=(Section("how do you export today?", "turn 1", "Me"),
                  Section("we export to a spreadsheet every friday", "turn 2", "Dana")),
    )
    hits = kb_index.KeywordIndex([conversation]).search("spreadsheet")
    assert (hits[0].location, hits[0].speaker) == ("turn 2", "Dana")


def test_a_long_snippet_starts_and_ends_on_whole_words():
    text = ("alpha " * 80) + "needle here " + ("omega " * 80)
    hits = kb_index.KeywordIndex([_doc("x", text)]).search("needle")
    body = hits[0].snippet.strip("…")
    assert body.split()[0] in ("alpha", "needle") and body.split()[-1] in ("omega", "here")
    assert "needle" in hits[0].snippet


def test_chunks_group_short_sections_and_never_split_one():
    document = _doc("c", *(["short"] * 5), "x" * (kb_index.CHUNK_CHARS * 2))
    chunks = kb_index.chunk(document)
    assert len(chunks[0].sections) == 5
    assert chunks[-1].sections[0].text.startswith("x")


# --- topics --------------------------------------------------------------------------


def test_topics_prefer_what_a_document_repeats_and_others_do_not():
    a = _doc("a", "spreadsheet export spreadsheet export invoice invoice the the the " * 3)
    b = _doc("b", "calendar reminder calendar reminder invoice " * 3)
    result = kb_index.topics([a, b])
    assert "spreadsheet" in " ".join(result[a.doc_id])
    assert "calendar" in " ".join(result[b.doc_id])
    assert "the" not in result[a.doc_id]


def test_project_topics_need_two_documents_and_rank_by_how_many():
    a = _doc("a", "invoice invoice export export spreadsheet spreadsheet")
    b = _doc("b", "invoice invoice export export calendar calendar")
    c = _doc("c", "invoice invoice reminder reminder")
    shared = kb_index.project_topics([a, b, c])
    assert shared[0] == ("invoice", 3)
    assert ("export", 2) in shared
    assert all(term not in ("spreadsheet", "calendar", "reminder") for term, _ in shared)


def test_a_snippet_around_pointed_hebrew_still_contains_the_match():
    pointed = "שָׁלוֹם " * 60 + "יְצִיאָה " + "עוֹד " * 60
    hits = kb_index.KeywordIndex([_doc("n", pointed)]).search("יציאה")
    assert "יְצִיאָה" in hits[0].snippet


def test_the_word_as_written_outranks_a_stripped_coincidence():
    # `משלוח` (a delivery) stripped of two "particles" is `לוח` (a board).
    delivery = _doc("d", "המשלוח הגיע באיחור")
    board = _doc("b", "הלוח היה מלא")
    hits = kb_index.KeywordIndex([board, delivery]).search("משלוח")
    assert hits[0].doc_id == delivery.doc_id
