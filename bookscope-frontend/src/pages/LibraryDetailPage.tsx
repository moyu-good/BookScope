import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Library, Upload, Loader2 } from "lucide-react";
import { fetchLibraryAnalysis } from "../lib/api";
import BookSummaryCard from "../components/BookSummaryCard";
import VerdictCard from "../components/VerdictCard";
import ChapterTimeline from "../components/ChapterTimeline";
import CharacterGallery from "../components/CharacterGallery";
import EmotionRadar from "../components/EmotionRadar";
import ArcChart from "../components/ArcChart";

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
            <span
              className="text-lg text-[var(--accent)] shrink-0"
              style={{ fontFamily: "var(--font-display)" }}
            >
              书鉴
            </span>
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
            <button
              onClick={() => navigate("/library")}
              className="inline-flex items-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors duration-200"
            >
              <Library className="w-3.5 h-3.5" />
              书库
            </button>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-6xl mx-auto w-full px-4 py-6 space-y-6">
        {/* Archive notice */}
        <div className="flex items-start gap-3 bg-[var(--accent)]/5 border border-[var(--accent)]/20 rounded-xl px-4 py-3">
          <Upload className="w-4 h-4 text-[var(--accent)] shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-[var(--text)]">
              这是归档的分析结果。
            </p>
            <p className="text-xs text-[var(--text-secondary)] mt-0.5">
              如需角色对话、灵魂丰富和全文搜索，请
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

        {/* Charts */}
        {hasAnalysis && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {overview.emotion_scores && overview.emotion_scores.length > 0 && (
              <EmotionRadar emotionScores={overview.emotion_scores} />
            )}
            {overview.valence_series && overview.valence_series.length > 0 && (
              <ArcChart
                valenceSeries={overview.valence_series}
                arcPattern={overview.arc_pattern}
              />
            )}
          </div>
        )}

        {/* Back to library */}
        <div className="pt-4 flex justify-center">
          <button
            onClick={() => navigate("/library")}
            className="inline-flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors duration-200"
          >
            <ArrowLeft className="w-4 h-4" />
            返回书库
          </button>
        </div>
      </main>
    </div>
  );
}
