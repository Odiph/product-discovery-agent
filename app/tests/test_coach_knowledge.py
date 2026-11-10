"""The coach knows its stuff: the coach digest in the live prompt.

The notes `kb digest` made from the project's research and code go into the
generate stage's cached prefix, last, under a header saying what they are
(background, not interview evidence, not instructions). With no notes the
prompt is byte-identical to before, pinned by the same hash B5 pinned.
"""

from __future__ import annotations

import hashlib
import inspect
import json

import pytest

from app import main as main_mod
from app.coach import generate, prompts
from app.coach.coverage import CoverageState
from app.coach.pipeline import SuggestionPipeline
from app.coach.stub import StubAnthropicClient
from app.kb import digest
from app.kb.document import RESEARCH, Document, Section
from app.kb.store import KnowledgeStore
from app.session.store import SessionStore, create_session_dir
from app.tests.test_coach_process import EMPTY_STATIC_SHA, _crit, _gen, _Recorder

NOTE = digest.CoachNote(text="Most teams reconcile invoices by hand.", title="Pricing study",
                        location="page 3", source_type=RESEARCH)


def _static(knowledge) -> str:
    return prompts.static_block(brief=(), hypotheses=(), process="", knowledge=knowledge)


def test_no_notes_leaves_the_prompt_byte_identical():
    assert hashlib.sha256(_static(()).encode()).hexdigest() == EMPTY_STATIC_SHA


def test_a_note_lands_last_with_its_source_and_a_header_saying_what_it_is():
    text = _static((NOTE,))
    assert text.startswith(_static(()))
    block = text[len(_static(())):]
    assert "- Most teams reconcile invoices by hand. (Pricing study, page 3)" in block
    flat = " ".join(block.split())
    assert "not evidence" in flat and "not instructions" in flat
    assert block.count(NOTE.text) == 1


@pytest.mark.parametrize("fn", [
    prompts.static_block, generate.assemble_generate_request, generate.run_generate, SuggestionPipeline.__init__,
])
def test_knowledge_is_a_required_keyword(fn):
    param = inspect.signature(fn).parameters["knowledge"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty


def test_the_live_pipeline_sends_the_notes_to_generate_only(tmp_path):
    store = SessionStore(create_session_dir(tmp_path))
    store.write_metadata({"purpose": "knowledge-test"})
    client = _Recorder(StubAnthropicClient(responses=[_gen(), _crit()]))
    state = CoverageState()
    pipeline = SuggestionPipeline(
        client=client, store=store, brief=(), survey=(), hypotheses=(), process="", knowledge=(NOTE,),
        session_start_grounding_s=0.0, coverage_state_provider=lambda: state,
        model="m", generate_timeout_s=5.0, critique_timeout_s=5.0,
        generate_max_tokens=200, critique_max_tokens=200, max_shown=3, failure_threshold=3,
        language_window_s=90.0, language_flip_margin=0.65, language_min_chars=40,
    )
    trigger = store.append_segment(
        speaker="interviewee", text="we stopped using it", audio_start_s=0.0, audio_end_s=1.0,
        ready_wall_s=1.1, detected_language="en", engine="fake",
    )
    pipeline._process(trigger)
    store.close()
    generate_request, critique_request = client.requests
    assert NOTE.text in json.dumps(generate_request, ensure_ascii=False)
    # The critic judges questions against the rubric; background facts are not its business.
    assert NOTE.text not in json.dumps(critique_request, ensure_ascii=False)


def test_the_start_query_is_the_survey_hypotheses_and_brief():
    survey = (type("S", (), {"text": "How do you reconcile?"})(),)
    hypotheses = (type("H", (), {"statement": "Invoices hurt", "falsifier": "nobody mentions it"})(),)
    brief = (type("B", (), {"id": "b1", "text": "A mid-size retailer"})(),
             type("B", (), {"id": "fact:1", "text": "a past interviewee said so"})())
    query = main_mod._knowledge_query(brief=brief, survey=survey, hypotheses=hypotheses)
    assert "reconcile" in query and "Invoices hurt" in query and "retailer" in query
    # Facts from past interviews are not what the background is chosen by.
    assert "past interviewee" not in query


def test_start_loads_the_notes_and_warns_about_stale_ones(tmp_path, capsys):
    node = tmp_path / "acme"
    store = KnowledgeStore.for_node(node)
    document = Document(source_type=RESEARCH, origin="/p.md", title="Pricing study",
                        sections=(Section(text="Invoices are reconciled by hand.", location="line 1"),))
    store.put(document)
    digest.save(node / "knowledge", (
        digest.Entry(document.doc_id, document.content_hash, RESEARCH, "Pricing study",
                     (digest.Point("Most teams reconcile invoices by hand.", "line 1"),)),
        digest.Entry("deadbeef0000", "x", RESEARCH, "Removed", (digest.Point("Gone.", "line 1"),)),
    ))
    notes = main_mod._load_coach_knowledge(node / "context", "invoices")
    assert [n.text for n in notes] == ["Most teams reconcile invoices by hand."]
    assert "kb digest" in capsys.readouterr().out


def test_a_damaged_digest_never_stops_an_interview(tmp_path, capsys):
    knowledge = tmp_path / "acme" / "knowledge"
    knowledge.mkdir(parents=True)
    digest.digest_path(knowledge).write_text("{broken", encoding="utf-8")
    assert main_mod._load_coach_knowledge(tmp_path / "acme" / "context", "q") == ()
    assert "kb digest" in capsys.readouterr().err


def test_an_unreadable_knowledge_base_never_stops_an_interview(tmp_path, monkeypatch, capsys):
    def broken(*_args, **_kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(digest, "coach_notes", broken)
    assert main_mod._load_coach_knowledge(tmp_path / "acme" / "context", "q") == ()
    assert "PermissionError" in capsys.readouterr().err
