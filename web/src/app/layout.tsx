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
          {children}
        </div>
      </body>
    </html>
  );
}
