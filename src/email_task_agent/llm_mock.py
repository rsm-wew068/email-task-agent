"""Scripted mock LLM for the keyless demo instance (case-study brief: "mocked
external integrations are allowed if clearly labeled").

When no API key is configured, the demo chat runs on this deterministic model
instead of a real provider. It exercises the SAME pipeline as production —
real tools, real store, real approval state machine — with canned model
responses. The UI and README label it clearly as a mock.
"""

from __future__ import annotations

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

_TASK_SUMMARY = (
    "Here's what's on your plate (demo data): 9 open tasks. The nearest ones are "
    "'Send me the onboarding checklist' (Tom, due 2026-11-04), 'Send October invoice "
    "to ClientCo billing' (you, due 2026-11-05) and 'Post weekly standup notes' "
    "(you, due 2026-11-06). Ask me to draft a reply and I'll show you the approval flow."
)

_DRAFT_TOOL_CALL_ARGS = {
    "to": "kate@fernwoodlabs.com",
    "subject": "Re: Q3 draft for the board",
    "body": "Hi Kate,\n\nQuick note to confirm the revised Q3 draft is on its way to you now — you'll have it ahead of the board meeting.\n\nBest,\nAlex",
}


def _counts(messages: list[ModelMessage]) -> tuple[int, int]:
    calls = returns = 0
    for message in messages:
        for part in getattr(message, "parts", []):
            kind = getattr(part, "part_kind", "")
            calls += kind == "tool-call"
            returns += kind == "tool-return"
    return calls, returns


def _last_tool_return(messages: list[ModelMessage]) -> str:
    text = "Done."
    for message in messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", "") == "tool-return":
                text = str(getattr(part, "content", text))
    return text


def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    calls, returns = _counts(messages)
    user_text = ""
    for message in messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", "") == "user-prompt":
                user_text = str(getattr(part, "content", ""))

    # Mid-approval-flow or after a tool ran: wrap up with the tool outcome.
    if calls > 0 and returns > 0:
        return ModelResponse(parts=[TextPart(content=_last_tool_return(messages))])

    # First turn: drafting requests trigger the approval-gated draft tool.
    if calls == 0 and returns == 0 and any(
        word in user_text.lower() for word in ("draft", "reply", "email", "write")
    ):
        return ModelResponse(
            parts=[
                TextPart(content="I'll prepare the draft for your approval."),
                ToolCallPart(
                    tool_name="create_gmail_draft",
                    args=_DRAFT_TOOL_CALL_ARGS,
                    tool_call_id="mock-draft-1",
                ),
            ]
        )

    # Task questions: point at the demo data without tools.
    if calls == 0 and returns == 0 and any(
        word in user_text.lower() for word in ("task", "due", "todo", "open", "owe")
    ):
        return ModelResponse(parts=[TextPart(content=_TASK_SUMMARY)])

    return ModelResponse(
        parts=[
            TextPart(
                content="(Mock LLM, no API key configured.) Try: 'what tasks are open?' "
                "or 'draft a reply to Kate' to see the approval flow."
            )
        ]
    )


def build_mock_model() -> Model:
    """Deterministic stand-in for a real provider; labeled as a mock in the UI."""
    return FunctionModel(_respond)
