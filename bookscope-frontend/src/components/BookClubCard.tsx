import { useState } from "react";
import { MessagesSquare, Loader2 } from "lucide-react";
import { fetchBookClubPack, type BookClubPack } from "../lib/api";

interface BookClubCardProps {
  sessionId: string;
  bookType: string;
  uiLang: string;
}

const DIFFICULTY_COLORS: Record<string, string> = {
  Easy: "bg-green-500/10 text-green-400",
  Medium: "bg-amber-500/10 text-amber-400",
  Challenging: "bg-red-500/10 text-red-400",
};

export default function BookClubCard({ sessionId, bookType, uiLang }: BookClubCardProps) {
  const [pack, setPack] = useState<BookClubPack | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const generate = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchBookClubPack(sessionId, bookType, uiLang);
      setPack(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate");
    } finally {
      setLoading(false);
    }
  };

  if (!pack && !loading && !error) {
    return (
      <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6 text-center">
        <MessagesSquare className="mx-auto w-8 h-8 mb-3 text-[var(--bs-text-muted)] opacity-40" />
        <p className="text-sm text-[var(--bs-text-muted)] mb-3">
          Generate discussion questions and reading difficulty assessment
        </p>
        <button
          onClick={generate}
          className="px-4 py-2 rounded-xl bg-[var(--bs-accent)] text-white text-sm font-medium
                     hover:bg-[var(--bs-accent-hover)] transition-colors"
        >
          Generate Book Club Pack
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6">
        <div className="flex items-center gap-2 text-sm text-[var(--bs-text-muted)]">
          <Loader2 className="w-4 h-4 animate-spin" />
          Generating book club pack...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6">
        <p className="text-sm text-red-400 mb-2">{error}</p>
        <button onClick={generate} className="text-xs text-[var(--bs-accent)] hover:underline">
          Retry
        </button>
      </div>
    );
  }

  if (!pack) return null;

  return (
    <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MessagesSquare className="w-4 h-4 text-teal-500" strokeWidth={1.5} />
          <h3 className="text-sm font-semibold tracking-wide uppercase text-[var(--bs-text-muted)]">
            Book Club Pack
          </h3>
        </div>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${DIFFICULTY_COLORS[pack.difficulty] ?? ""}`}>
          {pack.difficulty}
        </span>
      </div>

      {pack.arc_summary && (
        <p className="text-sm text-[var(--bs-text-muted)] leading-relaxed">
          {pack.arc_summary}
        </p>
      )}

      <div className="space-y-2">
        {pack.questions.map((q, i) => (
          <div key={i} className="flex gap-3 items-start">
            <span className="text-xs font-bold text-[var(--bs-accent)] mt-0.5 w-5 flex-shrink-0">
              Q{i + 1}
            </span>
            <p className="text-sm text-[var(--bs-text)] leading-relaxed">{q}</p>
          </div>
        ))}
      </div>

      {pack.target_audience && (
        <p className="text-xs text-[var(--bs-text-muted)]">
          Target audience: {pack.target_audience}
        </p>
      )}
    </div>
  );
}
