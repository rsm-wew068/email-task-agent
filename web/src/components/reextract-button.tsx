"use client";

import { useActionState } from "react";
import { reextractThread } from "@/app/actions";
import SubmitButton from "@/components/submit-button";

export default function ReextractButton({ gmailThreadId }: { gmailThreadId: string }) {
  const [message, formAction] = useActionState(
    async (_prev: string | null, _formData: FormData) => reextractThread(gmailThreadId),
    null,
  );

  return (
    <form action={formAction} className="inline">
      <SubmitButton>Re-extract</SubmitButton>
      {message && <span className="ml-2 text-xs text-gray-500">{message}</span>}
    </form>
  );
}
