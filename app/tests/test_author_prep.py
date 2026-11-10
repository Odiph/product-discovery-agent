"""`prep`'s proposals, offered on the `author` page (backlog B4).

`GET /api/prep` returns the survey questions `prep` would change, each with
its reason. It writes nothing: accepting one changes the survey ON THE PAGE,
and the operator's own "Save survey" is still the one thing that writes
`context/survey.json` (gate 19's single-writer rule, unchanged).
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.coach import prep as prep_mod
from app.tests.test_prep import node  # noqa: F401 -- the same two-interview project `prep` is tested on
from app.web import author as web_author
from app.tests.test_web_author import AUTHOR_STATIC_DIR


def _client(context_dir) -> TestClient:
    app = web_author.create_author_app(context_dir=context_dir, static_dir=AUTHOR_STATIC_DIR)
    return TestClient(app, base_url="http://127.0.0.1")


def test_the_page_is_offered_exactly_what_prep_would_change(node):  # noqa: F811
    response = _client(node).get("/api/prep")
    assert response.status_code == 200
    assert response.json() == {"proposals": [{
        "item_id": "q2",
        "text": "What did you do next?",
        "action": prep_mod.MOVE_EARLIER,
        "reason": "never asked in the 2 interviews that had it: move it earlier, or drop it if it no longer matters",
    }], "survey": "present"}


def test_asking_writes_nothing(node):  # noqa: F811
    before = {p.name: p.read_bytes() for p in node.iterdir()}
    _client(node).get("/api/prep")
    assert {p.name: p.read_bytes() for p in node.iterdir()} == before


def test_a_fresh_node_has_no_proposals(tmp_path):
    (tmp_path / "context").mkdir()
    assert _client(tmp_path / "context").get("/api/prep").json() == {"proposals": [], "survey": "missing"}


def test_a_damaged_survey_proposes_nothing_rather_than_guessing(node):  # noqa: F811
    (node / "survey.json").write_text("{broken", encoding="utf-8")
    assert _client(node).get("/api/prep").json() == {"proposals": [], "survey": "unreadable"}


def test_the_prep_read_is_guarded_like_every_other_route(node):  # noqa: F811
    app = web_author.create_author_app(context_dir=node, static_dir=AUTHOR_STATIC_DIR)
    assert TestClient(app, base_url="http://evil.example").get("/api/prep").status_code == 403


def test_the_cli_and_the_page_judge_the_same_way(node, capsys):  # noqa: F811
    from app import main as main_mod

    assert main_mod.main(["prep"]) == 0
    out = capsys.readouterr().out
    for proposal in _client(node).get("/api/prep").json()["proposals"]:
        assert f"{proposal['action']}: {proposal['reason']}" in out


def test_proposals_are_plain_json(node):  # noqa: F811
    body = _client(node).get("/api/prep").text
    assert json.loads(body)["proposals"][0]["item_id"] == "q2"


def test_a_survey_that_is_not_utf8_proposes_nothing_rather_than_failing(node):  # noqa: F811
    (node / "survey.json").write_bytes(b"\xff\xfe[not utf8")
    response = _client(node).get("/api/prep")
    assert response.status_code == 200
    assert response.json() == {"proposals": [], "survey": "unreadable"}
