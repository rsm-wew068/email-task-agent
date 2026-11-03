"""E1 runner: score extraction predictions against a synthetic suite.

Usage (from the repo root):
  # Smoke: score the null extractor (predicts nothing) — harness sanity check
  uv run python -m email_task_agent.evals.e1

  # Score a real extraction run
  uv run python -m email_task_agent.evals.e1 --predictions run.json

  # Record the pinned baseline (3 runs)
  uv run python -m email_task_agent.evals.e1 --predictions run.json \
      --runs 3 --record-baseline evals/baselines/e1_baseline.json

  # Gate a change against the baseline (exit 1 on failure)
  uv run python -m email_task_agent.evals.e1 --predictions run.json \
      --runs 3 --gate evals/baselines/e1_baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from email_task_agent.evals.gate import gate_decision
from email_task_agent.evals.loader import Suite, load_predictions, load_suite
from email_task_agent.evals.scoring import SCORER_VERSION, PredictedTask, ScorerReport, score_thread

DEFAULT_SUITE = "evals/data/e1_test.json"


def score_suite(suite: Suite, split: str, predictions: dict[str, list[PredictedTask]]) -> ScorerReport:
    report = ScorerReport(scorer_version=SCORER_VERSION, suite=suite.name)
    for thread in suite.split(split):
        preds = predictions.get(thread.thread_id, [])
        report.threads.append(score_thread(thread.thread_id, thread.gold, preds, thread.thread_text))
    return report


def describe_missed(suite: Suite, report: ScorerReport) -> list[str]:
    gold_by_thread = {t.thread_id: t.gold for t in suite.threads}
    lines = []
    for item in report.missed_tasks():
        g = gold_by_thread[item["thread_id"]][item["gold_index"]]
        lines.append(f"  {item['thread_id']}: missed gold task \"{g.title}\" (owner={g.owner_email})")
    return lines


def describe_invented(report: ScorerReport) -> list[str]:
    return [
        f"  {item['thread_id']}: invented task ({item['reason']}) quote=\"{item['quote']}\""
        for item in report.invented_tasks()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default=DEFAULT_SUITE)
    parser.add_argument("--split", default="test", choices=["dev", "test"])
    parser.add_argument("--predictions", help="JSON file of extraction predictions; default: null extractor")
    parser.add_argument("--runs", type=int, default=1, help="number of eval runs (pin 3 for baselines)")
    parser.add_argument("--record-baseline", metavar="PATH", help="write baseline metrics JSON")
    parser.add_argument("--gate", metavar="PATH", help="compare against baseline JSON; exit 1 on failure")
    args = parser.parse_args(argv)

    suite = load_suite(args.suite)
    predictions = load_predictions(args.predictions) if args.predictions else {}

    runs = [score_suite(suite, args.split, predictions) for _ in range(args.runs)]
    metrics_per_run = [r.metrics() for r in runs]

    print(f"Scorer {SCORER_VERSION} | suite={suite.name} split={args.split} runs={args.runs}")
    print(f"Gold tasks: {runs[0].n_gold} | Predictions: {runs[0].n_predictions}")
    mean = {k: sum(m[k] for m in metrics_per_run) / len(metrics_per_run) for k in metrics_per_run[0]}
    print(
        f"P={mean['precision']:.3f} R={mean['recall']:.3f} F1={mean['f1']:.3f} | "
        f"strict F1={mean['strict_f1']:.3f} | owner={mean['owner_accuracy']:.3f} "
        f"due={mean['due_accuracy']:.3f} status={mean['status_accuracy']:.3f}"
    )

    missed = describe_missed(suite, runs[0])
    invented = describe_invented(runs[0])
    if missed:
        print(f"Missed gold tasks ({len(missed)}):")
        print("\n".join(missed))
    if invented:
        print(f"Invented/unmatched predictions ({len(invented)}):")
        print("\n".join(invented))

    if args.record_baseline:
        path = Path(args.record_baseline)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "scorer_version": SCORER_VERSION,
                    "suite": suite.name,
                    "split": args.split,
                    "predictions_file": args.predictions,
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "runs": metrics_per_run,
                },
                indent=2,
            )
            + "\n"
        )
        print(f"Baseline recorded -> {path}")

    if args.gate:
        baseline = json.loads(Path(args.gate).read_text())
        if baseline.get("scorer_version") != SCORER_VERSION:
            print(
                f"GATE ERROR: baseline scorer {baseline.get('scorer_version')} != {SCORER_VERSION}; "
                "re-record the baseline (scorer spec changed)."
            )
            return 2
        decision = gate_decision(baseline["runs"], metrics_per_run)
        print(decision.summary())
        if not decision.passed:
            print("Regression details: see missed/invented lists above vs the baseline report.")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
