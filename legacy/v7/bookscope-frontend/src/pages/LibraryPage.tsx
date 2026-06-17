import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Library,
  Trash2,
  Loader2,
  BookOpen,
  Plus,
  Tag,
  Clock,
  ChevronRight,
} from "lucide-react";
import { fetchLibrary, deleteLibraryItem } from "../lib/api";

interface LibraryItem {
  filename: string;
  session_id: string;
  title: string;
  arc_pattern: string;
  total_chunks: number;
  total_words: number;
  language: string;
  analyzed_at: string;
  tags: string[];
}

interface LibraryResponse {
  items: LibraryItem[];
  total: number;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

export default function LibraryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [deleting, setDeleting] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery<LibraryResponse>({
    queryKey: ["library"],
    queryFn: () => fetchLibrary() as Promise<LibraryResponse>,
  });

  const handleDelete = async (filename: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (deleting) return;
    setDeleting(filename);
    try {
      await deleteLibraryItem(filename);
      queryClient.invalidateQueries({ queryKey: ["library"] });
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="min-h-svh bg-[var(--bg)]">
      <header className="sticky top-0 z-40 bg-[var(--bg)]/80 backdrop-blur-md border-b border-[var(--border)]">
        <div className="max-w-4xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Library className="w-5 h-5 text-[var(--accent)]" />
            <h1 className="text-xl text-[var(--accent)]">书库</h1>
          </div>
          <button
            onClick={() => navigate("/")}
            className="inline-flex items-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors duration-200"
          >
            <Plus className="w-3.5 h-3.5" />
            新建分析
          </button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-8">
        {isLoading && (
          <div className="flex items-center justify-center h-40">
            <Loader2 className="w-6 h-6 animate-spin text-[var(--accent)]" />
          </div>
        )}

        {error && (
          <p className="text-center text-sm text-red-400">
            {error instanceof Error ? error.message : "加载书库失败"}
          </p>
        )}

        {data && data.items.length === 0 && (
          <div className="text-center py-16">
            <Library className="w-10 h-10 text-[var(--border)] mx-auto mb-3" />
            <p className="text-sm text-[var(--text-secondary)] mb-4">
              暂无已保存的分析。
            </p>
            <button
              onClick={() => navigate("/")}
              className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm hover:bg-[var(--accent-hover)] transition-colors duration-200"
            >
              分析一本书
            </button>
          </div>
        )}

        {data && data.items.length > 0 && (
          <div className="space-y-3">
            {data.items.map((item) => (
              <div
                key={item.session_id || item.filename}
                onClick={() =>
                  navigate(
                    item.session_id
                      ? `/book/${item.session_id}`
                      : `/library/${encodeURIComponent(item.filename)}`,
                  )
                }
                className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-4 hover:border-[var(--accent)]/30 hover:bg-[var(--surface-hover)] transition-all duration-200 cursor-pointer group"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <BookOpen className="w-4 h-4 text-[var(--accent)] shrink-0" />
                      <h3 className="text-sm font-medium text-[var(--text)] truncate group-hover:text-[var(--accent)] transition-colors duration-200">
                        {item.title}
                      </h3>
                      <ChevronRight className="w-3.5 h-3.5 text-[var(--text-secondary)] opacity-0 group-hover:opacity-100 transition-opacity duration-200 shrink-0" />
                    </div>
                    <div className="flex items-center gap-3 text-[10px] text-[var(--text-secondary)] mb-2">
                      <span>{item.total_chunks} 段</span>
                      <span>{item.total_words.toLocaleString()} 字</span>
                      <span className="uppercase">{item.language}</span>
                      {item.arc_pattern && (
                        <span className="px-1.5 py-0.5 rounded bg-[var(--surface-hover)]">
                          {item.arc_pattern}
                        </span>
                      )}
                      {item.analyzed_at && (
                        <span className="inline-flex items-center gap-1">
                          <Clock className="w-2.5 h-2.5" />
                          {formatDate(item.analyzed_at)}
                        </span>
                      )}
                    </div>
                    {item.tags.length > 0 && (
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <Tag className="w-3 h-3 text-[var(--text-secondary)]" />
                        {item.tags.map((tag) => (
                          <span
                            key={tag}
                            className="px-1.5 py-0.5 text-[10px] rounded bg-[var(--accent)]/10 text-[var(--accent)]"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={(e) => handleDelete(item.filename, e)}
                    disabled={deleting === item.filename}
                    className="shrink-0 p-2 rounded-lg text-[var(--text-secondary)] hover:text-red-400 hover:bg-red-500/10 transition-all duration-200"
                    title="删除"
                  >
                    {deleting === item.filename ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Trash2 className="w-4 h-4" />
                    )}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
