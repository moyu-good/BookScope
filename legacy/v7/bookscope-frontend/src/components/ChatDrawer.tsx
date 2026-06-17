import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  MessageCircle,
  X,
  Send,
  Loader2,
  User,
  BookOpen,
  ArrowRight,
} from "lucide-react";
import clsx from "clsx";
import { chatStream, characterChat } from "../lib/api";
import type { SSEEvent, CharacterBrief } from "../lib/types";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  /** Characters mentioned in this response — for suggestion chips */
  mentionedCharacters?: string[];
}

type ChatMode = "book" | "character";

interface ChatDrawerProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  characters: CharacterBrief[];
}

/* ------------------------------------------------------------------ */
/*  ChatDrawer                                                         */
/* ------------------------------------------------------------------ */

export default function ChatDrawer({
  open,
  onClose,
  sessionId,
  characters,
}: ChatDrawerProps) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<ChatMode>("book");
  const [activeCharacter, setActiveCharacter] = useState<string | null>(null);

  const [bookMessages, setBookMessages] = useState<ChatMessage[]>([]);
  const [charMessages, setCharMessages] = useState<ChatMessage[]>([]);

  const messages = mode === "book" ? bookMessages : charMessages;
  const setMessages = mode === "book" ? setBookMessages : setCharMessages;

  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Character names for mention detection
  const charNames = characters.map((c) => c.name);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const detectMentionedCharacters = useCallback(
    (text: string): string[] => {
      return charNames.filter((name) => text.includes(name));
    },
    [charNames],
  );

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setStreaming(true);

    // Placeholder assistant message
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    const sse =
      mode === "book"
        ? chatStream(sessionId, text, "zh")
        : characterChat(sessionId, activeCharacter!, text, "zh");

    let fullContent = "";

    sse.onEvent((event: SSEEvent) => {
      if (event.type === "message") {
        const chunk = (event as { content?: string }).content ?? "";
        fullContent += chunk;
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
            updated[updated.length - 1] = { ...last, content: `Error: ${errMsg}` };
          }
          return updated;
        });
        setStreaming(false);
      }
    });

    sse.onDone(() => {
      // Detect character mentions for suggestion chips
      const mentioned = detectMentionedCharacters(fullContent);
      if (mentioned.length > 0) {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              mentionedCharacters: mentioned,
            };
          }
          return updated;
        });
      }
      setStreaming(false);
    });

    sse.onError((err) => {
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === "assistant" && !last.content) {
          updated[updated.length - 1] = { ...last, content: `Error: ${err}` };
        }
        return updated;
      });
      setStreaming(false);
    });

    sse.start();
  }, [
    input,
    streaming,
    mode,
    sessionId,
    activeCharacter,
    setMessages,
    detectMentionedCharacters,
  ]);

  const switchToCharacter = useCallback((name: string) => {
    setActiveCharacter(name);
    setMode("character");
    setCharMessages([]);
  }, []);

  const switchToBook = useCallback(() => {
    setMode("book");
    setActiveCharacter(null);
  }, []);

  const goToCharacterPage = useCallback(
    (name: string) => {
      onClose();
      navigate(`/book/${sessionId}/character/${encodeURIComponent(name)}`);
    },
    [navigate, sessionId, onClose],
  );

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm transition-opacity duration-300"
          onClick={onClose}
        />
      )}

      {/* Drawer */}
      <div
        className={clsx(
          "fixed top-0 right-0 z-50 h-full w-full sm:w-[420px] bg-[var(--bg)] border-l border-[var(--border)] flex flex-col transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 h-14 border-b border-[var(--border)] shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <MessageCircle className="w-4 h-4 text-[var(--accent)] shrink-0" />
            {mode === "book" ? (
              <span
                className="text-lg text-[var(--accent)] truncate"
                style={{ fontFamily: "var(--font-display)" }}
              >
                问书
              </span>
            ) : (
              <div className="flex items-center gap-2 min-w-0">
                <button
                  onClick={switchToBook}
                  className="text-xs text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors shrink-0"
                >
                  问书
                </button>
                <span className="text-[var(--border)]">/</span>
                <span
                  className="text-lg text-[var(--accent)] truncate"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  与{activeCharacter}对话
                </span>
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Character quick-switch strip */}
        {characters.length > 0 && (
          <div className="flex items-center gap-1.5 px-4 py-2 border-b border-[var(--border)] overflow-x-auto shrink-0">
            <button
              onClick={switchToBook}
              className={clsx(
                "shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-medium transition-all",
                mode === "book"
                  ? "bg-[var(--accent)]/15 text-[var(--accent)]"
                  : "text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)]",
              )}
            >
              <BookOpen className="w-3 h-3" />
              整本书
            </button>
            {characters.slice(0, 8).map((ch) => (
              <button
                key={ch.name}
                onClick={() =>
                  ch.has_soul
                    ? switchToCharacter(ch.name)
                    : goToCharacterPage(ch.name)
                }
                className={clsx(
                  "shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-medium transition-all",
                  mode === "character" && activeCharacter === ch.name
                    ? "bg-[var(--accent)]/15 text-[var(--accent)]"
                    : "text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)]",
                  !ch.has_soul && "opacity-50",
                )}
                title={ch.has_soul ? `与${ch.name}对话` : `${ch.name}尚未丰富灵魂`}
              >
                <User className="w-3 h-3" />
                {ch.name}
              </button>
            ))}
          </div>
        )}

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center px-4">
              <MessageCircle className="w-8 h-8 text-[var(--border)] mb-3" />
              {mode === "book" ? (
                <>
                  <p className="text-sm text-[var(--text-secondary)] mb-1">
                    关于本书的任何问题都可以问
                  </p>
                  <p className="text-xs text-[var(--text-secondary)]/60">
                    回答基于全文 RAG 检索
                  </p>
                </>
              ) : (
                <>
                  <p className="text-sm text-[var(--text-secondary)] mb-1">
                    以{activeCharacter}的视角回答你的问题
                  </p>
                  <p className="text-xs text-[var(--text-secondary)]/60">
                    基于文本中的性格、动机和经历
                  </p>
                </>
              )}
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i}>
              <div
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={clsx(
                    "max-w-[85%] rounded-lg px-3.5 py-2.5 text-sm leading-relaxed",
                    msg.role === "user"
                      ? "bg-[var(--accent)] text-white"
                      : "bg-[var(--surface)] border border-[var(--border)] text-[var(--text)]",
                  )}
                >
                  {msg.content || (
                    <Loader2 className="w-4 h-4 animate-spin text-[var(--text-secondary)]" />
                  )}
                </div>
              </div>

              {/* Character suggestion chips */}
              {msg.role === "assistant" &&
                msg.mentionedCharacters &&
                msg.mentionedCharacters.length > 0 &&
                mode === "book" && (
                  <div className="flex flex-wrap gap-1.5 mt-2 ml-1">
                    {msg.mentionedCharacters.map((name) => {
                      const ch = characters.find((c) => c.name === name);
                      return (
                        <button
                          key={name}
                          onClick={() =>
                            ch?.has_soul
                              ? switchToCharacter(name)
                              : goToCharacterPage(name)
                          }
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-medium bg-[var(--accent)]/8 text-[var(--accent)] border border-[var(--accent)]/20 hover:bg-[var(--accent)]/15 transition-all"
                        >
                          <User className="w-2.5 h-2.5" />
                          {name}会怎么想？
                          <ArrowRight className="w-2.5 h-2.5" />
                        </button>
                      );
                    })}
                  </div>
                )}
            </div>
          ))}
        </div>

        {/* Input */}
        <div className="border-t border-[var(--border)] p-3 flex items-center gap-2 shrink-0">
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
            placeholder={
              mode === "book"
                ? "问关于这本书的问题..."
                : `问${activeCharacter}...`
            }
            disabled={streaming}
            className="flex-1 bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:border-[var(--accent)]/50 disabled:opacity-50 transition-colors"
          />
          <button
            onClick={handleSend}
            disabled={streaming || !input.trim()}
            className="shrink-0 p-2 rounded-lg bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:opacity-40 transition-all"
          >
            {streaming ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>
    </>
  );
}
