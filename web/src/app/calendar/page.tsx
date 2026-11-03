import Link from "next/link";
import { backend, unwrap } from "@/lib/backend";
import { currentMonth, monthGrid, todayIso } from "@/lib/calendar";
import { Icon } from "@/components/icons";
import type { TaskView } from "@/lib/types";

export const dynamic = "force-dynamic";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default async function CalendarPage({
  searchParams,
}: {
  searchParams: Promise<{ month?: string }>;
}) {
  const { month } = await searchParams;
  const timeZone = process.env.APP_TIME_ZONE ?? "UTC";
  // Malformed ?month= falls back to the current month instead of NaN dates.
  const valid = month && /^\d{4}-(0[1-9]|1[0-2])$/.test(month) ? month : undefined;
  const grid = monthGrid(valid ?? currentMonth(timeZone));

  // Query the VISIBLE grid (leading/trailing days from neighboring months),
  // not just the month — parity with what the grid renders.
  const tasks = await unwrap(
    backend.GET("/api/calendar", {
      params: { query: { start: grid.weeks[0][0].iso, end: grid.weeks[grid.weeks.length - 1][6].iso } },
    }),
  );
  const byDate = new Map<string, TaskView[]>();
  for (const task of tasks) {
    if (!task.due_date) continue;
    byDate.set(task.due_date, [...(byDate.get(task.due_date) ?? []), task]);
  }
  const today = todayIso(timeZone);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="calendar-label">
            {grid.label}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {tasks.length} {tasks.length === 1 ? "task" : "tasks"} with due dates this month
          </p>
        </div>
        <div className="flex items-center rounded-lg border border-gray-300 bg-white shadow-sm">
          <Link
            href={`/calendar?month=${grid.prev}`}
            className="flex items-center gap-1.5 rounded-l-lg px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            ← {grid.prev}
          </Link>
          <div className="h-5 w-px bg-gray-200" />
          <Link
            href={`/calendar?month=${grid.next}`}
            className="flex items-center gap-1.5 rounded-r-lg px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            {grid.next} →
          </Link>
        </div>
      </header>

      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
        <table className="w-full table-fixed border-collapse">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50/60">
              {WEEKDAYS.map((d) => (
                <th key={d} className="px-2 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-400">
                  {d}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.weeks.map((week, i) => (
              <tr key={i}>
                {week.map((day) => (
                  <td
                    key={day.iso}
                    className={`h-28 border-b border-r border-gray-100 p-1.5 align-top text-sm last:border-r-0 ${
                      day.inMonth ? "bg-white" : "bg-gray-50/60 text-gray-300"
                    } ${day.iso === today ? "bg-indigo-50/50 outline outline-2 -outline-offset-2 outline-indigo-400" : ""}`}
                  >
                    {day.day && (
                      <span
                        className={`text-xs font-semibold ${day.iso === today ? "flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-white" : "text-gray-700"}`}
                      >
                        {day.day}
                      </span>
                    )}
                    {(byDate.get(day.iso) ?? []).map((task) => (
                      <Link
                        key={task.id}
                        href={`/?q=${encodeURIComponent(task.title)}`}
                        title={task.title}
                        className="mt-1 block truncate rounded-md border-l-2 border-indigo-400 bg-indigo-50 px-1.5 py-0.5 text-[11px] font-medium text-indigo-900 hover:bg-indigo-100"
                      >
                        {task.title.length > 24 ? `${task.title.slice(0, 24)}…` : task.title}
                      </Link>
                    ))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center gap-2 text-xs text-gray-400">
        <Icon name="calendar" className="h-3.5 w-3.5" />
        Today is highlighted; events show tasks by due date. Click a task to filter the task list.
      </div>
    </div>
  );
}
