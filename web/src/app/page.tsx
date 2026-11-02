import { reextractThread } from "@/app/actions";
import ReviewQueue from "@/components/review-queue";
import SubmitButton from "@/components/submit-button";
import SyncControls from "@/components/sync-controls";
import TaskTable from "@/components/task-table";
import { backend, unwrap } from "@/lib/backend";
import type { MetaView, TaskBoardView } from "@/lib/types";

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

  return (
    <main>
      <section className="mb-6">
        <form method="get" action="/" className="mr-3 inline-flex flex-wrap items-center gap-2">
          <input
            type="search"
            name="q"
            defaultValue={q ?? ""}
            placeholder="search tasks…"
            className="rounded border border-gray-300 px-2 py-1.5"
          />
          <select name="status" defaultValue={status ?? ""} className="rounded border border-gray-300 px-2 py-1.5">
            <option value="">any status</option>
            <option value="open">open</option>
            <option value="done">done</option>
            <option value="cancelled">cancelled</option>
          </select>
          <SubmitButton>Filter</SubmitButton>
        </form>
        <SyncControls enabled={meta.sync_enabled} />
      </section>

      <section className="my-6" data-testid="review-queue-section">
        <h2 className="mb-2 font-semibold">Review queue</h2>
        <ReviewQueue suggestions={board.suggestions} />
      </section>

      <section className="my-6">
        <h2 className="mb-2 font-semibold">
          Tasks {q ? `matching “${q}”` : ""} ({board.tasks.length})
        </h2>
        <TaskTable tasks={board.tasks} />
      </section>

      <section className="my-6">
        <h2 className="mb-2 font-semibold">Threads</h2>
        <table className="w-full border-collapse bg-white text-left text-sm">
          <thead>
            <tr className="border-b text-xs uppercase tracking-wide text-gray-500">
              <th className="px-2 py-2">Subject</th>
              <th className="px-2 py-2">Participants</th>
              <th className="px-2 py-2">Last message</th>
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {board.threads.map((t) => (
              <tr key={t.id} className="border-b border-gray-200">
                <td className="px-2 py-2">{t.subject ?? "(no subject)"}</td>
                <td className="px-2 py-2 text-gray-500">{t.participants.join(", ")}</td>
                <td className="px-2 py-2 text-gray-500">{t.last_message_at ?? "—"}</td>
                <td className="px-2 py-2">
                  <form action={reextractThread.bind(null, t.gmail_thread_id)}>
                    <SubmitButton>Re-extract</SubmitButton>
                  </form>
                </td>
              </tr>
            ))}
            {board.threads.length === 0 && (
              <tr>
                <td colSpan={4} className="px-2 py-2 text-gray-500">
                  No threads loaded.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </main>
  );
}

export type { MetaView, TaskBoardView };
