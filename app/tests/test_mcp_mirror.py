"""`get_mirror` over MCP: the habits cross, the words do not.

Sentinels sit in the interviewee's offer AND in the critique artifact's
verbatim question text. The positive control is the walked-past moment
itself: it must arrive (with its time and signals), or the absence of the
sentinels proves nothing.
"""

from __future__ import annotations

import json

import pytest

from app.coach.asked_store import CRITIQUE_DOC_FILENAME
from app.mcp import tools as mcp_tools

SPEECH = "intervieweesentinelqq"
QUESTION = "questionsentinelqq"
OFFER = (f"Last Tuesday I had to rebuild the whole export by hand in a spreadsheet {SPEECH}, it took "
         "me about three hours and honestly it was the most annoying part of my week")


@pytest.fixture
def repo(tmp_path):
    session = tmp_path / "projects" / "acme" / "sessions" / "20260901T100000"
    session.mkdir(parents=True)
    (session / "session.json").write_text(json.dumps({"started_at": "2026-09-01T10:00:00"}), encoding="utf-8")
    turns = [("interviewer", f"How did last week go {QUESTION}?"), ("interviewee", OFFER),
             ("interviewer", "Love it. Question seven, how do you choose a new tool?")]
    (session / "transcript.jsonl").write_text("".join(
        json.dumps({"kind": "segment", "seq": i, "speaker": sp, "text": tx, "audio_end_s": 10.0 * (i + 1)}) + "\n"
        for i, (sp, tx) in enumerate(turns)), encoding="utf-8")
    (session / CRITIQUE_DOC_FILENAME).write_text(json.dumps({
        "summary": {"judged": 2, "clean": 1, "leading": 1},
        "turns": [{"index": 0, "seqs": [0], "text": f"How did last week go {QUESTION}?"}],
    }), encoding="utf-8")
    return tmp_path


def test_habits_and_moments_cross_and_no_words_do(repo):
    payload = mcp_tools.call_tool("get_mirror", {"project": "acme"}, repo_root=repo)
    (interview,) = payload["interviews"]
    (moment,) = interview["walked_past"]
    assert moment["acknowledged"] is True and moment["at_s"] == 20.0
    assert "workaround" in moment["signals"]
    assert interview["flags"] == {"leading": 1} and interview["judged_questions"] == 2
    blob = json.dumps(payload)
    assert SPEECH not in blob and QUESTION not in blob


def test_scope_and_unknown_arguments_are_refused(repo):
    with pytest.raises(mcp_tools.ToolArgumentError):
        mcp_tools.call_tool("get_mirror", {"project": "acme", "scope": "subtree"}, repo_root=repo)
