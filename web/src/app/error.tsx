"use client";

import { Icon } from "@/components/icons";
import { btn } from "@/lib/ui";

export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // Server Component error messages are redacted in production builds, so no
  // message matching here — the offline banner lives in the layout, which
  // knows the real state (review finding 9).
  return (
    <main className="my-12 flex flex-col items-center gap-3 rounded-2xl border border-red-200 bg-red-50 p-10 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-100 text-red-500">
        <Icon name="alert" className="h-5 w-5" />
      </div>
      <h2 className="font-semibold text-red-800">Something went wrong</h2>
      <p className="max-w-sm text-sm text-red-700">
        The page failed to render. Check the backend-offline notice above if one is showing.
      </p>
      <button className={btn("default")} onClick={reset}>
        Retry
      </button>
    </main>
  );
}
