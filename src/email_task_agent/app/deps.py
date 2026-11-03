"""Shared app dependencies (kept out of main.py to avoid an import cycle with
app/api.py, which needs Deps for its router factory)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from email_task_agent.chat.service import ChatService


@dataclass
class Deps:
    store: object
    mode: str  # demo | private
    owner_email: str
    chat: ChatService | None = None
    sync_runner: Callable[[], str] | None = None  # returns a banner message
    reextract_runner: Callable[[str], str] | None = None
