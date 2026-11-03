import ChatPanel from "@/components/chat-panel";
import { backend, unwrapOrNull } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function ChatPage() {
  const meta = await unwrapOrNull(backend.GET("/api/meta", {}));

  return (
    <main>
      <section className="my-4">
        {meta === null ? (
          <p className="text-gray-500">The backend is not responding — see the notice above.</p>
        ) : meta.chat_enabled ? (
          <ChatPanel />
        ) : (
          <p className="text-gray-500">
            Chat is disabled: set LLM_API_KEY (or OPENAI_API_KEY) in the backend&apos;s .env and
            restart it.
          </p>
        )}
      </section>
    </main>
  );
}
