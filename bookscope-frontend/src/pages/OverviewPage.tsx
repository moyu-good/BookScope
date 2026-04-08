import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Search, ChevronDown, ChevronRight } from "lucide-react";
import { fetchOverview } from "../lib/api";
import { useExtraction } from "./BookLayout";
import ExtractionProgress from "../components/ExtractionProgress";
import BookOutline from "../components/BookOutline";
import BookSummaryCard from "../components/BookSummaryCard";
import VerdictCard from "../components/VerdictCard";
import ChapterDeepView from "../components/ChapterDeepView";
import ChapterTimeline from "../components/ChapterTimeline";
import CharacterGallery from "../components/CharacterGallery";
import EmotionRadar from "../components/EmotionRadar";
import NarrativeRhythmChart from "../components/NarrativeRhythmChart";
import ArcChart from "../components/ArcChart";
import SearchPanel from "../components/SearchPanel";

/* ------------------------------------------------------------------ */
/*  Fade-in wrapper for progressive reveal                            */
/* ------------------------------------------------------------------ */

function RevealSection({
  show,
  delay = 0,
  children,
}: {
  show: boolean;
  delay?: number;
  children: React.ReactNode;
}) {
  if (!show) return null;
  return (
    <div
      className="animate-[fadeSlideIn_0.5s_ease-out_both]"
      style={{ animationDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  OverviewPage                                                       */
/* ------------------------------------------------------------------ */

export default function OverviewPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { isExtracting, sseEvents } = useExtraction();
  const [searchOpen, setSearchOpen] = useState(false);

  const { data: overview } = useQuery({
    queryKey: ["overview", sessionId],
    queryFn: () => fetchOverview(sessionId!),
    enabled: !!sessionId,
    refetchInterval: isExtracting ? 2000 : false,
  });

  const hasKG =
    !!overview?.book_outline || !!overview?.overall_summary || (overview?.characters_brief?.length ?? 0) > 0;
  const hasAnalysis = !!overview?.arc_pattern || !!overview?.reader_verdict;

  return (
    <div className="space-y-6">
      {/* Extraction progress */}
      {isExtracting && <ExtractionProgress events={sseEvents} />}

      {/* Book outline — deep analysis first, fallback to legacy summary */}
      <RevealSection show={hasKG && !!(overview?.book_outline || overview?.overall_summary)}>
        {overview?.book_outline ? (
          <BookOutline
            outline={overview.book_outline}
            themes={overview.theme_analyses}
            legacySummary={overview.overall_summary}
            legacyThemes={overview.themes}
          />
        ) : (
          <BookSummaryCard
            summary={overview?.overall_summary ?? ""}
            themes={overview?.themes ?? []}
          />
        )}
      </RevealSection>

      {/* Reader verdict */}
      <RevealSection show={hasAnalysis && !!overview?.reader_verdict} delay={100}>
        <VerdictCard verdict={overview!.reader_verdict!} />
      </RevealSection>

      {/* Chapter deep analysis — fallback to timeline if deep analysis not available */}
      <RevealSection
        show={hasKG && ((overview?.chapter_analyses?.length ?? 0) > 0 || (overview?.chapter_summaries?.length ?? 0) > 0)}
        delay={150}
      >
        {(overview?.chapter_analyses?.length ?? 0) > 0 ? (
          <ChapterDeepView chapters={overview!.chapter_analyses!} />
        ) : (
          <ChapterTimeline chapters={overview?.chapter_summaries ?? []} />
        )}
      </RevealSection>

      {/* Character gallery */}
      <RevealSection
        show={hasKG && (overview?.characters_brief?.length ?? 0) > 0}
        delay={200}
      >
        <CharacterGallery
          characters={overview?.characters_brief ?? []}
          sessionId={sessionId!}
          bookType={overview?.book_type}
        />
      </RevealSection>

      {/* Narrative rhythm — event-annotated chart (replaces abstract valence) */}
      <RevealSection
        show={hasKG && (overview?.narrative_rhythm?.length ?? 0) > 0}
        delay={250}
      >
        <NarrativeRhythmChart points={overview!.narrative_rhythm!} />
      </RevealSection>

      {/* Charts row — emotion radar + legacy arc fallback */}
      <RevealSection show={hasAnalysis} delay={300}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {overview?.emotion_scores && overview.emotion_scores.length > 0 && (
            <EmotionRadar emotionScores={overview.emotion_scores} bookType={overview.book_type} />
          )}
          {/* Fallback: show old ArcChart only if no narrative rhythm data */}
          {!(overview?.narrative_rhythm?.length) &&
            overview?.valence_series &&
            overview.valence_series.length > 0 && (
              <ArcChart
                valenceSeries={overview.valence_series}
                arcPattern={overview.arc_pattern}
              />
            )}
        </div>
      </RevealSection>

      {/* Inline search — collapsible */}
      {sessionId && !isExtracting && hasKG && (
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl overflow-hidden animate-[fadeSlideIn_0.5s_ease-out_both]" style={{ animationDelay: "400ms" }}>
          <button
            onClick={() => setSearchOpen((v) => !v)}
            className="w-full px-5 py-3 flex items-center justify-between text-left hover:bg-[var(--surface-hover)] transition-colors"
          >
            <span className="flex items-center gap-2">
              <Search className="w-4 h-4 text-[var(--accent)]" />
              <span
                className="text-lg text-[var(--accent)]"
                style={{ fontFamily: "var(--font-display)" }}
              >
                全文搜索
              </span>
            </span>
            {searchOpen ? (
              <ChevronDown className="w-4 h-4 text-[var(--text-secondary)]" />
            ) : (
              <ChevronRight className="w-4 h-4 text-[var(--text-secondary)]" />
            )}
          </button>
          {searchOpen && (
            <div className="border-t border-[var(--border)]">
              <SearchPanel sessionId={sessionId} embedded />
            </div>
          )}
        </div>
      )}

      {/* Empty state — only show when nothing is happening and no data */}
      {!isExtracting && !hasKG && !hasAnalysis && (
        <div className="flex flex-col items-center justify-center h-64 text-[var(--text-secondary)]">
          <p className="text-sm">等待数据... 提取可能尚未开始。</p>
        </div>
      )}
    </div>
  );
}
