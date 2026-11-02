import { setTaskStatus, splitTask } from "@/app/actions";
import SubmitButton from "@/components/submit-button";
import type { TaskView } from "@/lib/types";
import { badge } from "@/lib/ui";

export default function TaskTable({ tasks }: { tasks: TaskView[] }) {
  return (
    <table className="w-full border-collapse bg-white text-left text-sm">
      <thead>
        <tr className="border-b text-xs uppercase tracking-wide text-gray-500">
          <th className="px-2 py-2">Task</th>
          <th className="px-2 py-2">Owner</th>
          <th className="px-2 py-2">Due</th>
          <th className="px-2 py-2">Status</th>
          <th className="px-2 py-2" />
        </tr>
      </thead>
      <tbody>
        {tasks.map((task) => (
          <tr key={task.id} data-testid={`task-${task.id}`} className="border-b border-gray-200 align-top">
            <td className="px-2 py-2 font-medium">
              {task.title}
              {task.needs_review && <span className={`ml-2 ${badge("review")}`}>review</span>}
            </td>
            <td className="px-2 py-2 text-gray-500">{task.owner_email ?? "—"}</td>
            <td className="px-2 py-2">{task.due_date ?? "—"}</td>
            <td className="px-2 py-2">
              <span className={badge(task.status)}>{task.status}</span>
            </td>
            <td className="px-2 py-2">
              <div className="flex flex-wrap gap-2">
                <form action={setTaskStatus.bind(null, task.id, task.status !== "open" ? "open" : "done")}>
                  <SubmitButton testid={`task-toggle-${task.id}`}>
                    {task.status !== "open" ? "Mark open" : "Mark done"}
                  </SubmitButton>
                </form>
                {task.merged && (
                  <form action={splitTask.bind(null, task.id)}>
                    <SubmitButton>Split (undo merge)</SubmitButton>
                  </form>
                )}
              </div>
            </td>
          </tr>
        ))}
        {tasks.length === 0 && (
          <tr>
            <td colSpan={5} className="px-2 py-2 text-gray-500">
              No tasks yet — run a sync.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
