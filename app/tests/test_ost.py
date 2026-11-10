"""The Opportunity Solution Tree (`app/coach/ost.py`, `app/tree_cli.py`, the
author page's tree routes, MCP `get_tree`).

What these defend, in order: the two new hypothesis fields are optional and
invisible to every file written before them; the tree's file-level rules are
strict on the author save and tolerant on read; every count is
`interview_summary.standing`'s own; the four empty states read differently; a
theme becomes an opportunity only when a human writes one; and no quote
crosses any of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import main as main_mod
from app.coach import corpus as corpus_mod
from app.coach import corpus_store
from app.coach import interview_summary as summary_mod
from app.coach import ost as ost_mod
from app.coach.corpus import Bearing, Fact, Hypothesis, tree_problems
from app.mcp import tools as mcp_tools
from app.tests.test_web_author import AUTHOR_STATIC_DIR, _get_json, _post_json, _running_author_server
from app.web import author as web_author

REPO_ROOT = Path(__file__).resolve().parents[2]
QUOTE = "ost-sentinel-verbatim-quote-5e1c"


def _h(**fields):
    base = {"id": "h1", "statement": "a belief", "falsifier": "a way to be wrong"}
    return Hypothesis.model_validate({**base, **fields})


# --- the model: two optional fields, per-record rules ------------------------------------


def test_kind_must_be_one_of_the_two_or_absent():
    assert _h().kind is None
    assert _h(kind="opportunity").kind == "opportunity"
    with pytest.raises(ValidationError):
        _h(kind="outcome")


def test_only_a_solution_may_have_a_parent():
    assert _h(kind="solution", parent="o1").parent == "o1"
    for kind in (None, "opportunity"):
        with pytest.raises(ValidationError):
            _h(kind=kind, parent="o1")
    with pytest.raises(ValidationError):
        _h(kind="solution", parent="  ")


def test_an_unclassified_hypothesis_dumps_without_the_new_keys():
    # The serializer is what keeps old files byte-stable on save; without it
    # every hypothesis grows `"kind": null, "parent": null`.
    assert set(_h().model_dump()) == {
        "id", "statement", "falsifier", "state", "criterion", "criterion_registered_after",
    }
    assert _h(kind="solution", parent="o1").model_dump()["parent"] == "o1"


# --- the file-level rules: parent exists, is an opportunity, no cycles ----------------------


def test_a_sound_tree_has_no_problems():
    assert tree_problems([_h(id="o1", kind="opportunity"), _h(id="s1", kind="solution", parent="o1")]) == ()


@pytest.mark.parametrize("parent_kind", [None, "solution"])
def test_a_parent_that_is_not_an_opportunity_is_named(parent_kind):
    hypotheses = [_h(id="p", kind=parent_kind), _h(id="s1", kind="solution", parent="p")]
    (problem,) = tree_problems(hypotheses)
    assert "'s1'" in problem and "not an opportunity" in problem


def test_a_dangling_parent_is_named():
    (problem,) = tree_problems([_h(id="s1", kind="solution", parent="gone")])
    assert "'gone'" in problem and "not a hypothesis" in problem


def test_cycles_cannot_be_written():
    # Two solutions parenting each other, and a self-parent: the "parent must
    # be an opportunity" rule is what rules out every cycle.
    pair = [_h(id="a", kind="solution", parent="b"), _h(id="b", kind="solution", parent="a")]
    assert len(tree_problems(pair)) == 2
    assert len(tree_problems([_h(id="a", kind="solution", parent="a")])) == 1


def test_a_classified_node_needs_a_statement():
    (problem,) = tree_problems([_h(id="o1", kind="opportunity", statement="  ")])
    assert "'o1'" in problem and "statement" in problem
    assert tree_problems([_h(statement="")]) == (), "an OLD unclassified blank stays legal"


# --- old files: unchanged on load and on save --------------------------------------------


def test_the_example_files_load_and_dump_with_the_same_keys():
    raw = json.loads((REPO_ROOT / "context" / "hypotheses.example.json").read_text(encoding="utf-8"))
    for entry in raw:
        dumped = Hypothesis.model_validate(entry).model_dump()
        assert {k: dumped[k] for k in entry} == entry
        assert "kind" not in dumped and "parent" not in dumped


def test_an_old_file_saves_through_the_author_page_byte_for_byte_as_before(tmp_path):
    """Saved once, then again unchanged: the bytes must be identical, and must
    carry no tree key -- an old project opened and saved stays an old file."""
    context = tmp_path / "context"
    context.mkdir()
    old = json.loads((REPO_ROOT / "context" / "hypotheses.example.json").read_text(encoding="utf-8"))
    app = web_author.create_author_app(context_dir=context, static_dir=AUTHOR_STATIC_DIR)
    with _running_author_server(app) as base:
        assert _post_json(base + "/api/hypotheses", old)[0] == 200
        first = (context / "hypotheses.json").read_bytes()
        assert _post_json(base + "/api/hypotheses", _get_json(base + "/api/hypotheses"))[0] == 200
        second = (context / "hypotheses.json").read_bytes()
    assert first == second
    for entry in json.loads(first):
        assert "kind" not in entry and "parent" not in entry


# --- the outcome file ----------------------------------------------------------------------


def test_outcome_reads_missing_present_and_unreadable(tmp_path):
    assert ost_mod.read_outcome(tmp_path).state == ost_mod.OUTCOME_MISSING
    (tmp_path / "outcome.json").write_text("{not json", encoding="utf-8")
    assert ost_mod.read_outcome(tmp_path).state == ost_mod.OUTCOME_UNREADABLE
    (tmp_path / "outcome.json").write_text('["wrong shape"]', encoding="utf-8")
    assert ost_mod.read_outcome(tmp_path).state == ost_mod.OUTCOME_UNREADABLE
    (tmp_path / "outcome.json").write_text('{"outcome": "  "}', encoding="utf-8")
    assert not ost_mod.read_outcome(tmp_path).is_set, "a saved blank is a cleared outcome"
    (tmp_path / "outcome.json").write_text('{"outcome": "Cut churn"}', encoding="utf-8")
    assert ost_mod.read_outcome(tmp_path).is_set


@pytest.mark.parametrize("body", [[], {}, {"outcome": 3}, {"outcome": "x", "extra": 1}, {"outcome": "x" * 501}])
def test_an_invalid_outcome_payload_is_refused(body):
    assert ost_mod.validate_outcome_payload(body)[0] is None


# --- the tree over a real corpus: the seam --------------------------------------------------


def _fact(fact_id, session_id, claim, bearings=()):
    return Fact(
        id=fact_id, session_id=session_id, seqs=(1,), claim=claim, provenance="evidence",
        quoted_text=QUOTE,
        bearings=tuple(Bearing(hypothesis_id=h, stance=s) for h, s in bearings),
    )


HYPOTHESES = [
    {"id": "o1", "statement": "ייצוא לגיליון הוא כאב", "falsifier": "nobody exports", "kind": "opportunity"},
    {"id": "s1", "statement": "one-click export", "falsifier": "they ignore it", "kind": "solution",
     "parent": "o1"},
    {"id": "h3", "statement": "pricing is fine", "falsifier": "they complain about price"},
]

FACTS = [
    # o1: supported by THREE claims from TWO interviews (S1 twice), contradicted in one.
    _fact("f1", "S1", "rebuilds the export by hand", [("o1", "supports")]),
    _fact("f2", "S1", "export again by hand on Friday", [("o1", "supports")]),
    _fact("f3", "S2", "export is a daily chore", [("o1", "supports")]),
    _fact("f4", "S3", "never exports anything", [("o1", "undermines")]),
    _fact("f5", "S2", "would click one export button", [("s1", "supports")]),
    # A recurring pattern no hypothesis predicted, in Hebrew.
    _fact("u1", "S1", "התור במשחק ארוך ומשעמם מאוד"),
    _fact("u2", "S2", "התור במשחק ארוך ומשעמם בערב"),
    _fact("u3", "S3", "המקלדת שלו חדשה"),
]


@pytest.fixture
def node(tmp_path, monkeypatch):
    context = tmp_path / "context"
    context.mkdir()
    (tmp_path / "sessions").mkdir()
    monkeypatch.setenv("APP_CONTEXT_DIR", str(context))
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(tmp_path / "sessions"))
    (context / "hypotheses.json").write_text(json.dumps(HYPOTHESES, ensure_ascii=False), encoding="utf-8")
    return context


def _tree(context):
    hypotheses = corpus_mod.load_hypotheses(context, missing_ok=True)
    exists = (context / "facts.json").is_file()
    facts = corpus_mod.load_facts(context, sessions_root=None) if exists else ()
    refs = [summary_mod.fact_ref(f, project="") for f in facts]
    return ost_mod.build_tree(hypotheses, refs, outcome=ost_mod.read_outcome(context), corpus_exists=exists), hypotheses, refs


def test_every_count_is_standings_own_over_a_real_facts_file(node):
    corpus_store.write_facts(node, FACTS)
    tree, hypotheses, refs = _tree(node)
    (o1,) = tree.opportunities
    assert (o1.supporting_interviews, o1.contrary_interviews, o1.total_interviews) == (2, 1, 3), (
        "per INTERVIEW: S1's two supporting claims count once"
    )
    for node_ in (o1, o1.children[0], *tree.unclassified):
        h = next(x for x in hypotheses if x.id == node_.hypothesis_id)
        s = summary_mod.standing(h, refs, project="")
        assert (node_.supporting_interviews, node_.contrary_interviews, node_.unclear_interviews,
                node_.total_interviews) == (s.supporting_interviews, s.contrary_interviews,
                                            s.unclear_interviews, s.total_interviews)
    assert [c.hypothesis_id for c in o1.children] == ["s1"]
    assert [n.hypothesis_id for n in tree.unclassified] == ["h3"]


def test_counts_move_after_an_extract_and_the_structure_does_not(node):
    corpus_store.write_facts(node, FACTS[:1])
    before, _, _ = _tree(node)
    corpus_store.write_facts(node, FACTS)
    after, _, _ = _tree(node)
    assert before.opportunities[0].supporting_interviews == 1
    assert after.opportunities[0].supporting_interviews == 2
    assert [o.hypothesis_id for o in before.opportunities] == [o.hypothesis_id for o in after.opportunities]


def test_a_dangling_parent_reads_as_unclassified_and_never_raises(node):
    broken = HYPOTHESES[:1] + [{**HYPOTHESES[1], "parent": "gone"}]
    (node / "hypotheses.json").write_text(json.dumps(broken), encoding="utf-8")
    tree, _, _ = _tree(node)
    assert tree.opportunities[0].children == ()
    assert [n.hypothesis_id for n in tree.unclassified] == ["s1"]
    assert tree.problems


# --- the CLI ----------------------------------------------------------------------------


def _run(capsys):
    assert main_mod.main(["tree"]) == 0
    return capsys.readouterr().out


def test_the_cli_renders_the_tree_with_hebrew_labels_and_no_quote(node, capsys):
    corpus_store.write_facts(node, FACTS)
    (node / "outcome.json").write_text(json.dumps({"outcome": "להפחית נטישה"}), encoding="utf-8")
    out = _run(capsys)
    assert "OUTCOME: להפחית נטישה" in out
    assert "OPPORTUNITY [o1] ייצוא לגיליון הוא כאב" in out
    assert "supports in 2, contradicts in 1" in out
    assert out.index("[o1]") < out.index("SOLUTION [s1]") < out.index("Unclassified") < out.index("[h3]")
    assert "Candidate opportunities (not in the tree):" in out
    assert "in 2 interviews" in out and "Promote one: `python -m app author`" in out
    assert QUOTE not in out


def test_no_outcome_and_no_hypotheses_say_so(node, capsys):
    (node / "hypotheses.json").unlink()
    out = _run(capsys)
    assert "OUTCOME: not set" in out
    assert "No hypotheses yet" in out


def test_nothing_extracted_is_not_the_same_as_no_evidence(node, capsys):
    out = _run(capsys)
    assert "Nothing extracted yet" in out
    assert "themes come from extracted claims" in out


def test_a_real_tree_says_how_many_interviews_it_counts(node, capsys):
    corpus_store.write_facts(node, FACTS)
    out = _run(capsys)
    assert "Nothing extracted yet" not in out
    assert "Evidence from 3 extracted interview(s)" in out


def test_an_unreadable_outcome_is_not_reported_as_unset(node, capsys):
    (node / "outcome.json").write_text("{", encoding="utf-8")
    assert "could not be read" in _run(capsys)


# --- the author page: outcome, candidates, promote-on-save -----------------------------------


@pytest.fixture
def author(node):
    app = web_author.create_author_app(context_dir=node, static_dir=AUTHOR_STATIC_DIR)
    with _running_author_server(app) as base:
        yield base


def test_outcome_saves_and_reads_back(author, node):
    assert _post_json(author + "/api/outcome", {"outcome": "  Cut churn  "}) == (200, {"saved": 1})
    assert _get_json(author + "/api/outcome") == {"outcome": "Cut churn", "state": "present"}
    assert _get_json(author + "/api/state")["outcome"] == "present"


def test_an_unreadable_outcome_is_never_overwritten(author, node):
    (node / "outcome.json").write_text("{", encoding="utf-8")
    status, _ = _post_json(author + "/api/outcome", {"outcome": "x"})
    assert status == 409
    assert (node / "outcome.json").read_text(encoding="utf-8") == "{"


def test_candidates_are_labels_counts_and_claims_never_quotes(author, node):
    corpus_store.write_facts(node, FACTS)
    body = _get_json(author + "/api/candidates")
    assert body["facts"] == "present"
    assert [c["interviews"] for c in body["candidates"]] == [2]
    assert QUOTE not in json.dumps(body, ensure_ascii=False)


def test_candidates_without_a_corpus_say_missing(author):
    assert _get_json(author + "/api/candidates") == {"facts": "missing", "candidates": []}


def test_promoting_with_a_written_statement_and_falsifier_saves_an_opportunity(author, node):
    current = _get_json(author + "/api/hypotheses")
    new = {"id": "o2", "statement": "the queue is dead time", "falsifier": "nobody waits", "kind": "opportunity"}
    assert _post_json(author + "/api/hypotheses", current + [new])[0] == 200
    saved = corpus_mod.load_hypotheses(node, missing_ok=False)
    assert saved[-1].kind == "opportunity"


@pytest.mark.parametrize("bad", [
    {"id": "o2", "statement": "", "falsifier": "nobody waits", "kind": "opportunity"},
    {"id": "o2", "statement": "the queue", "kind": "opportunity"},
    {"id": "s2", "statement": "a button", "falsifier": "f", "kind": "solution", "parent": "h3"},
    {"id": "s2", "statement": "a button", "falsifier": "f", "kind": "solution", "parent": "gone"},
    {"id": "s2", "statement": "a button", "falsifier": "f", "kind": "solution", "parent": "s2"},
])
def test_the_save_path_refuses_an_invalid_tree_and_writes_nothing(author, node, bad):
    before = (node / "hypotheses.json").read_bytes()
    status, body = _post_json(author + "/api/hypotheses", _get_json(author + "/api/hypotheses") + [bad])
    assert status == 400
    assert repr(bad["id"]) in body["error"]
    assert (node / "hypotheses.json").read_bytes() == before


def test_reclassifying_an_opportunity_out_from_under_its_solution_is_refused(author, node):
    current = _get_json(author + "/api/hypotheses")
    current[0] = {k: v for k, v in current[0].items() if k != "kind"}
    status, body = _post_json(author + "/api/hypotheses", current)
    assert status == 400 and "'s1'" in body["error"]


def test_a_re_parent_keeps_the_criterion_boundary(author, node, tmp_path):
    # Moving a solution is not a criterion edit, so its pre-registration
    # boundary must not move (the stamping rule keys on criterion text only).
    (tmp_path / "sessions" / "S1").mkdir()
    current = _get_json(author + "/api/hypotheses")
    current[1]["criterion"] = "3 of 5 click it"
    _post_json(author + "/api/hypotheses", current)
    (tmp_path / "sessions" / "S2").mkdir()
    current = _get_json(author + "/api/hypotheses")
    current.append({"id": "o9", "statement": "another pain", "falsifier": "f", "kind": "opportunity"})
    current[1]["parent"] = "o9"
    assert _post_json(author + "/api/hypotheses", current)[0] == 200
    saved = {h.id: h for h in corpus_mod.load_hypotheses(node, missing_ok=False)}
    assert saved["s1"].parent == "o9"
    assert saved["s1"].criterion_registered_after == ("S1",)


# --- MCP get_tree: what crosses ---------------------------------------------------------------


def _mcp_tree(tmp_path):
    context = tmp_path / "projects" / "acme" / "context"
    context.mkdir(parents=True)
    (context / "hypotheses.json").write_text(json.dumps(HYPOTHESES, ensure_ascii=False), encoding="utf-8")
    (context / "outcome.json").write_text(json.dumps({"outcome": "Cut churn"}), encoding="utf-8")
    corpus_store.write_facts(context, FACTS)
    return mcp_tools.call_tool("get_tree", {"project": "acme"}, repo_root=tmp_path)


def test_get_tree_carries_exactly_these_keys(tmp_path):
    payload = _mcp_tree(tmp_path)
    assert set(payload) == {
        "project", "status", "outcome", "opportunities", "unclassified", "candidates", "problems",
        "errors", "extraction", "unextracted_projects",
    }
    node_keys = {
        "hypothesis_id", "kind", "statement", "state", "is_scorable", "supporting_interviews",
        "contrary_interviews", "unclear_interviews", "total_interviews", "solutions",
    }
    assert set(payload["opportunities"][0]) == node_keys
    assert set(payload["opportunities"][0]["solutions"][0]) == node_keys
    assert set(payload["candidates"][0]) == {"label", "interviews", "claims"}
    assert isinstance(payload["candidates"][0]["claims"], int), "a count, never the claim text"
    assert payload["outcome"] == {"state": "present", "text": "Cut churn"}
    assert payload["status"] == "tree"


def test_get_tree_emits_no_quote_and_no_claim_text(tmp_path):
    raw = json.dumps(_mcp_tree(tmp_path), ensure_ascii=False)
    assert QUOTE not in raw
    for fact in FACTS:
        assert fact.claim not in raw, f"claim text crossed: {fact.claim}"
