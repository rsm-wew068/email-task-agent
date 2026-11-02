"use client";

import { useActionState } from "react";
import { runSync } from "@/app/actions";
import SubmitButton from "@/components/submit-button";

export default function SyncControls({ enabled }: { enabled: boolean }) {
  const [message, formAction] = useActionState(runSync, null);

  if (!enabled) return null;

  return (
    <form action={formAction} className="inline">
      <SubmitButton kind="primary" testid="sync-button">
        Sync now
      </SubmitButton>{" "}
      <span data-testid="sync-banner" className="text-sm text-gray-500">
        {message}
      </span>
    </form>
  );
}
