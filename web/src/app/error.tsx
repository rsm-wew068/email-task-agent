"use client";

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
    <main className="my-8 rounded-lg border border-red-300 bg-red-50 p-6">
      <h2 className="mb-2 font-semibold text-red-800">Something went wrong</h2>
      <p className="mb-4 text-sm text-red-700">
        The page failed to render. Check the backend-offline notice above if one is showing.
      </p>
      <button
        className="rounded-md border border-red-400 bg-white px-3 py-1.5 text-sm font-medium hover:bg-red-100"
        onClick={reset}
      >
        Retry
      </button>
    </main>
  );
}
