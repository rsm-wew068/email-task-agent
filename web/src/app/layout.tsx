import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { backend, unwrapOrNull } from "@/lib/backend";
import type { MetaView } from "@/lib/types";
import { badge } from "@/lib/ui";
import { Icon } from "@/components/icons";
import { NavLink } from "@/components/nav-link";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "email-task-agent",
};

function Shell({ children, meta }: { children: React.ReactNode; meta: MetaView | null }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="min-h-screen antialiased">
        {/* Mobile top bar */}
        <div className="sticky top-0 z-20 flex items-center gap-4 border-b border-gray-200 bg-white/90 px-4 py-3 backdrop-blur lg:hidden">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white">
            <Icon name="mail" className="h-4 w-4" />
          </div>
          <span className="font-semibold">email-task-agent</span>
          <span className="ml-auto" data-testid="mode-badge">
            <span className={badge(meta ? meta.mode : "offline")}>{meta ? meta.mode : "offline"}</span>
          </span>
        </div>

        <div className="mx-auto flex max-w-[1400px]">
          {/* Desktop sidebar */}
          <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-gray-200 bg-white px-4 py-6 lg:flex">
            <div className="mb-8 flex items-center gap-3 px-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-md shadow-indigo-500/25">
                <Icon name="mail" className="h-4.5 w-4.5" />
              </div>
              <div className="leading-tight">
                <div className="text-sm font-semibold">email-task-agent</div>
                <div className="text-xs text-gray-400">Gmail → tasks</div>
              </div>
            </div>

            <nav className="flex flex-col gap-1">
              <NavLink href="/" icon="inbox" label="Tasks" exact />
              <NavLink href="/calendar" icon="calendar" label="Calendar" />
              <NavLink href="/chat" icon="chat" label="Chat" />
            </nav>

            <div className="mt-auto flex flex-col gap-2 px-2">
              <div className="rounded-xl bg-gray-50 p-3 text-xs text-gray-500">
                <div className="mb-1 flex items-center gap-1.5 font-medium text-gray-700">
                  <Icon name="shield" className="h-3.5 w-3.5" />
                  Instance
                </div>
                <div data-testid="mode-badge" className="flex items-center gap-2">
                  <span className={badge(meta ? meta.mode : "offline")}>{meta ? meta.mode : "offline"}</span>
                </div>
              </div>
            </div>
          </aside>

          {/* Content */}
          <main className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-10">
            <div className="mx-auto max-w-4xl">
              {!meta && (
                <div className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                  <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
                  <div>
                    <div className="font-semibold">Backend unreachable</div>
                    <div className="mt-0.5 text-red-700">
                      Start it with{" "}
                      <code className="rounded bg-red-100 px-1 py-0.5 font-mono text-xs">
                        uv run uvicorn email_task_agent.app.main:app_factory --reload
                      </code>{" "}
                      and check BACKEND_URL.
                    </div>
                  </div>
                </div>
              )}
              {children}
            </div>
          </main>
        </div>
      </body>
    </html>
  );
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const meta = await unwrapOrNull(backend.GET("/api/meta", {}));
  return <Shell meta={meta}>{children}</Shell>;
}
