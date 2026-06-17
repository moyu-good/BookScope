import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Library, Play, Loader2 } from "lucide-react";
import { fetchLibraryAnalysis, fetchActiveSessions } from "../lib/api";
import BookSummaryCard from "../components/BookSummaryCard";
import VerdictCard from "../components/VerdictCard";
import ChapterTimeline from "../components/ChapterTimeline";
import CharacterGallery from "../components/CharacterGallery";

export default function LibraryDetailPage() {
  const { filename } = useParams<{ filename: string }>();
  const navigate = useNavigate();
  const decodedFilename = filename ? decodeURIComponent(filename) : "";

  const {
    data: overview,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["library-analysis", decodedFilename],
    queryFn: () => fetchLibraryAnalysis(decodedFilename),
    enabled: !!decodedFilename,
  });

  // Check if there's an active session for this book (by title match)
  const { data: sessionsData } = useQuery({
    queryKey: ["active-sessions"],
    queryFn: fetchActiveSessions,
    staleTime: 10_000,
  });

  const matchingSession = sessionsData?.sessions.find(
    (s) => overview?.title && s.title === overview.title,
  );

  if (isLoading) {
    return (
      <div className="min-h-svh flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-[var(--accent)]" />
      </div>
    );
  }

  if (error || !overview) {
    return (
      <div className="min-h-svh flex flex-col items-center justify-center gap-4">
        <p className="text-sm text-red-400">
          {error instanceof Error ? error.message : "无法加载分析数据"}
        </p>
        <button
          onClick={() => navigate("/library")}
          className="text-sm text-[var(--accent)] hover:underline"
        >
          返回书库
        </button>
      </div>
    );
  }

  const hasKG =
    !!overview.overall_summary || (overview.characters_brief?.length ?? 0) > 0;
  const hasAnalysis = !!overview.arc_pattern || !!overview.reader_verdict;

  return (
    <div className="min-h-svh bg-[var(--bg)]">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-[var(--bg)]/80 backdrop-blur-md border-b border-[var(--border)]">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={() => navigate("/library")}
              className="text-lg text-[var(--accent)] shrink-0 hover:opacity-80 transition-opacity"
              style={{ fontFamily: "var(--font-display)" }}
            >
              书鉴
            </button>
            <span className="text-xs text-[var(--border)]">|</span>
            <h1
              className="text-base truncate text-[var(--text)]"
              style={{
                fontFamily: "var(--font-display)",
                letterSpacing: "0.08em",
              }}
            >
              {overview.title}
            </h1>
            <span className="shrink-0 px-2 py-0.5 text-[10px] font-medium rounded-full bg-[var(--surface-hover)] text-[var(--text-secondary)]">
              归档
            </span>
          </div>

          <div className="flex items-center gap-2">
            {matchingSession && (
              <button
                onClick={() =>
                  navigate(`/book/${matchingSession.session_id}`)
                }
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-all"
              >
                <Play className="w-3 h-3" />
                继续分析
              </button>
            )}
            <button
              onClick={() => navigate("/library")}
              className="inline-flex items-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors"
            >
              <Library className="w-3.5 h-3.5" />
              书库
            </button>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-6xl mx-auto w-full px-4 py-6 space-y-6">
        {/* Resume notice or archive notice */}
        {matchingSession ? (
          <button
            onClick={() =>
              navigate(`/book/${matchingSession.session_id}`)
            }
            className="w-full flex items-start gap-3 bg-[var(--accent)]/8 border border-[var(--accent)]/25 rounded-xl px-4 py-3 text-left hover:bg-[var(--accent)]/12 transition-all"
          >
            <Play className="w-4 h-4 text-[var(--accent)] shrink-0 mt-0.5" />
            <div>
              <p className="text-sm text-[var(--text)]">
                此书的活跃会话仍在运行
              </p>
              <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                点击继续分析，可使用聊天、搜索和角色深潜功能
              </p>
            </div>
          </button>
        ) : (
          <div className="flex items-start gap-3 bg-[var(--surface)] border border-[var(--border)] rounded-xl px-4 py-3">
            <Library className="w-4 h-4 text-[var(--text-secondary)] shrink-0 mt-0.5" />
            <div>
              <p className="text-sm text-[var(--text-secondary)]">
                归档的分析结果。如需聊天和角色深潜，请
                <button
                  onClick={() => navigate("/")}
                  className="text-[var(--accent)] hover:underline mx-0.5"
                >
                  重新上传原始文件
                </button>
                。
              </p>
            </div>
          </div>
        )}

        {/* Summary */}
        {hasKG && overview.overall_summary && (
          <BookSummaryCard
            summary={overview.overall_summary}
            themes={overview.themes ?? []}
          />
        )}

        {/* Verdict */}
        {hasAnalysis && overview.reader_verdict && (
          <VerdictCard verdict={overview.reader_verdict} />
        )}

        {/* Chapter timeline */}
        {hasKG &&
          overview.chapter_summaries &&
          overview.chapter_summaries.length > 0 && (
            <ChapterTimeline chapters={overview.chapter_summaries} />
          )}

        {/* Characters — readonly mode */}
        {hasKG &&
          overview.characters_brief &&
          overview.characters_brief.length > 0 && (
            <CharacterGallery
              characters={overview.characters_brief}
              readOnly
            />
          )}

        {/* Back to library */}
        <div className="pt-4 flex justify-center">
          <button
            onClick={() => navigate("/library")}
            className="inline-flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回书库
          </button>
        </div>
      </main>
    </div>
  );
}
