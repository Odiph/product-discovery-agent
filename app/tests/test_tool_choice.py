"""`reasoning_client.tool_choice`: the models that 400 on a forced tool get `auto`."""

import pytest

from app.coach import reasoning_client as rc


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-opus-5-5", "anthropic/claude-sonnet-5.5",
                                   "anthropic/claude-opus-5.5", "claude-fable-5-2", "claude-mythos-5-1"])
def test_models_that_refuse_a_forced_tool_get_auto(model):
    assert rc.tool_choice(model, "report") == {"type": "auto"}


@pytest.mark.parametrize("model", ["claude-haiku-4-5-20251001", "claude-opus-5", "claude-sonnet-5",
                                   "google/gemini-2.5-flash", "anthropic/claude-opus-4.8", "claude-haiku-5-5"])
def test_every_other_model_is_forced(model):
    assert rc.tool_choice(model, "report") == {"type": "tool", "name": "report"}


def test_no_call_site_forces_a_tool_by_hand():
    # A literal forced choice bypasses the helper and 400s on the models above.
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    offenders = [str(p.relative_to(root)) for d in ("app", "benchmark") for p in (root / d).rglob("*.py")
                 if "tests" not in p.parts and '{"type": "tool", "name"' in p.read_text(encoding="utf-8")
                 and p.name != "reasoning_client.py"]
    assert offenders == []


def test_the_judge_model_falls_back_to_the_extract_model(monkeypatch):
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.setenv("EXTRACT_MODEL", "google/gemini-2.5-flash")
    assert rc.resolve_judge_model() == "google/gemini-2.5-flash"
    monkeypatch.setenv("JUDGE_MODEL", "anthropic/claude-sonnet-5.5")
    assert rc.resolve_judge_model() == "anthropic/claude-sonnet-5.5"
    assert rc.resolve_extract_model() == "google/gemini-2.5-flash"
