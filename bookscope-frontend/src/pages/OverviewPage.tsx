import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchOverview } from "../lib/api";
import { useExtraction } from "./BookLayout";
import ExtractionProgress from "../components/ExtractionProgress";
import BookSummaryCard from "../components/BookSummaryCard";
import VerdictCard from "../components/VerdictCard";
import ChapterTimeline from "../components/ChapterTimeline";
import CharacterGallery from "../components/CharacterGallery";
import EmotionRadar from "../components/EmotionRadar";
import ArcChart from "../components/ArcChart";

export default function OverviewPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { isExtracting, sseEvents } = useExtraction();

  const { data: overview } = useQuery({
    queryKey: ["overview", sessionId],
    queryFn: () => fetchOverview(sessionId!),
    enabled: !!sessionId,
    refetchInterval: isExtracting ? 2000 : false,
  });

  const hasKG =
    !!overview?.overall_summary || (overview?.characters_brief?.length ?? 0) > 0;
  const hasAnalysis = !!overview?.arc_pattern || !!overview?.reader_verdict;

  return (
    <div className="space-y-6">
      {/* Extraction progress */}
      {isExtracting && <ExtractionProgress events={sseEvents} />}

      {/* Book summary */}
      {hasKG && overview?.overall_summary && (
        <BookSummaryCard
          summary={overview.overall_summary}
          themes={overview.themes ?? []}
        />
      )}

      {/* Reader verdict */}
      {hasAnalysis && overview?.reader_verdict && (
        <VerdictCard verdict={overview.reader_verdict} />
      )}

      {/* Chapter timeline */}
      {hasKG &&
        overview?.chapter_summaries &&
        overview.chapter_summaries.length > 0 && (
          <ChapterTimeline chapters={overview.chapter_summaries} />
        )}

      {/* Character gallery */}
      {hasKG &&
        overview?.characters_brief &&
        overview.characters_brief.length > 0 && (
          <CharacterGallery
            characters={overview.characters_brief}
            sessionId={sessionId!}
          />
        )}

      {/* Charts row */}
      {hasAnalysis && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {overview?.emotion_scores && overview.emotion_scores.length > 0 && (
            <EmotionRadar emotionScores={overview.emotion_scores} />
          )}
          {overview?.valence_series && overview.valence_series.length > 0 && (
            <ArcChart
              valenceSeries={overview.valence_series}
              arcPattern={overview.arc_pattern}
            />
          )}
        </div>
      )}

      {/* Empty state */}
      {!isExtracting && !hasKG && !hasAnalysis && (
        <div className="flex flex-col items-center justify-center h-64 text-[var(--text-secondary)]">
          <p className="text-sm">
            等待数据... 提取可能尚未开始。
          </p>
        </div>
      )}
    </div>
  );
}
