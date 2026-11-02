"""E1-U eval harness (plan §9, rev 5): wrong-update-link regression.

Feeds emails one at a time through validate+reconcile and counts links the
extractor got wrong (an update attached to a task other than the scenario's
labeled target). With a scripted extractor this pins the counting logic;
point it at a real model (via an adapter) once keys exist. The regression
rule: the wrong-link count must never go up vs the recorded baseline.

  uv run python -m email_task_agent.evals.e1u --extractor scripted[:perfect|wrong]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from email_task_agent.models.extraction import TaskUpdate, ThreadExtraction
from email_task_agent.pipeline.reconcile import ExistingTask, reconcile
from email_task_agent.pipeline.validate import ThreadInput, validate_extraction


@dataclass
class WrongLinkScenario:
    name: str
    # Tasks shown to the extractor before the new email arrives.
    existing: list[ExistingTask]
    # The new email's text and the update the model SHOULD attach to which task.
    new_email_text: str
    evidence_quote: str
    expected_task_id: int
    status: str = "done"


def build_scenarios() -> list[WrongLinkScenario]:
    monday = date(2026, 11, 2)
    return [
        WrongLinkScenario(
            name="two similar tasks, email clearly completes the second",
            existing=[
                ExistingTask(1, "Review API contract draft", "a@x", monday + timedelta(days=3), "open", None),
                ExistingTask(2, "Review vendor contract draft", "a@x", monday + timedelta(days=4), "open", None),
            ],
            new_email_text="Subject: Vendor contract\n\nThe vendor contract draft review is finished, I sent my comments.",
            evidence_quote="The vendor contract draft review is finished, I sent my comments.",
            expected_task_id=2,
        ),
        WrongLinkScenario(
            name="question about task A must not complete task B",
            existing=[
                ExistingTask(1, "Send Q3 draft", "a@x", monday + timedelta(days=2), "open", None),
                ExistingTask(2, "File expense report", "a@x", monday + timedelta(days=5), "open", None),
            ],
            new_email_text="Subject: Q3 draft\n\nIs the Q3 draft ready to send yet?",
            evidence_quote="Is the Q3 draft ready to send yet?",
            expected_task_id=1,
        ),
    ]


def run_scenario(scenario: WrongLinkScenario, extract_fn) -> int:
    """Feed the new email through the pipeline once; return 1 if the update was
    linked to the wrong task, else 0."""
    inp = ThreadInput(
        thread_id=scenario.name,
        thread_text=scenario.new_email_text,
        participants={"a@x"},
        shown_task_ids={t.id for t in scenario.existing},
        new_message_ids={"m-new"},
        message_dates={"m-new": date(2026, 11, 3)},
    )
    extraction = extract_fn(scenario, inp)
    validated = validate_extraction(extraction, inp)
    out = reconcile(validated, scenario.existing, processed_message_ids=set())
    for update in out.updates:
        if update.status == "done" and update.task_id != scenario.expected_task_id:
            return 1
    # A done-update attached to the right task but arriving as a *suggestion*
    # is not a wrong link (low-confidence path); absence is fine too.
    return 0


def scripted_extractor(variant: str):
    """Scripted 'model': variant 'perfect' links correctly; 'wrong' attaches
    updates to the first shown task. Stands in for the real model until the
    D3 bake-off pins one."""

    def extract(scenario: WrongLinkScenario, inp: ThreadInput) -> ThreadExtraction:
        if variant == "perfect":
            ref = scenario.expected_task_id
        else:  # 'wrong': deliberately attach to a shown task that is NOT the target
            ref = next(tid for tid in sorted(inp.shown_task_ids) if tid != scenario.expected_task_id)
        return ThreadExtraction(
            new_tasks=[],
            updates=[
                TaskUpdate(
                    ref_task_id=ref,
                    status=scenario.status,
                    confidence=0.9,
                    evidence_quote=scenario.evidence_quote,
                    source_message_id="m-new",
                )
            ],
        )

    return extract


def count_wrong_links(scenarios: list[WrongLinkScenario], extract_fn) -> int:
    return sum(run_scenario(s, extract_fn) for s in scenarios)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extractor", default="scripted:perfect")
    parser.add_argument("--baseline", help="JSON file with the recorded wrong-link count; fails if current > baseline")
    parser.add_argument("--record-baseline", help="write the count as the new baseline")
    args = parser.parse_args(argv)

    kind, _, variant = args.extractor.partition(":")
    if kind != "scripted":
        print("Only scripted extractors are wired; adapt ExtractionAgent for real-model runs.")
        return 2
    scenarios = build_scenarios()
    wrong = count_wrong_links(scenarios, scripted_extractor(variant or "perfect"))
    print(f"E1-U ({variant}): {wrong} wrong links out of {len(scenarios)} scenarios (must not go up)")

    if args.record_baseline:
        Path(args.record_baseline).write_text(json.dumps({"variant": variant, "wrong_links": wrong}, indent=2) + "\n")
        print(f"Baseline recorded -> {args.record_baseline}")
    if args.baseline:
        recorded = json.loads(Path(args.baseline).read_text())
        if wrong > recorded["wrong_links"]:
            print(f"GATE FAIL: {wrong} > baseline {recorded['wrong_links']}")
            return 1
        print("GATE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
