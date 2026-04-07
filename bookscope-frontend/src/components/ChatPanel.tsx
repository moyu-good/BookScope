import { useState, useRef, useCallback } from "react";
import { Send, Loader2 } from "lucide-react";
import { chatSSE } from "../lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface ChatPanelProps {
  sessionId: string;
}

export default function ChatPanel({ sessionId }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const send = useCallback(() => {
    const q = input.trim();
    if (!q || loading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setLoading(true);

    controllerRef.current = chatSSE(
      sessionId,
      q,
      "en",
      (content) => {
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant") {
            return [...prev.slice(0, -1), { role: "assistant", content: last.content + content }];
          }
          return [...prev, { role: "assistant", content }];
        });
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
      },
      () => setLoading(false),
      (err) => {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err.message}` },
        ]);
        setLoading(false);
      }
    );
  }, [sessionId, input, loading]);

  return (
    <div className="bg-[var(--bs-surface)] rounded-2xl border border-[var(--bs-border)] flex flex-col h-[600px]">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-16 text-[var(--bs-text-muted)]">
            <p className="text-lg mb-2">Ask anything about this book</p>
            <p className="text-sm">Uses RAG-powered retrieval for accurate answers</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-[var(--bs-accent)] text-white rounded-br-md"
                  : "bg-[var(--bs-bg)] text-[var(--bs-text)] rounded-bl-md border border-[var(--bs-border)]"
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.content}</p>
            </div>
          </div>
        ))}
        {loading && messages[messages.length - 1]?.role === "user" && (
          <div className="flex justify-start">
            <Loader2 className="w-5 h-5 text-[var(--bs-text-muted)] animate-spin" />
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-[var(--bs-border)] p-3 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          placeholder="Ask about the book..."
          className="flex-1 rounded-xl border border-[var(--bs-border)] px-4 py-2.5 text-sm
                     outline-none focus:border-[var(--bs-accent)] transition-colors
                     bg-[var(--bs-bg)]"
          disabled={loading}
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          className="w-10 h-10 rounded-xl bg-[var(--bs-accent)] text-white
                     flex items-center justify-center
                     hover:bg-[var(--bs-accent-hover)] transition-colors
                     disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
