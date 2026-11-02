"use client";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const offline = /fetch failed|ECONNREFUSED|BackendError|network/i.test(error.message);
  return (
    <main className="my-8 rounded-lg border border-red-300 bg-red-50 p-6">
      <h2 className="mb-2 font-semibold text-red-800">
        {offline ? "Backend unreachable" : "Something went wrong"}
      </h2>
      <p className="mb-4 text-sm text-red-700">
        {offline
          ? "Could not reach the FastAPI backend — check that it is running and BACKEND_URL is set."
          : error.message}
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
