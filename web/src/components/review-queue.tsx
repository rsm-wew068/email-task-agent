import { acceptSuggestion, rejectSuggestion } from "@/app/actions";
import SubmitButton from "@/components/submit-button";
import type { SuggestionView } from "@/lib/types";

export default function ReviewQueue({ suggestions }: { suggestions: SuggestionView[] }) {
  if (suggestions.length === 0) {
    return <p className="text-sm text-gray-500">Nothing waiting for review.</p>;
  }

  return (
    <div data-testid="review-queue">
      {suggestions.map((s) => (
        <div key={s.id} className="my-2 border-l-4 border-amber-500 bg-amber-50 p-3">
          {s.kind === "possible_duplicate" ? (
            <>
              <strong>
                Possible duplicate:
              </strong>{" "}
              “{String(s.payload.new_title ?? "")}” looks like task #{s.other_task_id ?? "?"}.
              <div className="mt-2 flex flex-wrap gap-2">
                <form action={acceptSuggestion.bind(null, s.id, s.task_id ?? undefined)}>
                  <SubmitButton kind="approve">Merge into #{s.task_id ?? "?"}</SubmitButton>
                </form>
                <form action={acceptSuggestion.bind(null, s.id, s.other_task_id ?? undefined)}>
                  <SubmitButton>Keep the new one</SubmitButton>
                </form>
                <form action={rejectSuggestion.bind(null, s.id)}>
                  <SubmitButton kind="deny">Both are distinct</SubmitButton>
                </form>
              </div>
            </>
          ) : s.kind === "low_confidence_done" ? (
            <>
              <strong>Low-confidence “done”:</strong> task #{s.task_id ?? "?"} may be complete
              (“{String(s.payload.evidence_quote ?? "")}”).
              <div className="mt-2 flex flex-wrap gap-2">
                <form action={acceptSuggestion.bind(null, s.id, undefined)}>
                  <SubmitButton kind="approve">Mark done</SubmitButton>
                </form>
                <form action={rejectSuggestion.bind(null, s.id)}>
                  <SubmitButton kind="deny">Keep open</SubmitButton>
                </form>
              </div>
            </>
          ) : (
            <strong>
              {s.kind} — suggestion #{s.id}.
            </strong>
          )}
        </div>
      ))}
    </div>
  );
}
