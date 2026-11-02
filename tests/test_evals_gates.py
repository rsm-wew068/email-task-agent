"""E2 must pass 100%; E1-U wrong-link counting must behave."""

from __future__ import annotations

from email_task_agent.evals.e1u import (
    build_scenarios,
    count_wrong_links,
    run_scenario,
    scripted_extractor,
)
from email_task_agent.evals.e2 import _run as run_e2
from email_task_agent.evals.e2 import build_scenarios as build_e2_scenarios


def test_e2_all_recorded_scenarios_pass():
    failures = []
    for scenario in build_e2_scenarios():
        ok, problems = run_e2(scenario)
        if not ok:
            failures.append((scenario.name, problems))
    assert not failures, f"E2 gate is 100%; failures: {failures}"


def test_e1u_perfect_extractor_has_zero_wrong_links():
    assert count_wrong_links(build_scenarios(), scripted_extractor("perfect")) == 0


def test_e1u_wrong_extractor_counted():
    scenarios = build_scenarios()
    wrong = count_wrong_links(scenarios, scripted_extractor("wrong"))
    assert wrong == len(scenarios)  # every update lands on the wrong task


def test_e1u_count_never_goes_up_vs_recorded_baseline(tmp_path):
    import json

    from email_task_agent.evals.e1u import main as e1u_main

    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"variant": "perfect", "wrong_links": 0}))
    assert e1u_main(["--extractor", "scripted:perfect", "--baseline", str(baseline)]) == 0
    assert e1u_main(["--extractor", "scripted:wrong", "--baseline", str(baseline)]) == 1


def test_run_scenario_counts_wrong_link_individually():
    scenarios = build_scenarios()
    assert run_scenario(scenarios[0], scripted_extractor("wrong")) == 1
