import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Library, Trash2, Loader2, Clock, Globe } from "lucide-react";
import { fetchLibrary, deleteFromLibrary, type LibraryItem } from "../lib/api";

export default function LibraryPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const data = await fetchLibrary();
      setItems(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load library");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleDelete = async (filename: string) => {
    try {
      await deleteFromLibrary(filename);
      setItems((prev) => prev.filter((i) => i.filename !== filename));
    } catch {
      // silent
    }
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 bg-[var(--bs-bg)]/95 backdrop-blur border-b border-[var(--bs-border)]">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Library className="w-5 h-5 text-[var(--bs-accent)]" strokeWidth={1.5} />
            <h1 className="text-lg font-medium">Library</h1>
          </div>
          <button
            onClick={() => navigate("/")}
            className="text-sm text-[var(--bs-text-muted)] hover:text-[var(--bs-accent)] transition-colors"
          >
            New analysis
          </button>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-6 h-6 text-[var(--bs-accent)] animate-spin" />
          </div>
        ) : error ? (
          <p className="text-center text-red-400 py-10">{error}</p>
        ) : items.length === 0 ? (
          <div className="text-center py-20">
            <BookOpen className="mx-auto w-12 h-12 mb-4 text-[var(--bs-text-muted)] opacity-30" />
            <p className="text-[var(--bs-text-muted)]">No saved analyses yet</p>
            <p className="text-sm text-[var(--bs-text-muted)] mt-1">
              Analyze a book and save it to build your library
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map((item) => (
              <div
                key={item.filename}
                onClick={() => navigate(`/book/lib:${item.filename}`)}
                className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-5
                           hover:border-[var(--bs-accent)]/30 transition-colors group cursor-pointer"
              >
                <div className="flex items-start justify-between mb-3">
                  <h3 className="font-medium text-[var(--bs-text)] line-clamp-2 pr-2">
                    {item.title}
                  </h3>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDelete(item.filename); }}
                    className="text-[var(--bs-text-muted)] hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Delete"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                <div className="space-y-1.5 text-xs text-[var(--bs-text-muted)]">
                  <div className="flex items-center gap-1.5">
                    <Globe className="w-3 h-3" />
                    {item.language.toUpperCase()} · {item.total_words.toLocaleString()} words · {item.total_chunks} chunks
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Clock className="w-3 h-3" />
                    {new Date(item.analyzed_at).toLocaleDateString()}
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  <span className="text-xs px-2 py-0.5 rounded-full bg-[var(--bs-accent)]/10 text-[var(--bs-accent)]">
                    {item.arc_pattern}
                  </span>
                  {item.tags.map((tag) => (
                    <span
                      key={tag}
                      className="text-xs px-2 py-0.5 rounded-full bg-[var(--bs-border)] text-[var(--bs-text-muted)]"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
