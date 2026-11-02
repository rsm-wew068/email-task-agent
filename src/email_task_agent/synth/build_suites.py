"""Generate the checked-in eval suites (evals/data/*.json).

  uv run python -m email_task_agent.synth.build_suites
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from email_task_agent.evals.scoring import SCORER_VERSION
from email_task_agent.synth.cases_demo import build_demo_extras
from email_task_agent.synth.cases_e1 import build_cases
from email_task_agent.synth.generate import ThreadSpec, write_suite

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "evals" / "data"
E1_PATH = DATA_DIR / "e1_test.json"
DEMO_PATH = DATA_DIR / "demo_mailbox.json"

# Fixed seed date (a Monday) so checked-in suites are byte-stable.
SEED_DATE = date(2026, 11, 2)


def _strip_gold(specs: list[ThreadSpec]) -> list[ThreadSpec]:
    return [ThreadSpec(thread_id=s.thread_id, emails=s.emails, gold=[], split=s.split, tags=s.tags) for s in specs]


def main() -> int:
    e1_specs = build_cases()
    demo_specs = build_cases() + build_demo_extras()

    write_suite("e1-v1", SEED_DATE, e1_specs, E1_PATH)
    write_suite("demo-v1", SEED_DATE, _strip_gold(demo_specs), DEMO_PATH)

    n_gold = sum(len(s.gold) for s in e1_specs)
    print(f"wrote {E1_PATH} ({len(e1_specs)} threads, {n_gold} gold tasks, scorer {SCORER_VERSION})")
    print(f"wrote {DEMO_PATH} ({len(demo_specs)} threads, gold stripped for the public demo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
