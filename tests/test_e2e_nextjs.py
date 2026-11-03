"""E2E (migration plan §6.2): Python Playwright against the Next.js production
build via `next start`. The browser only ever sees the Next.js origin; the
backend (uvicorn + a swappable ASGI shim) is reached server-side through
BACKEND_URL. Nine scenarios cover §8.2 parity plus the tasks/calendar pages.

Skips (module-level, not a failure) when Node or the production build is
missing; CI always builds before pytest.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
import uvicorn
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from email_task_agent.app.main import Deps, create_app
from email_task_agent.chat.service import ChatService
from email_task_agent.demo.seed import seed_demo_instance
from email_task_agent.memory import MemoryStore

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
OWNER = "alex@fernwoodlabs.com"

pytest.importorskip("playwright.sync_api")

if shutil.which("node") is None:
    pytest.skip("node not installed", allow_module_level=True)
if not (WEB / ".next" / "BUILD_ID").exists():
    pytest.skip("web/.next missing — run `npm --prefix web run build` first", allow_module_level=True)


# -- swappable ASGI shim (uvicorn serves ONE process; tests swap the app) ---------


class _Shim:
    def __init__(self) -> None:
        self.app = None

    async def __call__(self, scope, receive, send):
        if self.app is None or scope["type"] != "http":
            await send({"type": "http.response.start", "status": 503, "headers": []})
            await send({"type": "http.response.body", "body": b"no app installed"})
            return
        await self.app(scope, receive, send)


_SHIM = _Shim()


class FlakyGmail:
    def __init__(self) -> None:
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
            parts=[ToolCallPart(tool_name="create_gmail_draft",
                                args={"to": "kate@x", "subject": "Q3 draft", "body": "Here it is."},
                                tool_call_id="tc1")]
        )
    return ModelResponse(parts=[TextPart(content=_last_tool_return(messages))])


def two_action_script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    calls, returns = _counts(messages)
    if calls == 0 and returns == 0:
        return ModelResponse(
            parts=[
                ToolCallPart(tool_name="create_gmail_draft", args={"to": "k@x", "subject": "s", "body": "b"},
                             tool_call_id="tcA"),
                ToolCallPart(tool_name="create_google_task", args={"title": "Follow up", "due": None},
                             tool_call_id="tcB"),
            ]
        )
    return ModelResponse(parts=[TextPart(content=_last_tool_return(messages))])


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def install_app(
    *,
    model: FunctionModel | None = None,
    gmail: FlakyGmail | None = None,
    mode: str = "demo",
    sync_runner: Callable[[], str] | None = None,
    reextract_runner: Callable[[str], str] | None = None,
) -> MemoryStore:
    """Wire a fresh app into the shim; returns the store for assertions."""
    store = MemoryStore()
    seed_demo_instance(store, owner_email=OWNER)
    chat = ChatService(store, model, mode=mode, me=OWNER, gmail=gmail) if model else None
    _SHIM.app = create_app(
        Deps(store=store, mode=mode, owner_email=OWNER, chat=chat,
             sync_runner=sync_runner, reextract_runner=reextract_runner)
    )
    return store


@pytest.fixture(scope="module")
def backend_port():
    config = uvicorn.Config(_SHIM, host="127.0.0.1", port=_free_port(), lifespan="off", log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    install_app()  # something sane before each test installs its own
    yield port


@pytest.fixture(scope="module")
def next_port(backend_port: int):
    port = _free_port()
    env = dict(os.environ, BACKEND_URL=f"http://127.0.0.1:{backend_port}", NODE_ENV="production")
    # DEVNULL: an unread pipe fills up if Next prints enough and blocks the server.
    proc = subprocess.Popen(
        [str(WEB / "node_modules" / ".bin" / "next"), "start", "--port", str(port)],
        cwd=WEB, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    import urllib.request

    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
            break
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError("next start exited early")
            time.sleep(0.3)
    yield port
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        chromium = p.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture
def page(browser, next_port: int):
    # base_url lets tests use relative page.goto paths; a fresh context also
    # means localStorage (the chat session id) starts empty per test.
    context = browser.new_context(base_url=f"http://127.0.0.1:{next_port}")
    yield context.new_page(), next_port
    context.close()


def send_and_wait(page, message: str = "please draft a reply") -> None:
    page.goto("/chat")
    page.wait_for_selector("[data-testid=chat-input]")
    page.fill("[data-testid=chat-input]", message)
    page.click("[data-testid=chat-send]")
    page.wait_for_selector("[data-testid=approval-form]")


# -- scenarios ------------------------------------------------------------------------


def test_approve_executes_once(page):
    page, _port = page
    store = install_app(model=FunctionModel(single_draft_script))
    send_and_wait(page)
    assert "create_gmail_draft" in page.inner_text("[data-testid=approval-form]")

    page.click("[data-testid=approve-submit]")
    page.wait_for_selector("text=Created (id=")
    assert [store.action_get(i)["status"] for i in store.actions] == ["executed"]


def test_deny_does_not_execute(page):
    page, _port = page
    store = install_app(model=FunctionModel(single_draft_script))
    send_and_wait(page)
    page.check("input[name='decision-tc1'][value='deny']")
    page.click("[data-testid=approve-submit]")
    page.wait_for_selector("text=The tool call was denied")
    assert store.actions == {}  # a denied call never records an action row


def test_double_submit_races_reach_server_once(page):
    """Two real submits race (requestSubmit doesn't check `disabled`); the
    server-side version CAS decides that only one executes."""
    page, _port = page
    store = install_app(model=FunctionModel(single_draft_script))
    send_and_wait(page)
    page.evaluate(
        """() => {
            const form = document.querySelector('[data-testid=approval-form]');
            form.requestSubmit();
            form.requestSubmit();
        }"""
    )
    page.wait_for_selector("text=Created (id=")
    assert [store.action_get(i)["status"] for i in store.actions] == ["executed"]


def test_second_tab_stale_form(page):
    page, _port = page
    store = install_app(model=FunctionModel(single_draft_script))
    send_and_wait(page)  # tab A
    tab_b = page.context.new_page()
    try:
        tab_b.goto("/chat")  # shares localStorage: same session, same version
        tab_b.wait_for_selector("[data-testid=approval-form]")

        page.click("[data-testid=approve-submit]")
        page.wait_for_selector("text=Created (id=")

        tab_b.click("[data-testid=approve-submit]")
        tab_b.wait_for_selector("[data-testid=chat-error]")
        assert "stale" in tab_b.inner_text("[data-testid=chat-error]").lower()
        assert [store.action_get(i)["status"] for i in store.actions] == ["executed"]
    finally:
        tab_b.close()


def test_reload_preserves_pending_approval(page):
    page, _port = page
    install_app(model=FunctionModel(single_draft_script))
    send_and_wait(page)
    page.reload()
    page.wait_for_selector("[data-testid=approval-form]")
    assert "create_gmail_draft" in page.inner_text("[data-testid=approval-form]")


def test_two_actions_approve_one_deny_one(page):
    page, _port = page
    store = install_app(model=FunctionModel(two_action_script))
    send_and_wait(page, "draft and create a follow-up task")
    actions = page.locator("[data-testid=pending-action]")
    assert actions.count() == 2

    page.check("input[name='decision-tcA'][value='approve']")  # draft: approve
    page.check("input[name='decision-tcB'][value='deny']")  # google task: deny
    page.click("[data-testid=approve-submit]")
    page.wait_for_selector("[data-testid=chat-input]")  # back to idle

    executed = [store.action_get(i) for i in store.actions]
    assert len(executed) == 1
    assert executed[0]["status"] == "executed"
    assert executed[0]["kind"] == "create_gmail_draft"  # §8.2: approved tool's args


def test_crash_after_api_call_retry_never_sends_twice(page):
    page, _port = page
    gmail = FlakyGmail()
    install_app(model=FunctionModel(single_draft_script), gmail=gmail, mode="private")
    send_and_wait(page)

    page.click("[data-testid=approve-submit]")
    page.wait_for_selector("text=The previous attempt failed")
    assert gmail.calls == 1

    page.click("[data-testid=approve-submit]")
    page.wait_for_selector("text=NOT resending")
    assert gmail.calls == 1


def test_tasks_page_mark_done_via_server_action(page):
    page, _port = page
    store = install_app()
    page.goto("/")
    task = store.list_tasks()[0]
    page.wait_for_selector(f"[data-testid=task-toggle-{task.id}]")
    page.click(f"[data-testid=task-toggle-{task.id}]")
    page.wait_for_selector(f"[data-testid=task-{task.id}] >> text=Mark open")  # button flips
    assert store.list_tasks(status="done")


def test_calendar_month_shows_seeded_task(page):
    page, _port = page
    install_app()
    page.goto("/calendar?month=2026-11")
    page.wait_for_selector("[data-testid=calendar-label]")
    assert "November 2026" in page.inner_text("[data-testid=calendar-label]")
    assert "Q3 draft" in page.inner_text("table")
