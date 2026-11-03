"""Demo-mailbox threads (public demo instance): synthetic persona mailbox,
dates relative to the seed date. Target: 40-60 threads; these extras
join the E1 cases to form the demo suite. No gold — the demo is for browsing
and E3 agent questions, not for the extraction gate.
"""

from __future__ import annotations

from email_task_agent.synth.cases_e1 import KATE, ME, PRIYA, TOM
from email_task_agent.synth.generate import EmailSpec, ThreadSpec

VENDOR = "support@ledgerline.example"
DEVON = "devon@fernwoodlabs.com"
MAYA = "maya@outside.example"


def build_demo_extras() -> list[ThreadSpec]:
    return [
        ThreadSpec(
            thread_id="demo-001-expense-report",
            tags=["expense"],
            split="test",
            emails=[
                EmailSpec(
                    sender=KATE,
                    to=[ME],
                    day_offset=1,
                    subject="October expenses",
                    body=(
                        "Hi Alex,\n\nFinance is closing the books soon. "
                        "Please file your October expense report by Tuesday so payroll can "
                        "reimburse you this cycle.\n\nKate"
                    ),
                )
            ],
        ),
        ThreadSpec(
            thread_id="demo-002-vendor-outage",
            tags=["vendor"],
            split="test",
            emails=[
                EmailSpec(
                    sender=VENDOR,
                    to=[ME],
                    day_offset=1,
                    subject="[Resolved] LedgerLine reporting outage",
                    body=(
                        "The reporting outage affecting exports has been resolved. "
                        "No customer action is required; exports queued during the window "
                        "will complete automatically."
                    ),
                )
            ],
        ),
        ThreadSpec(
            thread_id="demo-003-conference-cfp",
            tags=["conference"],
            split="test",
            emails=[
                EmailSpec(
                    sender=MAYA,
                    to=[ME],
                    day_offset=2,
                    subject="PyAtlas CFP — would you submit?",
                    body=(
                        "Hey Alex,\n\nThe PyAtlas conference CFP is open. "
                        "If you submit the GraphRAG talk by December 1 I'll review it before "
                        "you send it.\n\nMaya"
                    ),
                )
            ],
        ),
        ThreadSpec(
            thread_id="demo-004-team-lunch",
            tags=["social"],
            split="test",
            emails=[
                EmailSpec(
                    sender=DEVON,
                    to=[ME, TOM, KATE],
                    day_offset=2,
                    subject="Team lunch Friday",
                    body=(
                        "Grabbing lunch at the taqueria on Friday at 12:30 — join if you "
                        "like, no agenda. I'll book a table for however many reply."
                    ),
                )
            ],
        ),
        ThreadSpec(
            thread_id="demo-005-contract-renewal",
            tags=["vendor", "renewal"],
            split="test",
            emails=[
                EmailSpec(
                    sender=PRIYA,
                    to=[ME],
                    day_offset=3,
                    subject="Contract renewal — ClientCo",
                    body=(
                        "Hi Alex,\n\nOur procurement team wants the renewal done early this year. "
                        "Can you return the signed renewal contract by the 20th? "
                        "Legal has already approved the terms.\n\nPriya"
                    ),
                )
            ],
        ),
        ThreadSpec(
            thread_id="demo-006-intro-to-maya",
            tags=["intro"],
            split="test",
            emails=[
                EmailSpec(
                    sender=DEVON,
                    to=[ME, MAYA],
                    day_offset=4,
                    subject="Intro: Maya (PyAtlas)",
                    body=(
                        "Connecting you two — Maya runs the PyAtlas track and Alex built our "
                        "internal task pipeline. I'll let you take it from here."
                    ),
                )
            ],
        ),
        ThreadSpec(
            thread_id="demo-007-password-rotation",
            tags=["it"],
            split="test",
            emails=[
                EmailSpec(
                    sender=VENDOR,
                    to=[ME],
                    day_offset=4,
                    subject="Scheduled maintenance",
                    body=(
                        "LedgerLine will undergo scheduled maintenance on Sunday 02:00-04:00 UTC. "
                        "This announcement is informational; the API remains available."
                    ),
                )
            ],
        ),
        ThreadSpec(
            thread_id="demo-008-handoff-to-tom",
            tags=["handoff"],
            split="test",
            emails=[
                EmailSpec(
                    sender=ME,
                    to=[TOM],
                    day_offset=5,
                    subject="Vendor onboarding — taking over",
                    body=(
                        "Tom, you're taking over the LedgerLine onboarding from me. "
                        "Please schedule the kickoff call with their team next week and "
                        "loop in Kate on the invite.\n\nAlex"
                    ),
                )
            ],
        ),
    ]
