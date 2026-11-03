import { setTaskStatus, splitTask } from "@/app/actions";
import SubmitButton from "@/components/submit-button";
import { Icon } from "@/components/icons";
import type { TaskView } from "@/lib/types";
import { avatarClasses, badge, initialsOf, statusDot } from "@/lib/ui";

function DueChip({ due, today }: { due: string | null; today: string }) {
  if (!due) return <span className="text-gray-400">—</span>;
  const overdue = due < today;
  const isToday = due === today;
  const cls = overdue
    ? "bg-red-50 text-red-700"
    : isToday
      ? "bg-amber-100 text-amber-800"
      : "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${cls}`}>
      {overdue && <Icon name="alert" className="h-3 w-3" />}
      {due}
      {isToday && " · today"}
      {overdue && " · overdue"}
    </span>
  );
}

export default function TaskTable({ tasks, today }: { tasks: TaskView[]; today: string }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50/60 text-xs font-medium uppercase tracking-wider text-gray-400">
            <th className="px-4 py-2.5">Task</th>
            <th className="px-4 py-2.5">Owner</th>
            <th className="px-4 py-2.5">Due</th>
            <th className="px-4 py-2.5">Status</th>
            <th className="px-4 py-2.5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {tasks.map((task) => (
            <tr key={task.id} data-testid={`task-${task.id}`} className="group transition-colors hover:bg-indigo-50/40">
              <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{task.title}</span>
                  {task.needs_review && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-800">
                      <Icon name="alert" className="h-3 w-3" />
                      review
                    </span>
                  )}
                </div>
                {task.merged && (
                  <div className="mt-0.5 text-xs text-gray-400">merged thread — undo below</div>
                )}
                {task.evidence_quote && (
                  <blockquote className="mt-1.5 max-w-md truncate border-l-2 border-indigo-200 pl-2 text-xs italic text-gray-500" title={task.evidence_quote}>
                    “{task.evidence_quote}”
                  </blockquote>
                )}
              </td>
              <td className="px-4 py-3">
                {task.owner_email ? (
                  <span className="flex items-center gap-2 text-gray-600">
                    <span className={avatarClasses()}>{initialsOf(task.owner_email)}</span>
                    <span className="hidden xl:inline">{task.owner_email}</span>
                  </span>
                ) : (
                  <span className="text-gray-400">unassigned</span>
                )}
              </td>
              <td className="px-4 py-3">
                <DueChip due={task.due_date} today={today} />
              </td>
              <td className="px-4 py-3">
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-600">
                  <span className={`h-1.5 w-1.5 rounded-full ${statusDot(task.status)}`} />
                  {task.status}
                </span>
              </td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap justify-end gap-2 opacity-80 group-hover:opacity-100">
                  <form action={setTaskStatus.bind(null, task.id, task.status !== "open" ? "open" : "done")}>
                    <SubmitButton testid={`task-toggle-${task.id}`}>
                      {task.status !== "open" ? "Reopen" : "Done"}
                    </SubmitButton>
                  </form>
                  {task.merged && (
                    <form action={splitTask.bind(null, task.id)}>
                      <SubmitButton kind="ghost">
                        <Icon name="split" className="h-3.5 w-3.5" />
                        Split
                      </SubmitButton>
                    </form>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {tasks.length === 0 && (
            <tr>
              <td colSpan={5} className="px-4 py-12">
                <div className="flex flex-col items-center gap-2 text-center">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gray-100 text-gray-400">
                    <Icon name="inbox" className="h-5 w-5" />
                  </div>
                  <div className="text-sm font-medium text-gray-700">No tasks found</div>
                  <div className="text-xs text-gray-400">
                    Run a sync, or adjust the filters above.
                  </div>
                </div>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
