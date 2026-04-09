import { useState, useRef, useEffect } from "react";
import { Send, ScrollText, X } from "lucide-react";
import clsx from "clsx";
import type { CharacterBrief, SSEEvent } from "../../lib/types";
import { chatStream, characterChat } from "../../lib/api";

/* ── Summon Strip (传召) ─────────────────────────── */

interface SummonStripProps {
  characters: CharacterBrief[];
  activeCharacter: string | null;
  onSelect: (name: string | null) => void;
}

export function SummonStrip({
  characters,
  activeCharacter,
  onSelect,
}: SummonStripProps) {
  if (characters.length === 0) return null;

  return (
    <div className="flex items-center gap-2 px-4 py-2 overflow-x-auto scrollbar-none">
      <span className="text-[10px] text-[var(--text-secondary)] shrink-0 tracking-wider">
        传召
      </span>
      {characters.slice(0, 8).map((ch) => {
        const active = activeCharacter === ch.name;
        return (
          <button
            key={ch.name}
            onClick={() => onSelect(active ? null : ch.name)}
            className={clsx(
              "shrink-0 px-2.5 py-1 text-[11px] rounded border transition-all cursor-pointer",
              "tracking-wide",
              active
                ? "border-[var(--vermillion)] text-[var(--vermillion)] bg-[var(--vermillion)]/10 seal-stamp !transform-none !shadow-none !text-[11px] !font-normal !p-0 !px-2.5 !py-1 !rounded !tracking-wide"
                : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--vermillion)]/50 hover:text-[var(--vermillion)]/70",
            )}
            style={active ? {
              transform: "rotate(-2deg)",
              borderWidth: "1.5px",
            } : undefined}
          >
            {ch.name}
          </button>
        );
      })}
    </div>
  );
}

/* ── Imperial Brush Input (御笔) ─────────────────── */

interface ImperialBrushProps {
  sessionId: string;
  characters: CharacterBrief[];
}

interface BrushMessage {
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  characterName?: string;
}

const INTRO_SEEN_KEY = "bookscope-brush-intro-seen";

export default function ImperialBrush({
  sessionId,
  characters,
}: ImperialBrushProps) {
  const [input, setInput] = useState("");
  const [activeCharacter, setActiveCharacter] = useState<string | null>(null);
  const [messages, setMessages] = useState<BrushMessage[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [showIntro, setShowIntro] = useState(
    () => !localStorage.getItem(INTRO_SEEN_KEY),
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const dismissIntro = () => {
    setShowIntro(false);
    localStorage.setItem(INTRO_SEEN_KEY, "1");
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = () => {
    const q = input.trim();
    if (!q) return;

    const userMsg: BrushMessage = { role: "user", content: q, characterName: activeCharacter ?? undefined };
    const assistantMsg: BrushMessage = {
      role: "assistant",
      content: "",
      isStreaming: true,
      characterName: activeCharacter ?? undefined,
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setExpanded(true);

    const sse = activeCharacter
      ? characterChat(sessionId, activeCharacter, q, "zh")
      : chatStream(sessionId, q, "zh");

    let accumulated = "";

    sse.onEvent((event: SSEEvent) => {
      if (event.type === "message" && typeof event.content === "string") {
        accumulated += event.content;
        setMessages((prev) =>
          prev.map((m, i) =>
            i === prev.length - 1 ? { ...m, content: accumulated } : m,
          ),
        );
      }
    });

    sse.onDone(() => {
      setMessages((prev) =>
        prev.map((m, i) =>
          i === prev.length - 1 ? { ...m, isStreaming: false } : m,
        ),
      );
    });

    sse.onError(() => {
      setMessages((prev) =>
        prev.map((m, i) =>
          i === prev.length - 1
            ? { ...m, content: accumulated || "回奏失败。", isStreaming: false }
            : m,
        ),
      );
    });

    sse.start();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40">
      {/* Expanded messages area */}
      {expanded && messages.length > 0 && (
        <div className="bg-[var(--surface)]/95 backdrop-blur-sm border-t border-[var(--border)] max-h-[40vh] overflow-y-auto">
          <div className="max-w-3xl mx-auto px-4 py-3 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-[var(--text-secondary)]">
                {activeCharacter ? `与${activeCharacter}对话` : "御笔问答"}
              </span>
              <button
                onClick={() => setExpanded(false)}
                className="text-[var(--text-secondary)] hover:text-[var(--text)] cursor-pointer"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            {messages.map((msg, i) => (
              <div
                key={i}
                className={clsx(
                  "text-sm leading-relaxed",
                  msg.role === "user"
                    ? "text-[var(--accent)] font-medium"
                    : "text-[var(--text)] pl-3 border-l-2 border-[var(--border)]",
                )}
              >
                {msg.role === "user" && (
                  <span className="text-[10px] text-[var(--text-secondary)] mr-2">
                    {msg.characterName ? `问${msg.characterName}：` : "御笔："}
                  </span>
                )}
                {msg.role === "assistant" && (
                  <span className="text-[10px] text-[var(--text-secondary)] mr-1">
                    {msg.characterName ? `${msg.characterName}回：` : "回奏："}
                  </span>
                )}
                <span className="whitespace-pre-line">{msg.content}</span>
                {msg.isStreaming && (
                  <span className="inline-block w-1.5 h-3 bg-[var(--accent)] ml-0.5 animate-pulse align-text-bottom" />
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      {/* Onboarding guide */}
      {showIntro && (
        <div className="bg-[var(--surface)] border-t border-[var(--accent)]/20">
          <div className="max-w-3xl mx-auto px-4 py-2.5 flex items-center justify-between">
            <span className="text-xs text-[var(--accent)] tracking-wide" style={{ fontFamily: "var(--font-body)" }}>
              在此与书中人物对话，或对任何章节留下朱批
            </span>
            <button
              onClick={dismissIntro}
              className="text-[var(--text-secondary)] hover:text-[var(--text)] text-xs cursor-pointer ml-3 shrink-0"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Summon strip + input */}
      <div className="bg-[var(--bg)] border-t border-[var(--border)]">
        <div className="max-w-3xl mx-auto">
          {/* Character chips */}
          <SummonStrip
            characters={characters}
            activeCharacter={activeCharacter}
            onSelect={setActiveCharacter}
          />

          {/* Input */}
          <div className="flex items-center gap-3 px-4 pb-4 pt-1">
            <ScrollText className="w-4 h-4 text-[var(--accent)] shrink-0 opacity-60" />
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={() => messages.length > 0 && setExpanded(true)}
              placeholder={
                activeCharacter
                  ? `传召${activeCharacter}回话...`
                  : "传召书中人物对话，或输入朱批..."
              }
              className={clsx(
                "flex-1 bg-[var(--surface)] border rounded-lg px-4 py-2.5 text-sm",
                "text-[var(--text)] placeholder:text-[var(--text-secondary)]/50",
                "focus:outline-none transition-colors",
                activeCharacter
                  ? "border-[var(--vermillion)]/30 focus:border-[var(--vermillion)]"
                  : "border-[var(--border)] focus:border-[var(--accent)]",
              )}
              style={{ fontFamily: "var(--font-body)" }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className={clsx(
                "p-2.5 rounded-lg transition-colors cursor-pointer shrink-0",
                activeCharacter
                  ? "bg-[var(--vermillion)] text-white disabled:opacity-30"
                  : "bg-[var(--accent)] text-[var(--bg)] disabled:opacity-30",
              )}
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
