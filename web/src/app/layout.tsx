import type { Metadata } from "next";
import Link from "next/link";
import { backend, unwrapOrNull } from "@/lib/backend";
import type { MetaView } from "@/lib/types";
import { badge } from "@/lib/ui";
import "./globals.css";

export const metadata: Metadata = {
  title: "email-task-agent",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const meta = await unwrapOrNull(backend.GET("/api/meta", {}));

  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <div className="mx-auto max-w-4xl p-4">
          <nav className="mb-6 flex items-baseline gap-4 border-b-2 border-gray-900 pb-2">
            <h1 className="m-0 text-lg font-bold">📧 email-task-agent</h1>
            <Link className="rounded px-1 py-0.5 hover:bg-gray-200" href="/">
              Tasks
            </Link>
            <Link className="rounded px-1 py-0.5 hover:bg-gray-200" href="/calendar">
              Calendar
            </Link>
            <Link className="rounded px-1 py-0.5 hover:bg-gray-200" href="/chat">
              Chat
            </Link>
            {meta ? (
              <span data-testid="mode-badge" className={badge(meta.mode)}>
                {meta.mode}
              </span>
            ) : (
              <span data-testid="mode-badge" className={badge("offline")}>
                backend offline
              </span>
            )}
          </nav>
          {/* Decided on the server, where meta is actually known — production
              error boundaries only see redacted messages (review finding 9). */}
          {!meta && (
            <div className="mb-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800">
              The FastAPI backend is not responding. Start it with{" "}
              <code>uv run uvicorn email_task_agent.app.main:app_factory --reload</code> and check
              BACKEND_URL.
            </div>
          )}
          {children}
        </div>
      </body>
    </html>
  );
}
