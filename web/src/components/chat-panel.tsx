"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import {
  approveChatSession,
  createChatSession,
  getChatSession,
  sendChatMessage,
} from "@/app/actions";
import { Icon } from "@/components/icons";
import { btn } from "@/lib/ui";
import type { ChatSessionView } from "@/lib/types";

const SESSION_KEY = "chat_session";

// The backend owns the state: this component renders whatever ChatSessionView
// comes back and never derives the state or version itself. Approve sends the
// version it rendered, so a double click or a second tab comes back stale.

function SendControls({ disabled }: { disabled: boolean }) {
  // An onSubmit form doesn't drive useFormStatus; the transition's pending
  // flag (passed in) does the actual disabling.
  return (
    <button
      type="submit"
      disabled={disabled}
      data-testid="chat-send"
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white shadow-sm shadow-indigo-600/25 transition-colors hover:bg-indigo-700 disabled:opacity-40"
      aria-label="Send"
    >
      <Icon name="send" className="h-4 w-4" />
    </button>
  );
}

export default function ChatPanel() {
  const [session, setSession] = useState<ChatSessionView | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [text, setText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  // React 19: isPending stays true until the async transition callback resolves.
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    startTransition(async () => {
      try {
        const stored = Number(window.localStorage.getItem(SESSION_KEY));
        let view = stored ? await getChatSession(stored) : null;
        if (!view) {
          view = await createChatSession();
        }
        window.localStorage.setItem(SESSION_KEY, String(view.session_id));
        setSession(view);
      } catch {
        setLoadError(true);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [session, pending]);

  function submit(fn: () => Promise<ChatSessionView>): void {
    startTransition(async () => {
      const view = await fn();
      setSession(view);
    });
  }

  function sendMessage(): void {
    const current = session;
    if (!current) return;
    const body = text;
    submit(async () => {
      try {
        const view = await sendChatMessage(current.session_id, body);
        setText(""); // clear only after success, so a failed send keeps the draft
        return view;
      } catch {
        return { ...current, error: "Could not send — is the backend up?" };
      }
    });
  }

  function decide(form: FormData): void {
    const current = session;
    if (!current) return;
    const decisions: Record<string, string> = {};
    for (const action of current.actions) {
      const value = form.get(`decision-${action.tool_call_id}`);
      decisions[action.tool_call_id] = typeof value === "string" ? value : "approve";
    }
    submit(async () => {
      try {
        return await approveChatSession(current.session_id, current.version, decisions);
      } catch {
        return { ...current, error: "Could not submit decisions — is the backend up?" };
      }
    });
  }

  const headerStatus =
    session?.state === "running"
      ? { label: "Thinking…", color: "bg-amber-400" }
      : session?.state === "awaiting_approval"
        ? { label: "Waiting for your decision", color: "bg-amber-400" }
        : session?.state === "failed"
          ? { label: "Failed — retryable", color: "bg-red-400" }
          : { label: "Online", color: "bg-emerald-500" };

  return (
    <div
      data-testid="chat-panel"
      className="flex h-[calc(100vh-9rem)] min-h-[480px] flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm"
    >
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-gray-100 px-5 py-3.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-white">
          <Icon name="spark" className="h-4 w-4" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">Assistant</div>
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <span className={`h-1.5 w-1.5 rounded-full ${headerStatus.color}`} />
            {session ? headerStatus.label : loadError ? "Offline" : "Connecting…"}
          </div>
        </div>
      </div>

      {/* Transcript */}
      <div ref={scrollRef} data-testid="chat-messages" className="scroll-slim flex-1 overflow-y-auto px-5 py-4">
        {loadError && !session ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-gray-400">
            <Icon name="alert" className="h-5 w-5" />
            Chat unavailable — the backend is not responding.
          </div>
        ) : !session ? (
          <div className="flex h-full items-center justify-center gap-1 text-sm text-gray-400">
            Connecting
            <span className="thinking-dot">·</span>
            <span className="thinking-dot">·</span>
            <span className="thinking-dot">·</span>
          </div>
        ) : (
          <div className="flex flex-col gap-2.5">
            {session.messages.map((message, index) => (
              <div
                key={index}
                className={
                  message.role === "user"
                    ? "ml-auto max-w-[80%] rounded-2xl rounded-br-md bg-indigo-600 px-3.5 py-2 text-sm text-white"
                    : message.role === "tool_call"
                      ? "mx-auto max-w-[90%] rounded-lg bg-gray-50 px-3 py-1.5 text-center font-mono text-[11px] text-gray-500"
                      : "mr-auto max-w-[80%] rounded-2xl rounded-bl-md border border-gray-100 bg-gray-50 px-3.5 py-2 text-sm text-gray-800"
                }
              >
                {message.role === "tool_call" && (
                  <Icon name="wrench" className="mr-1.5 inline h-3 w-3 align-[-2px]" />
                )}
                {message.text}
              </div>
            ))}
          </div>
        )}

        {session?.error && (
          <div
            data-testid="chat-error"
            className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
          >
            <Icon name="alert" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />
            {session.error}
          </div>
        )}
      </div>

      {/* Approval card */}
      {session && session.actions.length > 0 && (session.state === "awaiting_approval" || session.state === "failed") && (
        <form
          data-testid="approval-form"
          className="border-t border-amber-200 bg-amber-50/70 px-5 py-4"
          action={(formData) => decide(formData)}
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
            <Icon name="shield" className="h-4 w-4 text-amber-600" />
            Approval required
            {session.state === "failed" && (
              <span className="text-xs font-normal text-red-600">— previous attempt failed, decide again</span>
            )}
          </div>
          {session.actions.map((action) => (
            <fieldset key={action.tool_call_id} data-testid="pending-action" className="mt-3 rounded-lg border border-amber-200 bg-white p-3">
              <legend className="px-1 font-mono text-xs font-semibold text-amber-800">{action.tool_name}</legend>
              <pre className="scroll-slim max-h-32 overflow-auto rounded-md bg-gray-950 p-2.5 text-xs leading-relaxed text-gray-100">
                {JSON.stringify(action.args, null, 2)}
              </pre>
              <div className="mt-2 flex gap-5 text-sm">
                <label className="flex items-center gap-1.5 text-emerald-700">
                  <input
                    type="radio"
                    name={`decision-${action.tool_call_id}`}
                    value="approve"
                    defaultChecked
                    disabled={pending}
                    className="accent-emerald-600"
                  />
                  Approve
                </label>
                <label className="flex items-center gap-1.5 text-red-600">
                  <input
                    type="radio"
                    name={`decision-${action.tool_call_id}`}
                    value="deny"
                    disabled={pending}
                    className="accent-red-600"
                  />
                  Deny
                </label>
              </div>
            </fieldset>
          ))}
          <div className="mt-3 flex justify-end">
            <button type="submit" disabled={pending} data-testid="approve-submit" className={btn("primary")}>
              Submit decisions
            </button>
          </div>
        </form>
      )}

      {/* Input / states */}
      {session && (session.state === "idle" || (session.state === "failed" && session.actions.length === 0)) && (
        <form
          className="border-t border-gray-100 px-4 py-3"
          onSubmit={(event) => {
            event.preventDefault();
            sendMessage();
          }}
        >
          <div className="flex items-center gap-2">
            <input
              type="text"
              data-testid="chat-input"
              name="message"
              placeholder="Ask about your tasks…"
              autoComplete="off"
              className="h-9 flex-1 rounded-full border border-gray-300 bg-gray-50 px-4 text-sm placeholder:text-gray-400 focus:border-indigo-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              value={text}
              onChange={(event) => setText(event.target.value)}
              disabled={pending}
            />
            <SendControls disabled={pending || text.trim().length === 0} />
          </div>
        </form>
      )}

      {session?.state === "running" && (
        <div className="border-t border-gray-100 px-4 py-3 text-sm text-gray-400">
          Thinking
          <span className="thinking-dot ml-1">·</span>
          <span className="thinking-dot ml-0.5">·</span>
          <span className="thinking-dot ml-0.5">·</span>
        </div>
      )}

      {session && !showInput(session) && session.state !== "running" && session.actions.length > 0 && (
        <div className="border-t border-gray-100 px-4 py-3 text-xs text-gray-400">
          Decide on the pending action above before continuing.
        </div>
      )}
    </div>
  );
}

function showInput(session: ChatSessionView): boolean {
  return session.state === "idle" || (session.state === "failed" && session.actions.length === 0);
}
