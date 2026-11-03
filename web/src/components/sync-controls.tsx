"use client";

import { useActionState } from "react";
import { runSync } from "@/app/actions";
import SubmitButton from "@/components/submit-button";
import { Icon } from "@/components/icons";

export default function SyncControls({ enabled }: { enabled: boolean }) {
  const [message, formAction] = useActionState(runSync, null);

  if (!enabled) return null;

  return (
    <div className="flex items-center gap-2">
      <form action={formAction}>
        <SubmitButton kind="primary" testid="sync-button">
          <Icon name="refresh" className="h-3.5 w-3.5" />
          Sync now
        </SubmitButton>
      </form>
      <span data-testid="sync-banner" className="text-xs text-gray-500">
        {message}
      </span>
    </div>
  );
}
