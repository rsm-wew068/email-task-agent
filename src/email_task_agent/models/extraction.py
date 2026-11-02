"""Structured extraction output (plan §7 Extract stage).

This is the ``output_type=ThreadExtraction`` contract for the Pydantic AI
extraction agent: new tasks and updates, each anchored to an evidence quote
from a specific message. Dates arrive as free text and are parsed/validated in
the Validate stage — "due date must parse" is a validation outcome, not a
decode error.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NewTask(BaseModel):
    title: str = Field(..., min_length=1)
    owner_email: str | None = Field(
        None, description="Participant who owns the task; None if genuinely unassigned."
    )
    due_date: str | None = Field(None, description="ISO date if stated, else the raw phrase.")
    status: str = Field("open", pattern="^(open|done|cancelled)$")
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    evidence_quote: str = Field(..., min_length=1, description="Verbatim sentence from the email.")
    source_message_id: str


class TaskUpdate(BaseModel):
    # §7.3: updates must reference one of the task IDs shown in the Extract
    # context, citing a sentence from a NEW email. The Validate stage checks
    # both; reconciliation links updates by this ID, never by title similarity.
    ref_task_id: int
    title: str | None = None
    owner_email: str | None = None
    due_date: str | None = None
    status: str | None = Field(None, pattern="^(open|done|cancelled)$")
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    evidence_quote: str = Field(..., min_length=1)
    source_message_id: str


class ThreadExtraction(BaseModel):
    new_tasks: list[NewTask] = Field(default_factory=list)
    updates: list[TaskUpdate] = Field(default_factory=list)
