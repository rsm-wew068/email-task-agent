import { todayIso } from "@/lib/calendar";
import ReviewQueue from "@/components/review-queue";
import ReextractButton from "@/components/reextract-button";
import SubmitButton from "@/components/submit-button";
import SyncControls from "@/components/sync-controls";
import TaskTable from "@/components/task-table";
import { Icon } from "@/components/icons";
import { formatWhen } from "@/lib/calendar";
import { backend, unwrap } from "@/lib/backend";
import type { TaskBoardView } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function TasksPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string }>;
}) {
  const { q, status } = await searchParams;
  const query: { q?: string; status?: string } = {};
  if (q) query.q = q;
  if (status) query.status = status;

  const [board, meta] = await Promise.all([
    unwrap(backend.GET("/api/tasks", { params: { query } })),
    unwrap(backend.GET("/api/meta", {})),
  ]);
  const today = todayIso(process.env.APP_TIME_ZONE ?? "UTC");

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Tasks</h1>
          <p className="mt-1 text-sm text-gray-500">
            {board.tasks.length} {board.tasks.length === 1 ? "task" : "tasks"}
            {q ? ` matching “${q}”` : ""} · synced from your mailbox
          </p>
        </div>
        <SyncControls enabled={meta.sync_enabled} />
      </header>

      <form method="get" action="/" className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Icon
            name="search"
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
          />
          <input
            type="search"
            name="q"
            defaultValue={q ?? ""}
            placeholder="Search tasks…"
            className="w-64 rounded-lg border border-gray-300 bg-white py-1.5 pl-8 pr-3 text-sm placeholder:text-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>
        <select
          name="status"
          defaultValue={status ?? ""}
          className="rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
        >
          <option value="">Any status</option>
          <option value="open">Open</option>
          <option value="done">Done</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <SubmitButton>Apply</SubmitButton>
      </form>

      <section className="flex flex-col gap-3" data-testid="review-queue-section">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Review queue
          {board.suggestions.length > 0 && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
              {board.suggestions.length}
            </span>
          )}
        </h2>
        <ReviewQueue suggestions={board.suggestions} />
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-gray-400">
          <Icon name="inbox" className="h-4 w-4" />
          All tasks
        </h2>
        <TaskTable tasks={board.tasks} today={today} />
      </section>

      <section className="flex flex-col gap-3 pb-8">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-gray-400">
          <Icon name="mail" className="h-4 w-4" />
          Threads
        </h2>
        <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/60 text-xs font-medium uppercase tracking-wider text-gray-400">
                <th className="px-4 py-2.5">Subject</th>
                <th className="px-4 py-2.5">Participants</th>
                <th className="px-4 py-2.5">Last message</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {board.threads.map((t) => (
                <tr key={t.id} className="transition-colors hover:bg-indigo-50/40">
                  <td className="px-4 py-2.5 font-medium text-gray-800">{t.subject ?? "(no subject)"}</td>
                  <td className="px-4 py-2.5 text-gray-500">{t.participants.join(", ")}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-gray-400">{
                    t.last_message_at ? formatWhen(t.last_message_at) : "—"
                  }</td>
                  <td className="px-4 py-2.5 text-right">
                    {meta.sync_enabled && <ReextractButton gmailThreadId={t.gmail_thread_id} />}
                  </td>
                </tr>
              ))}
              {board.threads.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-gray-400">
                    No threads loaded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
