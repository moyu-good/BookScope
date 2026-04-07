import { useState, useCallback } from "react";
import { Search, FileText } from "lucide-react";
import { searchChunks, type SearchResult } from "../lib/api";

interface SearchPanelProps {
  sessionId: string;
}

export default function SearchPanel({ sessionId }: SearchPanelProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);

  const doSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    try {
      const res = await searchChunks(sessionId, q);
      setResults(res.results);
      setTotal(res.total_matches);
      setSearched(true);
    } catch {
      setResults([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [sessionId, query]);

  return (
    <div className="space-y-4">
      {/* Search bar */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--bs-text-muted)]" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doSearch()}
            placeholder="Search in book text..."
            className="w-full rounded-xl border border-[var(--bs-border)] pl-10 pr-4 py-2.5 text-sm
                       outline-none focus:border-[var(--bs-accent)] transition-colors
                       bg-[var(--bs-surface)]"
          />
        </div>
        <button
          onClick={doSearch}
          disabled={loading || !query.trim()}
          className="px-4 py-2.5 rounded-xl bg-[var(--bs-accent)] text-white text-sm font-medium
                     hover:bg-[var(--bs-accent-hover)] transition-colors
                     disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Search
        </button>
      </div>

      {/* Results */}
      {searched && (
        <p className="text-sm text-[var(--bs-text-muted)]">
          {total} match{total !== 1 ? "es" : ""} found
        </p>
      )}
      <div className="space-y-2">
        {results.map((r) => (
          <div
            key={r.chunk_index}
            className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-xl p-4"
          >
            <div className="flex items-center gap-2 mb-2">
              <FileText className="w-4 h-4 text-[var(--bs-text-muted)]" />
              <span className="text-xs font-medium text-[var(--bs-text-muted)]">
                Chunk {r.chunk_index + 1}
              </span>
              <span className="text-xs text-[var(--bs-text-muted)]">
                ({r.match_count} match{r.match_count !== 1 ? "es" : ""})
              </span>
            </div>
            <p className="text-sm text-[var(--bs-text)] leading-relaxed">
              {r.text_preview}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
