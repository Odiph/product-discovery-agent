"""The input-token estimate every paid call previews before `--yes`.

Calibrated on the one billed call on record (MEASUREMENTS.md, 2026-11-12):
the follow-up judge's request, 24,285 characters of JSON of which 3,494
Hebrew, billed 11,590 input tokens. The old flat four characters a token
said 6,071.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import extract_all
from app.coach import coverage_judge, follow_judge, prompt_judge, token_estimate, topics

APP = Path(__file__).resolve().parents[1]
BILLED = 11_590
OLD_RATE = re.compile(r"\bCHARS_PER_TOKEN\b|\+/-15%|four characters a\s+token")


def _request(ascii_chars: int, hebrew_chars: int, *, tools: bool = True) -> dict:
    # json.dumps of this dict adds a fixed wrapper; size the content so the
    # whole dump has exactly the counts asked for.
    request: dict = {"messages": [{"role": "user", "content": ""}]}
    if tools:
        request["tools"] = [{"name": "t"}]
    wrapper = len(token_estimate.dumped(request))
    request["messages"][0]["content"] = "a" * (ascii_chars - wrapper) + "א" * hebrew_chars
    return request


def test_the_billed_follow_up_call_is_reproduced_within_two_percent():
    estimate = token_estimate.estimate(_request(24_285 - 3_494, 3_494))
    assert abs(estimate - BILLED) / BILLED < 0.02, estimate


def test_a_hebrew_letter_costs_more_than_an_ascii_one():
    assert (token_estimate.estimate(_request(2_000, 1_000, tools=False))
            > token_estimate.estimate(_request(3_000, 0, tools=False)) * 1.5)


def test_tools_add_their_fixed_overhead_and_nothing_else_does():
    with_tools = token_estimate.estimate(_request(5_000, 0))
    without = token_estimate.estimate(_request(5_000, 0, tools=False))
    assert with_tools - without == token_estimate.TOOL_OVERHEAD_TOKENS


@pytest.mark.parametrize("estimate_fn", [
    prompt_judge.estimate_input_tokens, follow_judge.estimate_input_tokens,
    coverage_judge.estimate_input_tokens, topics.estimate_input_tokens,
], ids=["prompted", "followed", "coverage", "topics"])
def test_every_judge_preview_uses_the_shared_estimate(estimate_fn):
    request = _request(4_000, 700)
    assert estimate_fn(request) == token_estimate.estimate(request)


def test_extract_all_uses_the_shared_estimate(monkeypatch):
    request = _request(4_000, 700)
    monkeypatch.setattr(extract_all, "assemble_extract_request", lambda **_: request)
    assert extract_all._estimate_tokens([], [], max_tokens=1) == token_estimate.estimate(request)


def test_no_preview_keeps_its_own_flat_rate_or_the_old_accuracy_claim():
    offenders = [str(path.relative_to(APP)) for path in APP.rglob("*.py")
                 if "tests" not in path.parts
                 and OLD_RATE.search(path.read_text(encoding="utf-8"))]
    assert offenders == []
