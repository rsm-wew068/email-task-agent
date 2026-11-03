"use client";

import { useActionState } from "react";
import { reextractThread } from "@/app/actions";
import SubmitButton from "@/components/submit-button";
import { Icon } from "@/components/icons";

export default function ReextractButton({ gmailThreadId }: { gmailThreadId: string }) {
  const [message, formAction] = useActionState(
    async (_prev: string | null, _formData: FormData) => reextractThread(gmailThreadId),
    null,
  );

  return (
    <div className="flex items-center justify-end gap-2">
      <form action={formAction}>
        <SubmitButton kind="ghost">
          <Icon name="refresh" className="h-3.5 w-3.5" />
          Re-extract
        </SubmitButton>
      </form>
      {message && <span className="text-xs text-gray-400">{message}</span>}
    </div>
  );
}
