import { useState, useEffect, useRef } from "react";
import { Sparkles, RefreshCw } from "lucide-react";
import { narrativeSSE } from "../lib/api";

interface NarrativeCardProps {
  sessionId: string;
  bookType: string;
  uiLang: string;
}

export default function NarrativeCard({ sessionId, bookType, uiLang }: NarrativeCardProps) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const controllerRef = useRef<AbortController | null>(null);

  const generate = () => {
    setText("");
    setError("");
    setLoading(true);
    setDone(false);

    controllerRef.current?.abort();
    controllerRef.current = narrativeSSE(
      sessionId,
      bookType,
      uiLang,
      (token) => setText((prev) => prev + token),
      () => {
        setLoading(false);
        setDone(true);
      },
      (err) => {
        setLoading(false);
        setError(err.message);
      },
    );
  };

  useEffect(() => {
    generate();
    return () => controllerRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  return (
    <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-amber-500" strokeWidth={1.5} />
          <h3 className="text-sm font-semibold tracking-wide uppercase text-[var(--bs-text-muted)]">
            Book DNA
          </h3>
        </div>
        {done && (
          <button
            onClick={generate}
            className="text-[var(--bs-text-muted)] hover:text-[var(--bs-accent)] transition-colors"
            title="Regenerate"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {error ? (
        <p className="text-sm text-red-400">{error}</p>
      ) : (
        <p className="text-[var(--bs-text)] leading-relaxed text-[15px]">
          {text}
          {loading && (
            <span className="inline-block w-1.5 h-4 bg-[var(--bs-accent)] animate-pulse ml-0.5 align-text-bottom rounded-sm" />
          )}
        </p>
      )}

      {!text && !loading && !error && (
        <p className="text-sm text-[var(--bs-text-muted)] italic">
          Requires ANTHROPIC_API_KEY
        </p>
      )}
    </div>
  );
}
