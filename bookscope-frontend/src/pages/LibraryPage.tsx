import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Library,
  Trash2,
  Loader2,
  BookOpen,
  ArrowLeft,
  Tag,
} from "lucide-react";
import { fetchLibrary, deleteLibraryItem } from "../lib/api";

interface LibraryItem {
  filename: string;
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

export default function LibraryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [deleting, setDeleting] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery<LibraryResponse>({
    queryKey: ["library"],
    queryFn: () => fetchLibrary() as Promise<LibraryResponse>,
  });

  const handleDelete = async (filename: string) => {
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
            <h1 className="text-sm font-semibold">书库</h1>
          </div>
          <button
            onClick={() => navigate("/")}
            className="inline-flex items-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors duration-200"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
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
                key={item.filename}
                className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-4 hover:border-[var(--accent)]/30 transition-all duration-200"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <BookOpen className="w-4 h-4 text-[var(--accent)] shrink-0" />
                      <h3 className="text-sm font-medium text-[var(--text)] truncate">
                        {item.title}
                      </h3>
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
                    onClick={() => handleDelete(item.filename)}
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
