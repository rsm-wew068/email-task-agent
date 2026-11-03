import { acceptSuggestion, rejectSuggestion } from "@/app/actions";
import SubmitButton from "@/components/submit-button";
import { Icon } from "@/components/icons";
import type { SuggestionView } from "@/lib/types";

export default function ReviewQueue({ suggestions }: { suggestions: SuggestionView[] }) {
  if (suggestions.length === 0) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-400">
        <Icon name="check" className="h-4 w-4 text-emerald-500" />
        Nothing waiting for review.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="review-queue">
      {suggestions.map((s) => (
        <div
          key={s.id}
          className="rounded-xl border border-amber-200 bg-gradient-to-r from-amber-50 to-white p-4"
        >
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-100 text-amber-700">
              <Icon name={s.kind === "possible_duplicate" ? "merge" : "check"} className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              {s.kind === "possible_duplicate" ? (
                <>
                  <div className="text-sm font-medium text-gray-900">
                    Possible duplicate of task #{s.other_task_id ?? "?"}
                  </div>
                  <div className="mt-1 text-sm text-gray-600">
                    “{String(s.payload.new_title ?? "")}” looks like task #{s.task_id ?? "?"}.
                  </div>
                </>
              ) : s.kind === "low_confidence_done" ? (
                <>
                  <div className="text-sm font-medium text-gray-900">
                    Low-confidence “done” on task #{s.task_id ?? "?"}
                  </div>
                  <blockquote className="mt-1 border-l-2 border-amber-300 pl-2 text-sm italic text-gray-600">
                    {String(s.payload.evidence_quote ?? "")}
                  </blockquote>
                </>
              ) : (
                <div className="text-sm font-medium text-gray-900">
                  {s.kind} — suggestion #{s.id}
                </div>
              )}

              <div className="mt-3 flex flex-wrap gap-2">
                {s.kind === "possible_duplicate" ? (
                  <>
                    <form action={acceptSuggestion.bind(null, s.id, s.task_id ?? undefined)}>
                      <SubmitButton kind="approve">Merge into #{s.task_id ?? "?"}</SubmitButton>
                    </form>
                    <form action={acceptSuggestion.bind(null, s.id, s.other_task_id ?? undefined)}>
                      <SubmitButton>Keep the new one</SubmitButton>
                    </form>
                    <form action={rejectSuggestion.bind(null, s.id)}>
                      <SubmitButton kind="danger-ghost">Both are distinct</SubmitButton>
                    </form>
                  </>
                ) : s.kind === "low_confidence_done" ? (
                  <>
                    <form action={acceptSuggestion.bind(null, s.id, undefined)}>
                      <SubmitButton kind="approve">Mark done</SubmitButton>
                    </form>
                    <form action={rejectSuggestion.bind(null, s.id)}>
                      <SubmitButton kind="danger-ghost">Keep open</SubmitButton>
                    </form>
                  </>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
