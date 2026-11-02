"""§8.2 approval-flow tests in a REAL browser (Playwright + Chromium).

Runs the FastAPI app with the in-memory store and a scripted FunctionModel on
a local port, then drives it the way the plan specifies: approve, deny,
double submit, page reload, two actions in one turn, and a crash right after
the API call (retry must never send twice).
"""

from __future__ import annotations

import threading
import time

import pytest
import uvicorn
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from email_task_agent.app.main import Deps, create_app
from email_task_agent.chat.service import ChatService
from email_task_agent.demo.seed import seed_demo_instance
from email_task_agent.memory import MemoryStore

pytest.importorskip("playwright.sync_api")


class FlakyGmail:
    def __init__(self):
        self.calls = 0

    def create_draft(self, to: str, subject: str, body: str) -> str:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("connection reset right after the API call")
        return "draft-real-1"


def _counts(messages: list[ModelMessage]) -> tuple[int, int]:
    calls = returns = 0
    for message in messages:
        for part in getattr(message, "parts", []):
            kind = getattr(part, "part_kind", "")
            calls += kind == "tool-call"
            returns += kind == "tool-return"
    return calls, returns


def _last_tool_return(messages: list[ModelMessage]) -> str:
    text = "done"
    for message in messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", "") == "tool-return":
                text = str(getattr(part, "content", text))
    return text


def single_draft_script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    calls, returns = _counts(messages)
    if calls == 0 and returns == 0:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="create_gmail_draft",
                    args={"to": "kate@x", "subject": "Q3 draft", "body": "Here it is."},
                    tool_call_id="tc1",
                )
            ]
        )
    return ModelResponse(parts=[TextPart(content=_last_tool_return(messages))])


def two_action_script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    calls, returns = _counts(messages)
    if calls == 0 and returns == 0:
        return ModelResponse(
            parts=[
                ToolCallPart(tool_name="create_gmail_draft", args={"to": "k@x", "subject": "s", "body": "b"}, tool_call_id="tcA"),
                ToolCallPart(tool_name="create_google_task", args={"title": "Follow up", "due": None}, tool_call_id="tcB"),
            ]
        )
    return ModelResponse(parts=[TextPart(content=_last_tool_return(messages))])


def start_server(*, gmail: FlakyGmail | None = None, script=single_draft_script, mode="demo"):
    store = MemoryStore()
    seed_demo_instance(store, owner_email="alex@fernwoodlabs.com")
    service = ChatService(store, FunctionModel(script), mode=mode, me="alex@fernwoodlabs.com", gmail=gmail)
    app = create_app(Deps(store=store, mode=mode, owner_email="alex@fernwoodlabs.com", chat=service))

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}", store


def send_and_wait_for_approval(page, base: str, message: str):
    page.goto(f"{base}/chat")
    page.fill("input[name=message]", message)
    page.click("form.chat button.primary")
    page.wait_for_selector("form.approval")
    return page


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


def test_approve_executes_action_once(browser):
    base, store = start_server()
    page = browser.new_page()
    send_and_wait_for_approval(page, base, "please draft a reply to Kate")
    assert "create_gmail_draft" in page.inner_text("form.approval")

    page.click("form.approval button.primary")
    page.wait_for_selector("form.approval", state="detached")  # swap landed
    assert "Created (id=" in page.inner_text("#chat-panel")
    assert [store.action_get(i)["status"] for i in store.actions] == ["executed"]


def test_deny_does_not_execute(browser):
    base, store = start_server()
    page = browser.new_page()
    send_and_wait_for_approval(page, base, "draft it")
    page.check("input[name='decision_tc1'][value='deny']")
    page.click("form.approval button.primary")
    page.wait_for_selector("form.approval", state="detached")
    assert "The tool call was denied" in page.inner_text("#chat-panel")
    assert all(store.action_get(i)["status"] == "proposed" for i in store.actions)


def test_double_submit_is_stale_noop(browser):
    base, store = start_server()
    page = browser.new_page()
    send_and_wait_for_approval(page, base, "draft it")
    version = page.input_value("form.approval input[name=version]")
    session_id = page.input_value("form.approval input[name=session_id]")

    page.click("form.approval button.primary")
    page.wait_for_selector("form.approval", state="detached")

    # An old tab resubmits the captured (now stale) form via the real endpoint.
    stale = page.evaluate(
        """async ([base, session_id, version]) => {
            const body = new URLSearchParams({
                session_id, version, decision_tc1: 'approve',
            });
            const res = await fetch(`${base}/chat/approve`, {
                method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body,
            });
            return await res.text();
        }""",
        [base, session_id, version],
    )
    assert "stale" in stale.lower()
    assert [store.action_get(i)["status"] for i in store.actions] == ["executed"]  # exactly once


def test_page_reload_preserves_pending_approval(browser):
    base, _store = start_server()
    page = browser.new_page()
    send_and_wait_for_approval(page, base, "draft it")
    page.reload()
    page.wait_for_selector("form.approval")
    assert "create_gmail_draft" in page.inner_text("form.approval")


def test_two_actions_in_one_turn(browser):
    base, store = start_server(script=two_action_script)
    page = browser.new_page()
    send_and_wait_for_approval(page, base, "draft and create a follow-up task")
    text = page.inner_text("form.approval")
    assert "create_gmail_draft" in text and "create_google_task" in text

    page.check("input[name='decision_tcA'][value='approve']")
    page.check("input[name='decision_tcB'][value='approve']")
    page.click("form.approval button.primary")
    page.wait_for_selector("form.approval", state="detached")
    statuses = sorted(store.action_get(i)["status"] for i in store.actions)
    assert statuses == ["executed", "executed"]


def test_crash_after_api_call_retry_never_sends_twice(browser):
    gmail = FlakyGmail()
    base, _store = start_server(gmail=gmail, mode="private")
    page = browser.new_page()
    send_and_wait_for_approval(page, base, "draft it")

    page.check("input[name='decision_tc1'][value='approve']")
    page.click("form.approval button.primary")
    page.wait_for_selector("text=The previous attempt failed")  # failed state re-renders the form
    assert gmail.calls == 1

    page.click("form.approval button.primary")  # retry the same decision
    page.wait_for_selector("text=NOT resending")
    assert gmail.calls == 1  # the crash never produced a duplicate send
