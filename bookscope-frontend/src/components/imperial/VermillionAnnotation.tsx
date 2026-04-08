import { useState, useRef, useEffect } from "react";
import { Send } from "lucide-react";
import { chatStream } from "../../lib/api";
import type { SSEEvent } from "../../lib/types";

/** A single annotation (question + response pair) */
export interface Annotation {
  id: string;
  question: string;
  answer: string;
  isStreaming: boolean;
}

interface VermillionAnnotationProps {
  sessionId: string;
  /** Existing annotations for this section */
  annotations: Annotation[];
  /** Update annotations state in parent */
  onUpdate: (annotations: Annotation[]) => void;
  /** Whether the input area is open */
  isComposing: boolean;
  /** Toggle composing state */
  onComposingChange: (v: boolean) => void;
  /** Optional context hint to prepend to the question */
  sectionContext?: string;
}

export default function VermillionAnnotation({
  sessionId,
  annotations,
  onUpdate,
  isComposing,
  onComposingChange,
  sectionContext,
}: VermillionAnnotationProps) {
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isComposing) {
      inputRef.current?.focus();
    }
  }, [isComposing]);

  const handleSend = () => {
    const q = input.trim();
    if (!q) return;

    const id = Date.now().toString(36);
    const fullQuestion = sectionContext
      ? `[关于：${sectionContext}] ${q}`
      : q;

    // Add annotation with empty answer
    const newAnnotation: Annotation = {
      id,
      question: q,
      answer: "",
      isStreaming: true,
    };
    const updated = [...annotations, newAnnotation];
    onUpdate(updated);
    setInput("");

    // Stream response
    const sse = chatStream(sessionId, fullQuestion, "zh");
    let accumulated = "";

    sse.onEvent((event: SSEEvent) => {
      if (event.type === "message" && typeof event.content === "string") {
        accumulated += event.content;
        onUpdate(
          updated.map((a) =>
            a.id === id ? { ...a, answer: accumulated } : a,
          ),
        );
      }
    });

    sse.onDone(() => {
      onUpdate(
        updated.map((a) =>
          a.id === id ? { ...a, isStreaming: false } : a,
        ),
      );
    });

    sse.onError(() => {
      onUpdate(
        updated.map((a) =>
          a.id === id
            ? { ...a, answer: accumulated || "回奏失败，请重试。", isStreaming: false }
            : a,
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
    if (e.key === "Escape") {
      onComposingChange(false);
    }
  };

  return (
    <div className="space-y-3">
      {/* Existing annotations */}
      {annotations.map((a) => (
        <div key={a.id} className="annotation-card">
          {/* Question */}
          <div className="flex items-start gap-2 mb-2">
            <span className="seal-stamp text-[9px] px-1 py-0 shrink-0" style={{ transform: "rotate(-3deg)" }}>
              朱批
            </span>
            <p className="text-sm vermillion-text leading-relaxed font-medium">
              {a.question}
            </p>
          </div>
          {/* Answer */}
          {a.answer && (
            <div className="ml-0 mt-2 pl-3 border-l-2 border-[var(--fold-line)]">
              <p className="text-xs text-[var(--parchment-text-secondary)] leading-loose whitespace-pre-line">
                <span className="text-[var(--parchment-text)] font-medium">回奏：</span>
                {a.answer}
                {a.isStreaming && (
                  <span className="inline-block w-1.5 h-3.5 bg-[var(--vermillion)] ml-0.5 animate-pulse align-text-bottom" />
                )}
              </p>
            </div>
          )}
          {/* Streaming placeholder */}
          {a.isStreaming && !a.answer && (
            <div className="ml-0 mt-2 pl-3 border-l-2 border-[var(--fold-line)]">
              <p className="text-xs text-[var(--parchment-text-secondary)] italic">
                臣正在回奏...
                <span className="inline-block w-1.5 h-3.5 bg-[var(--vermillion)] ml-0.5 animate-pulse align-text-bottom" />
              </p>
            </div>
          )}
        </div>
      ))}

      {/* Input area */}
      {isComposing && (
        <div className="annotation-card !border-l-[var(--vermillion)] !bg-transparent">
          <div className="flex gap-2">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="朱笔批示..."
              rows={2}
              className="flex-1 resize-none bg-[var(--vermillion-light)] border border-[var(--vermillion-border)] rounded px-3 py-2 text-sm text-[var(--vermillion)] placeholder:text-[var(--vermillion)]/40 focus:outline-none focus:border-[var(--vermillion)] leading-relaxed"
              style={{ fontFamily: "var(--font-body)" }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="self-end p-2.5 rounded bg-[var(--vermillion)] text-white disabled:opacity-30 hover:bg-[var(--vermillion)]/90 transition-colors cursor-pointer shrink-0"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </div>
          <p className="text-[10px] text-[var(--parchment-text-secondary)] mt-1.5">
            Enter 发送 · Esc 收起 · Shift+Enter 换行
          </p>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
