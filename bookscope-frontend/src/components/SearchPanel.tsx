import { useState } from "react";
import { Search, Loader2 } from "lucide-react";
import { searchChunks } from "../lib/api";

interface SearchResult {
  chunk_index: number;
  text_preview: string;
  match_count: number;
}

interface SearchResponse {
  total_matches: number;
  results: SearchResult[];
}

interface SearchPanelProps {
  sessionId: string;
}

export default function SearchPanel({ sessionId }: SearchPanelProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [totalMatches, setTotalMatches] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async () => {
    const q = query.trim();
    if (!q) return;

    setLoading(true);
    setError(null);
    try {
      const data = (await searchChunks(sessionId, q)) as SearchResponse;
      setResults(data.results);
      setTotalMatches(data.total_matches);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
      setResults(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl overflow-hidden">
      <div className="flex items-center gap-2 px-5 py-3 border-b border-[var(--border)]">
        <Search className="w-4 h-4 text-[var(--accent)]" />
        <h2 className="text-xl text-[var(--accent)]">
          全文搜索
        </h2>
      </div>

      {/* Search input */}
      <div className="p-4 border-b border-[var(--border)] flex items-center gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSearch();
          }}
          placeholder="搜索书中关键词..."
          className="flex-1 bg-[var(--bg)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:border-[var(--accent)]/50 transition-colors duration-200"
        />
        <button
          onClick={handleSearch}
          disabled={loading || !query.trim()}
          className="shrink-0 px-3 py-2 rounded-lg bg-[var(--accent)] text-white text-sm hover:bg-[var(--accent-hover)] disabled:opacity-40 transition-all duration-200"
        >
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            "搜索"
          )}
        </button>
      </div>

      {/* Results */}
      <div className="max-h-96 overflow-y-auto">
        {error && (
          <p className="p-4 text-xs text-red-400">{error}</p>
        )}

        {results !== null && results.length === 0 && (
          <p className="p-4 text-center text-xs text-[var(--text-secondary)]">
            未找到匹配结果。
          </p>
        )}

        {results !== null && results.length > 0 && (
          <>
            <div className="px-4 py-2 text-xs text-[var(--text-secondary)] border-b border-[var(--border)]">
              找到 {totalMatches} 条匹配
            </div>
            <div className="divide-y divide-[var(--border)]">
              {results.map((r) => (
                <div
                  key={r.chunk_index}
                  className="px-4 py-3 hover:bg-[var(--surface-hover)] transition-colors duration-150"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-[var(--accent)]/10 text-[var(--accent)]">
                      段落 {r.chunk_index + 1}
                    </span>
                    <span className="text-[10px] text-[var(--text-secondary)]">
                      {r.match_count} 处匹配
                    </span>
                  </div>
                  <p className="text-xs text-[var(--text)] leading-relaxed">
                    {r.text_preview}
                  </p>
                </div>
              ))}
            </div>
          </>
        )}

        {results === null && !error && (
          <p className="p-4 text-center text-xs text-[var(--text-secondary)]">
            输入关键词搜索全书文本。
          </p>
        )}
      </div>
    </div>
  );
}
