import "server-only";

import createClient from "openapi-fetch";
import type { paths } from "./api-schema";

export const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export const backend = createClient<paths>({
  baseUrl: BACKEND_URL,
  fetch(request) {
    return fetch(request, { cache: "no-store" });
  },
});

export class BackendError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** Throws on transport/HTTP errors so page error boundaries catch them. */
export async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await promise;
  if (error !== undefined) {
    const detail =
      typeof error === "object" && error !== null && "detail" in error
        ? String((error as { detail: unknown }).detail)
        : JSON.stringify(error);
    throw new BackendError(detail, response.status);
  }
  if (!response.ok) {
    throw new BackendError(`${response.status} ${response.statusText}`, response.status);
  }
  return data as T;
}

/** Null on ANY non-OK status — for /api/meta, where any failure means "offline".
 *  (Chat session lookup must distinguish 404 from transient errors and does
 *  its own handling in actions.ts.) */
export async function unwrapOrNull<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T | null> {
  const { data, response } = await promise;
  if (!response.ok) return null;
  return (data ?? null) as T | null;
}
