import { useState } from "react";
import { BookMarked, Loader2 } from "lucide-react";
import { fetchRecommendations, type BookRecommendation } from "../lib/api";

interface RecommendationsCardProps {
  sessionId: string;
  bookType: string;
  uiLang: string;
}

export default function RecommendationsCard({ sessionId, bookType, uiLang }: RecommendationsCardProps) {
  const [recs, setRecs] = useState<BookRecommendation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const generate = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchRecommendations(sessionId, bookType, uiLang);
      setRecs(data.recommendations ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate");
    } finally {
      setLoading(false);
    }
  };

  if (recs.length === 0 && !loading && !error) {
    return (
      <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6 text-center">
        <BookMarked className="mx-auto w-8 h-8 mb-3 text-[var(--bs-text-muted)] opacity-40" />
        <p className="text-sm text-[var(--bs-text-muted)] mb-3">
          Get similar book recommendations based on analysis
        </p>
        <button
          onClick={generate}
          className="px-4 py-2 rounded-xl bg-[var(--bs-accent)] text-white text-sm font-medium
                     hover:bg-[var(--bs-accent-hover)] transition-colors"
        >
          Find Similar Books
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6">
        <div className="flex items-center gap-2 text-sm text-[var(--bs-text-muted)]">
          <Loader2 className="w-4 h-4 animate-spin" />
          Finding similar books...
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

  return (
    <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6 space-y-4">
      <div className="flex items-center gap-2">
        <BookMarked className="w-4 h-4 text-emerald-500" strokeWidth={1.5} />
        <h3 className="text-sm font-semibold tracking-wide uppercase text-[var(--bs-text-muted)]">
          Similar Books
        </h3>
      </div>

      <div className="space-y-3">
        {recs.map((rec, i) => (
          <div
            key={i}
            className="flex items-start gap-3 bg-[var(--bs-bg)] rounded-xl p-3"
          >
            <span className="text-lg font-light text-[var(--bs-text-muted)] w-6 text-center flex-shrink-0">
              {i + 1}
            </span>
            <div className="min-w-0">
              <div className="font-medium text-sm text-[var(--bs-text)]">
                {rec.title}
              </div>
              <div className="text-xs text-[var(--bs-text-muted)]">
                {rec.author}
              </div>
              <p className="text-xs text-[var(--bs-text-muted)] mt-1 leading-relaxed">
                {rec.reason}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
