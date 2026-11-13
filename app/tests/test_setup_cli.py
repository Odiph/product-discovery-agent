"""`python -m app setup`: a first-run check that ends in the demo or your own
project. Key presence only, never a value."""

from __future__ import annotations

from app import setup_cli

READY = {"ANTHROPIC_API_KEY": "sk-secret-123", "SONIOX_API_KEY": "sx-secret-456"}


def _render(env, **kwargs) -> str:
    options = {"python": (3, 12), "in_venv": True, "seeded": True, **kwargs}
    return "\n".join(setup_cli.render(setup_cli.checks(env, **options)))


def test_every_check_passes_on_a_ready_machine():
    results = setup_cli.checks(READY, python=(3, 12), in_venv=True, seeded=True)
    assert results and all(check.ok for check in results)


def test_a_missing_key_names_the_variable_and_never_a_value():
    out = _render(READY)
    assert "sk-secret-123" not in out and "sx-secret-456" not in out
    missing = setup_cli.checks({}, python=(3, 12), in_venv=True, seeded=False)
    model = next(check for check in missing if "ANTHROPIC_API_KEY" in check.name)
    assert not model.ok
    assert "ANTHROPIC_API_KEY" in model.next_step and "demo" in model.next_step


def test_a_local_endpoint_counts_as_a_model_key():
    results = setup_cli.checks({"COACH_BASE_URL": "http://127.0.0.1:8080/v1"},
                               python=(3, 12), in_venv=True, seeded=True)
    assert next(check for check in results if "ANTHROPIC_API_KEY" in check.name).ok


def test_old_python_and_no_venv_are_reported():
    results = {check.name: check for check in setup_cli.checks(READY, python=(3, 10), in_venv=False, seeded=True)}
    python = next(check for name, check in results.items() if name.startswith("Python"))
    venv = next(check for name, check in results.items() if "venv" in name.lower())
    assert not python.ok and "3.12" in python.next_step
    assert not venv.ok and venv.next_step


def test_it_ends_with_the_two_paths():
    lines = setup_cli.render(setup_cli.checks({}, python=(3, 12), in_venv=True, seeded=False))
    tail = "\n".join(lines[-3:])
    assert "python -m app demo --yes" in tail and "python -m app author --project" in tail
    assert "no key" in tail.lower()


def test_a_loaded_demo_points_at_the_hub_instead():
    lines = setup_cli.render(setup_cli.checks(READY, python=(3, 12), in_venv=True, seeded=True))
    assert any("python -m app hub --project claudictive-beta" in line for line in lines)
