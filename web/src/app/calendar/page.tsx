import Link from "next/link";
import { backend, unwrap } from "@/lib/backend";
import { currentMonth, monthGrid, todayIso } from "@/lib/calendar";
import type { TaskView } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function CalendarPage({
  searchParams,
}: {
  searchParams: Promise<{ month?: string }>;
}) {
  const { month } = await searchParams;
  const timeZone = process.env.APP_TIME_ZONE ?? "UTC";
  const grid = monthGrid(month ?? currentMonth(timeZone));

  const tasks = await unwrap(
    backend.GET("/api/calendar", {
      params: { query: { start: grid.first, end: grid.last } },
    }),
  );
  const byDate = new Map<string, TaskView[]>();
  for (const task of tasks) {
    if (!task.due_date) continue;
    byDate.set(task.due_date, [...(byDate.get(task.due_date) ?? []), task]);
  }
  const today = todayIso(timeZone);

  return (
    <main>
      <section>
        <h2 className="mb-2 font-semibold" data-testid="calendar-label">
          {grid.label}
        </h2>
        <nav className="mb-3 flex gap-4 text-sm">
          <Link href={`/calendar?month=${grid.prev}`}>← {grid.prev}</Link>
          <Link href={`/calendar?month=${grid.next}`}>{grid.next} →</Link>
        </nav>
        <table className="w-full table-fixed border-collapse bg-white">
          <thead>
            <tr className="text-xs uppercase text-gray-500">
              {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
                <th key={d} className="px-2 py-1 text-left">
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
                    className={`h-24 w-[14.2%] border border-gray-200 p-1 align-top text-sm ${
                      day.inMonth ? "" : "bg-gray-50 text-gray-400"
                    } ${day.iso === today ? "outline outline-2 outline-indigo-500" : ""}`}
                  >
                    {day.day && <strong className="text-xs">{day.day}</strong>}
                    {(byDate.get(day.iso) ?? []).map((task) => (
                      <Link
                        key={task.id}
                        href={`/?q=${encodeURIComponent(task.title)}`}
                        className="my-0.5 block rounded bg-indigo-100 px-1 py-0.5 text-xs text-gray-900"
                        title={task.title}
                      >
                        {task.title.length > 26 ? `${task.title.slice(0, 26)}…` : task.title}
                      </Link>
                    ))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
