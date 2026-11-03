"use client";

import { useEffect, useState, useTransition } from "react";
import {
  approveChatSession,
  createChatSession,
  getChatSession,
  sendChatMessage,
} from "@/app/actions";
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
    <button type="submit" className={btn("primary")} disabled={disabled} data-testid="chat-send">
      Send
    </button>
  );
}

export default function ChatPanel() {
  const [session, setSession] = useState<ChatSessionView | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [text, setText] = useState("");
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
        setLoadError(true); // "unavailable" only for a recorded load failure
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  if (!session) {
    return (
      <div data-testid="chat-panel" className="flex flex-col gap-2">
        {loadError ? (
          <p className="text-gray-500">Chat unavailable — the backend is not responding.</p>
        ) : (
          <p className="text-gray-500">Connecting…</p>
        )}
      </div>
    );
  }

  const showApproval =
    session.actions.length > 0 && (session.state === "awaiting_approval" || session.state === "failed");
  const showInput = session.state === "idle" || (session.state === "failed" && session.actions.length === 0);

  return (
    <div data-testid="chat-panel" className="flex flex-col gap-2">
      <div data-testid="chat-messages" className="flex flex-col gap-2">
        {session.messages.map((message, index) => (
          <div
            key={index}
            className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${
              message.role === "user"
                ? "self-end bg-indigo-100"
                : message.role === "tool_call"
                  ? "self-start border border-dashed border-gray-300 bg-white font-mono text-xs"
                  : "self-start border border-gray-200 bg-white"
            }`}
          >
            {message.text}
          </div>
        ))}
      </div>

      {session.error && (
        <div data-testid="chat-error" className="self-start rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {session.error}
        </div>
      )}

      {showApproval && (
        <form
          data-testid="approval-form"
          className="rounded-lg border border-amber-400 bg-amber-50 p-3"
          action={(formData) => decide(formData)}
        >
          {session.state === "failed" && (
            <p className="mb-2 text-sm text-red-700">The previous attempt failed — you can decide again.</p>
          )}
          <strong className="text-sm">The assistant wants to:</strong>
          {session.actions.map((action) => (
            <fieldset key={action.tool_call_id} data-testid="pending-action" className="mt-2">
              <legend className="font-mono text-sm">{action.tool_name}</legend>
              <pre className="max-w-full overflow-x-auto bg-white p-2 text-xs">
                {JSON.stringify(action.args, null, 2)}
              </pre>
              <div className="mt-1 flex gap-4 text-sm">
                <label>
                  <input
                    type="radio"
                    name={`decision-${action.tool_call_id}`}
                    value="approve"
                    defaultChecked
                    disabled={pending}
                  />{" "}
                  Approve
                </label>
                <label>
                  <input type="radio" name={`decision-${action.tool_call_id}`} value="deny" disabled={pending} /> Deny
                </label>
              </div>
            </fieldset>
          ))}
          <div className="mt-3">
            <button type="submit" className={btn("primary")} disabled={pending} data-testid="approve-submit">
              Submit decisions
            </button>
          </div>
        </form>
      )}

      {showInput && (
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            sendMessage();
          }}
        >
          <input
            type="text"
            data-testid="chat-input"
            name="message"
            placeholder="Ask about your tasks…"
            autoComplete="off"
            className="w-full rounded border border-gray-300 px-2 py-1.5"
            value={text}
            onChange={(event) => setText(event.target.value)}
            disabled={pending}
          />
          <SendControls disabled={pending} />
        </form>
      )}

      {session.state === "running" && <p className="text-sm text-gray-500">Thinking…</p>}
      {!showInput && !showApproval && session.state !== "running" && (
        <p className="text-sm text-gray-500">Decide on the pending action above before continuing.</p>
      )}
    </div>
  );
}
