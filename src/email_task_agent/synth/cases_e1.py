"""Starter E1 case set (label-first). Target per §9.3: 40 synthetic threads in
the test split (~100 gold tasks with the private golden set); this starter set
proves the harness end to end and seeds the case matrix. Grow by adding
ThreadSpecs — the self-consistency test keeps authoring honest.

Default task scope (rev 5 decision, §9.2): a task is in scope when the mailbox
owner owns it or asked someone for it. Threads where others are assigned work
while the owner is merely CC'd have EMPTY gold — they test the scope boundary.

Seed date 2026-11-02 is a Monday, so Friday = +4, Thursday = +3, Wednesday = +2,
"next Monday" = +7.
"""

from __future__ import annotations

from email_task_agent.synth.generate import EmailSpec, GoldSpec, ThreadSpec

ME = "alex@fernwoodlabs.com"
KATE = "kate@fernwoodlabs.com"
TOM = "tom@fernwoodlabs.com"
PRIYA = "priya@clientco.example"
SPARK = "newsletter@sparkmetrics.example"


def build_cases() -> list[ThreadSpec]:
    return [
        # 1. Direct task to me with an explicit date.
        ThreadSpec(
            thread_id="e1-001-send-q3-draft",
            tags=["single-task", "explicit-date"],
            emails=[
                EmailSpec(
                    sender=KATE,
                    to=[ME],
                    day_offset=0,
                    subject="Q3 draft for the board",
                    body=(
                        "Hi Alex,\n\n"
                        "Could you send me the revised Q3 draft by Friday so I can review it "
                        "before the board meeting?\n\n"
                        "The deck is in the shared drive under Finance/2026/Q3.\n\n"
                        "Thanks,\nKate"
                    ),
                )
            ],
            gold=[
                GoldSpec(
                    title="Send revised Q3 draft to Kate",
                    owner_email=ME,
                    due_offset_days=4,
                    evidence_sentence=(
                        "Could you send me the revised Q3 draft by Friday so I can review it "
                        "before the board meeting?"
                    ),
                    email_index=0,
                )
            ],
        ),
        # 2. Scheduling chatter, no task for me (the sender does the scheduling).
        ThreadSpec(
            thread_id="e1-002-kickoff-scheduling",
            tags=["no-task", "scheduling"],
            emails=[
                EmailSpec(
                    sender=TOM,
                    to=[ME, KATE],
                    day_offset=1,
                    subject="Kickoff scheduling",
                    body=(
                        "Hi both,\n\n"
                        "Great kickoff today. I'll send a calendar invite once we find a slot "
                        "that works for the client.\n\n"
                        "Tom"
                    ),
                ),
                EmailSpec(
                    sender=KATE,
                    to=[TOM, ME],
                    day_offset=1,
                    subject="Re: Kickoff scheduling",
                    body=("Works for me — afternoons are better this week."),
                ),
            ],
        ),
        # 3. Newsletter with action-flavoured wording — precision trap.
        ThreadSpec(
            thread_id="e1-003-newsletter-renewal",
            tags=["no-task", "precision-trap"],
            emails=[
                EmailSpec(
                    sender=SPARK,
                    to=[ME],
                    day_offset=2,
                    subject="Spark Metrics monthly digest",
                    body=(
                        "Your November digest is here.\n\n"
                        "Top story: dashboards get faster for every plan.\n\n"
                        "Renew your seat by November 15 to lock in current pricing.\n\n"
                        "You are receiving this because you subscribed at sparkmetrics.example."
                    ),
                )
            ],
        ),
        # 4. I'm CC'd; the task is Tom's, assigned by Kate — out of scope by default.
        ThreadSpec(
            thread_id="e1-004-cc-other-owner",
            tags=["no-task", "scope-boundary"],
            emails=[
                EmailSpec(
                    sender=KATE,
                    to=[TOM],
                    cc=[ME],
                    day_offset=2,
                    subject="Staging config",
                    body=(
                        "Tom, please update the staging config to point at the new database "
                        "before Thursday's release.\n\n"
                        "Alex, FYI only."
                    ),
                )
            ],
        ),
        # 5. I asked someone for something — in scope, owner is them.
        ThreadSpec(
            thread_id="e1-005-asked-for-checklist",
            tags=["single-task", "asked-for", "explicit-date"],
            emails=[
                EmailSpec(
                    sender=ME,
                    to=[TOM],
                    day_offset=2,
                    subject="Onboarding checklist",
                    body=(
                        "Tom, could you send me the onboarding checklist by Wednesday? "
                        "We have two new starters on the 16th.\n\n"
                        "Alex"
                    ),
                ),
                EmailSpec(
                    sender=TOM,
                    to=[ME],
                    day_offset=3,
                    subject="Re: Onboarding checklist",
                    body=("Will do — you'll have it Wednesday morning."),
                ),
            ],
            gold=[
                GoldSpec(
                    title="Send me the onboarding checklist",
                    owner_email=TOM,
                    due_offset_days=2,
                    evidence_sentence=(
                        "Tom, could you send me the onboarding checklist by Wednesday?"
                    ),
                    email_index=0,
                )
            ],
        ),
        # 6. Two different tasks stated in one sentence — both survive (rev 5 §7.3).
        ThreadSpec(
            thread_id="e1-006-two-tasks-one-sentence",
            tags=["multi-task", "one-sentence"],
            emails=[
                EmailSpec(
                    sender=KATE,
                    to=[ME],
                    day_offset=1,
                    subject="ClientCo invoice + tracker",
                    body=(
                        "Hi Alex,\n\n"
                        "Please send the October invoice to billing@clientco.example and update "
                        "the renewal tracker with the new dates by Thursday.\n\n"
                        "Both are blocking their procurement review.\n\n"
                        "Kate"
                    ),
                )
            ],
            gold=[
                GoldSpec(
                    title="Send October invoice to ClientCo billing",
                    owner_email=ME,
                    due_offset_days=3,
                    evidence_sentence=(
                        "Please send the October invoice to billing@clientco.example and update "
                        "the renewal tracker with the new dates by Thursday."
                    ),
                    email_index=0,
                ),
                GoldSpec(
                    title="Update renewal tracker with new dates",
                    owner_email=ME,
                    due_offset_days=3,
                    evidence_sentence=(
                        "Please send the October invoice to billing@clientco.example and update "
                        "the renewal tracker with the new dates by Thursday."
                    ),
                    email_index=0,
                ),
            ],
        ),
        # 7. Relative date "end of the week" — labeling rule resolves to Friday.
        ThreadSpec(
            thread_id="e1-007-relative-date",
            split="dev",
            tags=["single-task", "relative-date"],
            emails=[
                EmailSpec(
                    sender=PRIYA,
                    to=[ME],
                    day_offset=0,
                    subject="Integration sign-off",
                    body=(
                        "Hi Alex,\n\n"
                        "Legal cleared the DPA, so we can proceed.\n\n"
                        "Can you sign the integration agreement by the end of the week? "
                        "After that we can schedule the joint test.\n\n"
                        "Priya"
                    ),
                )
            ],
            gold=[
                GoldSpec(
                    title="Sign the ClientCo integration agreement",
                    owner_email=ME,
                    due_offset_days=4,
                    evidence_sentence="Can you sign the integration agreement by the end of the week?",
                    email_index=0,
                )
            ],
        ),
        # 8. Deadline moved by a later email — gold is the FINAL state (Nov 9, Monday).
        ThreadSpec(
            thread_id="e1-008-deadline-move",
            split="dev",
            tags=["single-task", "update", "deadline-move"],
            emails=[
                EmailSpec(
                    sender=KATE,
                    to=[ME],
                    day_offset=0,
                    subject="Security questionnaire",
                    body=(
                        "Hi Alex,\n\n"
                        "ClientCo's security team needs our questionnaire. "
                        "Please send the completed security questionnaire by Thursday next week.\n\n"
                        "Kate"
                    ),
                ),
                EmailSpec(
                    sender=KATE,
                    to=[ME],
                    day_offset=3,
                    subject="Re: Security questionnaire",
                    body=(
                        "Update: compliance moved the audit up. "
                        "Can you get the security questionnaire to me by Monday instead?\n\n"
                        "Sorry for the squeeze."
                    ),
                ),
            ],
            gold=[
                GoldSpec(
                    title="Send completed security questionnaire to Kate",
                    owner_email=ME,
                    due_offset_days=7,
                    evidence_sentence=(
                        "Can you get the security questionnaire to me by Monday instead?"
                    ),
                    email_index=1,
                )
            ],
        ),
        # 9. Task with no stated due date.
        ThreadSpec(
            thread_id="e1-009-no-due-date",
            split="dev",
            tags=["single-task", "no-date"],
            emails=[
                EmailSpec(
                    sender=PRIYA,
                    to=[ME],
                    day_offset=1,
                    subject="Integration notes",
                    body=(
                        "Hi Alex,\n\n"
                        "I pushed the integration notes to the shared folder.\n\n"
                        "When you get a chance, can you look over the integration notes and "
                        "flag anything risky?\n\n"
                        "No rush, but before the joint test would be ideal.\n\n"
                        "Priya"
                    ),
                )
            ],
            gold=[
                GoldSpec(
                    title="Review ClientCo integration notes",
                    owner_email=ME,
                    due_offset_days=None,
                    evidence_sentence=(
                        "When you get a chance, can you look over the integration notes and "
                        "flag anything risky?"
                    ),
                    email_index=0,
                )
            ],
        ),
        # 10. Explicit no-action FYI.
        ThreadSpec(
            thread_id="e1-010-fyi-deck",
            split="dev",
            tags=["no-task", "fyi"],
            emails=[
                EmailSpec(
                    sender=KATE,
                    to=[ME, TOM],
                    day_offset=2,
                    subject="Board deck v2",
                    body=(
                        "Attached is board deck v2 for your awareness. "
                        "No action needed on your side — comments close Friday."
                    ),
                )
            ],
        ),
        # 11. Recurring task — one gold task for the first instance (§7.3: instances
        # more than 7 days apart are never duplicate-suggested; that's E2 territory).
        ThreadSpec(
            thread_id="e1-011-recurring-standup-notes",
            split="dev",
            tags=["single-task", "recurring"],
            emails=[
                EmailSpec(
                    sender=KATE,
                    to=[ME],
                    day_offset=0,
                    subject="Standup notes",
                    body=(
                        "Hi Alex,\n\n"
                        "Starting this week, can you post the weekly standup notes every Friday "
                        "to the team channel? It keeps the async folks in the loop.\n\n"
                        "Kate"
                    ),
                )
            ],
            gold=[
                GoldSpec(
                    title="Post weekly standup notes",
                    owner_email=ME,
                    due_offset_days=4,
                    evidence_sentence=(
                        "Starting this week, can you post the weekly standup notes every Friday "
                        "to the team channel?"
                    ),
                    email_index=0,
                )
            ],
        ),
        # 12. Ambiguous owner ("someone from Alex's team") — owner None, needs review.
        ThreadSpec(
            thread_id="e1-012-ambiguous-owner",
            split="dev",
            tags=["single-task", "ambiguous-owner"],
            emails=[
                EmailSpec(
                    sender=KATE,
                    to=[ME, TOM],
                    day_offset=2,
                    subject="Pen test prep",
                    body=(
                        "Team,\n\n"
                        "The external pen test starts Nov 20. Someone from Alex's team should "
                        "refresh the staging SSL cert before the pen test starts.\n\n"
                        "I'll coordinate access with the vendor.\n\n"
                        "Kate"
                    ),
                )
            ],
            gold=[
                GoldSpec(
                    title="Refresh staging SSL cert before pen test",
                    owner_email=None,
                    due_offset_days=18,
                    evidence_sentence=(
                        "Someone from Alex's team should refresh the staging SSL cert before "
                        "the pen test starts."
                    ),
                    email_index=0,
                )
            ],
        ),
    ]
