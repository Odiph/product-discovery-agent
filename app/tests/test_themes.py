"""Unbound themes (app/coach/themes.py, app/themes_cli.py): a planted pattern
across interviews is found, and a one-off is not."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import main as main_mod
from app.coach import themes as themes_mod


def _ref(fact_id, session_id, claim, bearings=()):
    return SimpleNamespace(fact_id=fact_id, session_id=session_id, claim=claim, bearings=tuple(bearings))


PLANTED = [
    _ref("f1", "S1", "She fills the matchmaking queue time by checking her build status."),
    _ref("f2", "S2", "He checks build status during the matchmaking queue, every evening."),
    _ref("f3", "S3", "The queue wait is when she glances at the build status on her phone."),
]
NOISE = [
    _ref("n1", "S1", "He prefers a mechanical keyboard with brown switches."),
    _ref("n2", "S2", "She plays mostly on weekends with her sister."),
    _ref("n3", "S3", "He mentioned his monitor is twenty seven inches."),
]


def test_a_planted_pattern_across_interviews_is_found_and_one_offs_are_not():
    (theme,) = themes_mod.unbound_themes(PLANTED + NOISE)
    assert set(theme.fact_ids) == {"f1", "f2", "f3"}
    assert theme.sessions == ("S1", "S2", "S3")
    assert set(theme.label) >= {"build", "queue"}


def test_a_pattern_inside_one_interview_is_not_a_theme():
    same_session = [_ref(r.fact_id, "S1", r.claim) for r in PLANTED]
    assert themes_mod.unbound_themes(same_session) == ()


def test_claims_that_bear_on_a_hypothesis_are_left_to_standing():
    # Padded with unrelated unbound claims, so the common-word ceiling cannot
    # be what hides the pattern: only the bearing can.
    bound = [_ref(r.fact_id, r.session_id, r.claim, [("h1", "supports")]) for r in PLANTED]
    padding = [_ref("p1", "S1", "Her cat sleeps on the router."), _ref("p2", "S2", "He commutes by ferry."),
               _ref("p3", "S3", "She learned piano as a child."), _ref("p4", "S4", "His desk faces a window.")]
    assert themes_mod.unbound_themes(bound + NOISE + padding) == ()


def test_one_shared_word_is_a_coincidence_not_a_theme():
    claims = [_ref("a", "S1", "She bought a new keyboard for travel."),
              _ref("b", "S2", "His keyboard broke during a tournament.")]
    padding = [_ref("p1", "S3", "Her cat sleeps on the router."), _ref("p2", "S4", "He commutes by ferry.")]
    assert themes_mod.unbound_themes(claims + padding) == ()


def test_a_word_most_claims_use_does_not_glue_unrelated_claims():
    endings = ["felt slow in the settings", "would help during loading screens", "pricing seemed fair",
               "crashed once on a laptop", "needs a dark theme", "hid the minimap", "ran fine at launch",
               "took a while to install", "covered the chat window", "was found through a friend"]
    claims = [_ref(f"c{i}", f"S{i}", f"Claudictive overlay {text}.") for i, text in enumerate(endings)]
    assert themes_mod.unbound_themes(claims) == ()


def test_reporting_verbs_are_not_shared_content():
    claims = [
        _ref("a", "S1", "The interviewee mentioned she described her commute."),
        _ref("b", "S2", "The interviewee mentioned he described his garden."),
    ]
    assert themes_mod.unbound_themes(claims) == ()


def test_hebrew_claims_group_through_their_particles():
    claims = [
        _ref("h1", "S1", "בזמן ההמתנה בתור היא בודקת את הבילד בטלפון"),
        _ref("h2", "S2", "הוא בודק את הבילד כשהוא בתור למשחק"),
    ]
    (theme,) = themes_mod.unbound_themes(claims)
    assert theme.sessions == ("S1", "S2")


# --- the command ----------------------------------------------------------------------


@pytest.fixture
def node(tmp_path, monkeypatch):
    context = tmp_path / "context"
    context.mkdir()
    (context / "hypotheses.json").write_text(json.dumps([
        {"id": "h1", "statement": "x", "falsifier": "y"}]), encoding="utf-8")
    facts = [
        {"id": r.fact_id, "session_id": r.session_id, "seqs": [1], "claim": r.claim, "provenance": "evidence",
         "quoted_text": "verbatimsentinelqq", "bearings": []}
        for r in PLANTED + NOISE
    ]
    (context / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    monkeypatch.setenv("APP_CONTEXT_DIR", str(context))
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(tmp_path / "sessions"))
    return context


def test_the_command_lists_the_theme_with_its_claims_and_never_a_quote(node, capsys):
    assert main_mod.main(["themes"]) == 0
    out = capsys.readouterr().out
    assert "6 of 6 claims, from 3 interview(s), bear on no hypothesis." in out
    assert "in 3 interviews, 3 claims" in out
    assert "[f2] He checks build status" in out
    assert "verbatimsentinelqq" not in out


def test_no_corpus_says_what_to_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APP_CONTEXT_DIR", str(tmp_path / "context"))
    monkeypatch.setenv("APP_SESSIONS_ROOT", str(tmp_path / "sessions"))
    assert main_mod.main(["themes"]) == 0
    assert "extract" in capsys.readouterr().out


def test_get_themes_over_mcp_carries_claims_never_quotes(tmp_path):
    from app.mcp import tools as mcp_tools

    context = tmp_path / "projects" / "acme" / "context"
    context.mkdir(parents=True)
    (context / "facts.json").write_text(json.dumps([
        {"id": r.fact_id, "session_id": r.session_id, "seqs": [1], "claim": r.claim, "provenance": "evidence",
         "quoted_text": "verbatimsentinelqq", "bearings": []}
        for r in PLANTED + NOISE
    ]), encoding="utf-8")
    payload = mcp_tools.call_tool("get_themes", {"project": "acme"}, repo_root=tmp_path)
    (theme,) = payload["themes"]
    assert {f["fact_id"] for f in theme["facts"]} == {"f1", "f2", "f3"}
    assert "verbatimsentinelqq" not in json.dumps(payload)
    assert "extraction" in payload


# --- regressions from the 2026-10-21 review ------------------------------------------


def test_a_chain_of_pairwise_links_is_not_one_theme():
    chain = [
        _ref("c1", "S1", "apple banana cherry"),
        _ref("c2", "S2", "banana cherry delta echo"),
        _ref("c3", "S3", "delta echo foxtrot golf"),
        _ref("c4", "S4", "foxtrot golf hotel india"),
        _ref("c5", "S5", "hotel india juliet kilo"),
    ]
    for theme in themes_mod.unbound_themes(chain):
        assert not {"c1", "c5"} <= set(theme.fact_ids), "the two ends share nothing"
        assert len(theme.fact_ids) <= 3


def test_hebrew_singular_and_plural_meet_and_different_words_do_not_collide():
    words = dict(themes_mod._words("הזמנה הזמנות שירות שיר"))
    assert words["הזמנה"] & words["הזמנות"]
    assert not (words["שירות"] & words["שיר"])


def test_labels_do_not_depend_on_the_hash_seed():
    import os
    import subprocess
    import sys

    script = ("from types import SimpleNamespace as N; from app.coach import themes as t;"
              "r=[N(fact_id=str(i), session_id=f'S{i}', claim='alpha bravo charlie delta echo', bearings=())"
              " for i in range(3)]; print(t.unbound_themes(r)[0].label)")
    seen = set()
    for seed in ("1", "2", "3"):
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                                env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": "."})
        assert result.returncode == 0, result.stderr
        seen.add(result.stdout.strip())
    assert len(seen) == 1, seen


def test_a_non_string_claim_is_skipped():
    assert themes_mod.unbound_themes(PLANTED + [_ref("x", "S9", 42)])[0].fact_ids
