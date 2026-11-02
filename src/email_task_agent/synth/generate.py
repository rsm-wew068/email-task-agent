"""Label-first synthetic thread generation (plan §9, rev 2 §5.3 style).

Gold tasks are DECLARED FIRST with their evidence sentences; email bodies are
written around them so every evidence sentence appears verbatim (the
self-consistency test in tests/test_synth.py enforces this). Dates are authored
as day offsets from a seed date and rendered to absolute ISO dates, so suites
stay stable no matter when they are generated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from email_task_agent.evals.scoring import SCORER_VERSION


@dataclass
class EmailSpec:
    sender: str
    to: list[str]
    day_offset: int
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)


@dataclass
class GoldSpec:
    title: str
    owner_email: str | None
    due_offset_days: int | None
    evidence_sentence: str
    email_index: int
    status: str = "open"


@dataclass
class ThreadSpec:
    thread_id: str
    emails: list[EmailSpec]
    gold: list[GoldSpec] = field(default_factory=list)
    split: str = "test"
    tags: list[str] = field(default_factory=list)


def render_thread(spec: ThreadSpec, seed: date) -> dict:
    return {
        "thread_id": spec.thread_id,
        "split": spec.split,
        "tags": spec.tags,
        "emails": [
            {
                "from": e.sender,
                "to": e.to,
                "cc": e.cc,
                "date": (seed + timedelta(days=e.day_offset)).isoformat(),
                "subject": e.subject,
                "body": e.body,
            }
            for e in spec.emails
        ],
        "gold": [
            {
                "title": g.title,
                "owner_email": g.owner_email,
                "due_date": (seed + timedelta(days=g.due_offset_days)).isoformat()
                if g.due_offset_days is not None
                else None,
                "status": g.status,
                "evidence_sentence": g.evidence_sentence,
                "email_index": g.email_index,
            }
            for g in spec.gold
        ],
    }


def write_suite(name: str, seed: date, specs: list[ThreadSpec], path: str | Path) -> Path:
    payload = {
        "suite": name,
        "seed_date": seed.isoformat(),
        "scorer_version": SCORER_VERSION,
        "threads": [render_thread(s, seed) for s in specs],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return path
