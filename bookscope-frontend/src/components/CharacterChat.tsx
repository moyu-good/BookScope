import { useState, useRef, useEffect } from "react";
import { MessageCircle, Send, Loader2 } from "lucide-react";
import { characterChat } from "../lib/api";
import type { SSEEvent } from "../lib/types";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface CharacterChatProps {
  sessionId: string;
  characterName: string;
}

export default function CharacterChat({
  sessionId,
  characterName,
}: CharacterChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setStreaming(true);

    // Append an empty assistant message that we'll stream into
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    const sse = characterChat(sessionId, characterName, text, "zh");
    sse.onEvent((event: SSEEvent) => {
      if (event.type === "message") {
        const chunk = (event as { content?: string }).content ?? "";
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              content: last.content + chunk,
            };
          }
          return updated;
        });
      } else if (event.type === "error") {
        const errMsg =
          (event as { message?: string }).message ?? "Chat failed";
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant" && !last.content) {
            updated[updated.length - 1] = {
              ...last,
              content: `Error: ${errMsg}`,
            };
          }
          return updated;
        });
        setStreaming(false);
      }
    });
    sse.onDone(() => setStreaming(false));
    sse.onError((err) => {
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === "assistant" && !last.content) {
          updated[updated.length - 1] = {
            ...last,
            content: `Error: ${err}`,
          };
        }
        return updated;
      });
      setStreaming(false);
    });
    sse.start();
  };

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-5 py-3 border-b border-[var(--border)]">
        <MessageCircle className="w-4 h-4 text-[var(--accent)]" />
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          与{characterName}对话
        </h2>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="h-80 overflow-y-auto p-4 space-y-3"
      >
        {messages.length === 0 && (
          <p className="text-center text-xs text-[var(--text-secondary)] py-8">
            向{characterName}提问关于故事、动机或经历的任何问题。
          </p>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-lg px-3.5 py-2.5 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-[var(--accent)] text-white"
                  : "bg-[var(--bg)] border border-[var(--border)] text-[var(--text)]"
              }`}
            >
              {msg.content || (
                <Loader2 className="w-4 h-4 animate-spin text-[var(--text-secondary)]" />
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Input */}
      <div className="border-t border-[var(--border)] p-3 flex items-center gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder={`向${characterName}提问...`}
          disabled={streaming}
          className="flex-1 bg-[var(--bg)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:border-[var(--accent)]/50 disabled:opacity-50 transition-colors duration-200"
        />
        <button
          onClick={handleSend}
          disabled={streaming || !input.trim()}
          className="shrink-0 p-2 rounded-lg bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:opacity-40 transition-all duration-200"
        >
          {streaming ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
        </button>
      </div>
    </div>
  );
}
