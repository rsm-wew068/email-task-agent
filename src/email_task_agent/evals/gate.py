"""E1 regression gate (plan §9.3).

The gate fails if any gate metric drops by more than
    max(MIN_DROP_POINTS, 2 * baseline run-to-run std)
measured against the mean of the pinned baseline runs.

Units: metrics in ScorerReport are 0-1 floats, but the spec's thresholds are in
POINTS ("no regression of more than 2 F1 points", where ~100 gold tasks make
one task ≈ one point). The gate therefore works in points (metric × 100):
  allowed_points = max(2.0, 2 * baseline_std_points)
On the 0-1 scale the 2×std branch would be unreachable (max std of a 0-1
metric is 0.5 → 1 point), which is why the scaling matters.

Baseline runs: the eval is run 3 times with dataset, scorer, model and prompt
versions pinned. Std is the population std (ddof=0) of the baseline runs.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from email_task_agent.evals.scoring import GATE_METRICS

MIN_DROP_POINTS = 2.0


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    checks: list[dict]

    def summary(self) -> str:
        lines = ["PASS" if self.passed else "FAIL"]
        for c in self.checks:
            status = "ok" if c["ok"] else "DROP"
            lines.append(
                f"  {c['metric']}: {c['baseline_mean']:.2f} -> {c['current_mean']:.2f} pts "
                f"(drop {c['drop']:.2f}, allowed {c['allowed']:.2f}) {status}"
            )
        return "\n".join(lines)


def _points(runs: list[dict[str, float]], metric: str) -> list[float]:
    return [run[metric] * 100.0 for run in runs]


def gate_decision(baseline_runs: list[dict[str, float]], current_runs: list[dict[str, float]]) -> GateDecision:
    if not baseline_runs or not current_runs:
        raise ValueError("gate needs at least one baseline run and one current run")

    checks: list[dict] = []
    for metric in GATE_METRICS:
        base_values = _points(baseline_runs, metric)
        curr_values = _points(current_runs, metric)
        base_mean = statistics.fmean(base_values)
        base_std = statistics.pstdev(base_values)
        curr_mean = statistics.fmean(curr_values)
        allowed = max(MIN_DROP_POINTS, 2 * base_std)
        drop = base_mean - curr_mean
        checks.append(
            {
                "metric": metric,
                "baseline_mean": base_mean,
                "baseline_std": base_std,
                "current_mean": curr_mean,
                "allowed": allowed,
                "drop": drop,
                "ok": drop <= allowed,
            }
        )
    return GateDecision(passed=all(c["ok"] for c in checks), checks=checks)
