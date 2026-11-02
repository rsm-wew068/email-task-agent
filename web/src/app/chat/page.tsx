import ChatPanel from "@/components/chat-panel";
import { backend, unwrapOrNull } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function ChatPage() {
  const meta = await unwrapOrNull(backend.GET("/api/meta", {}));

  return (
    <main>
      <section className="my-4">
        {meta?.chat_enabled ? (
          <ChatPanel />
        ) : (
          <p className="text-gray-500">
            Chat needs OPENAI_API_KEY (or a configured model) on the backend.
          </p>
        )}
      </section>
    </main>
  );
}
