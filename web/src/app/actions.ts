"use server";

import { revalidatePath } from "next/cache";
import { backend, unwrap, unwrapOrNull } from "@/lib/backend";
import type { ChatSessionView } from "@/lib/types";

// Server actions are reachable as plain POST endpoints, so every argument is
// validated here even though the UI only sends valid values.

function assertId(id: number): void {
  if (!Number.isInteger(id) || id <= 0) throw new Error(`invalid id: ${id}`);
}

function refresh(): void {
  revalidatePath("/");
  revalidatePath("/calendar");
}

export async function setTaskStatus(taskId: number, status: string): Promise<void> {
  assertId(taskId);
  if (status !== "open" && status !== "done" && status !== "cancelled") {
    throw new Error(`invalid status: ${status}`);
  }
  await unwrap(
    backend.POST("/api/tasks/{task_id}/status", {
      params: { path: { task_id: taskId } },
      body: { status },
    }),
  );
  refresh();
}

export async function splitTask(taskId: number): Promise<void> {
  assertId(taskId);
  await unwrap(
    backend.POST("/api/tasks/{task_id}/split", { params: { path: { task_id: taskId } } }),
  );
  refresh();
}

export async function acceptSuggestion(suggestionId: number, keep?: number): Promise<void> {
  assertId(suggestionId);
  if (keep !== undefined) assertId(keep);
  await unwrap(
    backend.POST("/api/suggestions/{suggestion_id}/accept", {
      params: { path: { suggestion_id: suggestionId } },
      body: { keep: keep ?? null },
    }),
  );
  refresh();
}

export async function rejectSuggestion(suggestionId: number): Promise<void> {
  assertId(suggestionId);
  await unwrap(
    backend.POST("/api/suggestions/{suggestion_id}/reject", {
      params: { path: { suggestion_id: suggestionId } },
    }),
  );
  refresh();
}

export async function reextractThread(gmailThreadId: string): Promise<void> {
  if (!/^[A-Za-z0-9_.#-]+$/.test(gmailThreadId)) throw new Error("invalid thread id");
  await unwrap(
    backend.POST("/api/threads/{gmail_thread_id}/reextract", {
      params: { path: { gmail_thread_id: gmailThreadId } },
    }),
  );
  refresh();
}

export async function runSync(_prev: string | null, _formData: FormData): Promise<string> {
  const banner = await unwrap(backend.POST("/api/sync", {}));
  refresh();
  return banner.message;
}

// -- chat (the browser relays decisions; the backend owns the state) ----------------

export async function getChatSession(sessionId: number): Promise<ChatSessionView | null> {
  assertId(sessionId);
  return unwrapOrNull(backend.GET("/api/chat/sessions/{session_id}", {
    params: { path: { session_id: sessionId } },
  }));
}

export async function createChatSession(): Promise<ChatSessionView> {
  return unwrap(backend.POST("/api/chat/sessions", {}));
}

export async function sendChatMessage(sessionId: number, text: string): Promise<ChatSessionView> {
  assertId(sessionId);
  const trimmed = text.trim();
  if (trimmed.length < 1 || trimmed.length > 4000) throw new Error("message must be 1-4000 chars");
  return unwrap(
    backend.POST("/api/chat/sessions/{session_id}/messages", {
      params: { path: { session_id: sessionId } },
      body: { text: trimmed },
    }),
  );
}

export async function approveChatSession(
  sessionId: number,
  version: number,
  decisions: Record<string, string>,
): Promise<ChatSessionView> {
  assertId(sessionId);
  if (!Number.isInteger(version) || version < 0) throw new Error(`invalid version: ${version}`);
  const clean: Record<string, "approve" | "deny"> = {};
  for (const [toolCallId, decision] of Object.entries(decisions)) {
    if (decision !== "approve" && decision !== "deny") throw new Error(`invalid decision: ${decision}`);
    clean[toolCallId] = decision;
  }
  return unwrap(
    backend.POST("/api/chat/sessions/{session_id}/approve", {
      params: { path: { session_id: sessionId } },
      body: { version, decisions: clean },
    }),
  );
}
