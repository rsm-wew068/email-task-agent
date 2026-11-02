"""Load synthetic suites (label-first JSON produced by email_task_agent.synth).

Suite JSON shape:
{
  "suite": "e1-test",
  "seed_date": "2026-11-02",
  "scorer_version": "e1-spec-v1.1",
  "threads": [
    {
      "thread_id": "e1-001",
      "split": "test",
      "tags": ["single-task"],
      "emails": [{"from": "...", "to": ["..."], "cc": [], "date": "2026-11-02",
                  "subject": "...", "body": "..."}],
      "gold": [{"title": "...", "owner_email": "...", "due_date": "2026-11-06",
                "status": "open", "evidence_sentence": "...", "email_index": 0}]
    }
  ]
}

Predictions JSON shape (what an extractor run writes):
{"threads": [{"thread_id": "...", "predictions": [{"title", "owner_email",
  "due_date", "status", "evidence_quote", "source_email_index"}]}]}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from email_task_agent.evals.scoring import GoldTask, PredictedTask


@dataclass(frozen=True)
class EmailCase:
    sender: str
    to: list[str]
    cc: list[str]
    date: date
    subject: str
    body: str


@dataclass(frozen=True)
class ThreadCase:
    thread_id: str
    split: str
    tags: list[str]
    emails: list[EmailCase]
    gold: list[GoldTask] = field(default_factory=list)

    @property
    def thread_text(self) -> str:
        """Body text the scorer locates quotes in (all emails, in order)."""
        return "\n\n".join(
            f"Subject: {e.subject}\n\n{e.body}" for e in self.emails
        )


@dataclass(frozen=True)
class Suite:
    name: str
    seed_date: date
    threads: list[ThreadCase]

    def split(self, split: str) -> list[ThreadCase]:
        return [t for t in self.threads if t.split == split]


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def load_suite(path: str | Path) -> Suite:
    raw = json.loads(Path(path).read_text())
    threads = []
    for t in raw["threads"]:
        emails = [
            EmailCase(
                sender=e["from"],
                to=e.get("to", []),
                cc=e.get("cc", []),
                date=_parse_date(e["date"]),
                subject=e["subject"],
                body=e["body"],
            )
            for e in t["emails"]
        ]
        gold = [
            GoldTask(
                title=g["title"],
                owner_email=g.get("owner_email"),
                due_date=_parse_date(g.get("due_date")),
                status=g.get("status", "open"),
                evidence_sentence=g["evidence_sentence"],
                email_index=g["email_index"],
            )
            for g in t.get("gold", [])
        ]
        threads.append(
            ThreadCase(
                thread_id=t["thread_id"],
                split=t.get("split", "test"),
                tags=t.get("tags", []),
                emails=emails,
                gold=gold,
            )
        )
    return Suite(name=raw["suite"], seed_date=_parse_date(raw["seed_date"]), threads=threads)


def load_predictions(path: str | Path) -> dict[str, list[PredictedTask]]:
    raw = json.loads(Path(path).read_text())
    out: dict[str, list[PredictedTask]] = {}
    for t in raw["threads"]:
        out[t["thread_id"]] = [
            PredictedTask(
                title=p["title"],
                owner_email=p.get("owner_email"),
                due_date=_parse_date(p.get("due_date")),
                status=p.get("status", "open"),
                evidence_quote=p["evidence_quote"],
                source_email_index=p.get("source_email_index"),
            )
            for p in t.get("predictions", [])
        ]
    return out


def days_from(seed: date, day_offset: int) -> date:
    return seed + timedelta(days=day_offset)
