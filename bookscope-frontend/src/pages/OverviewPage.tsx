import { useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Search, ChevronDown, ChevronRight } from "lucide-react";
import { fetchOverview } from "../lib/api";
import { useExtraction } from "./BookLayout";
import ExtractionProgress from "../components/ExtractionProgress";
import MemorialSection, {
  FoldCrease,
  ReadStamp,
  AnnotateButton,
} from "../components/imperial/MemorialSection";
import VermillionAnnotation, {
  type Annotation,
} from "../components/imperial/VermillionAnnotation";
import ImperialBrush from "../components/imperial/ImperialBrush";
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
/*  Annotation state management                                       */
/* ------------------------------------------------------------------ */

type SectionKey = string;

function useAnnotations() {
  const [store, setStore] = useState<Record<SectionKey, Annotation[]>>({});
  const [composing, setComposing] = useState<SectionKey | null>(null);

  const get = useCallback(
    (key: SectionKey) => store[key] ?? [],
    [store],
  );

  const update = useCallback(
    (key: SectionKey, annotations: Annotation[]) =>
      setStore((prev) => ({ ...prev, [key]: annotations })),
    [],
  );

  return { get, update, composing, setComposing };
}

function useReadState() {
  const [reads, setReads] = useState<Set<SectionKey>>(new Set());
  const mark = useCallback(
    (key: SectionKey) => setReads((prev) => new Set(prev).add(key)),
    [],
  );
  const isRead = useCallback((key: SectionKey) => reads.has(key), [reads]);
  return { mark, isRead };
}

/* ------------------------------------------------------------------ */
/*  Memorial wrapper — adds 朱批 + 已阅 to any section                */
/* ------------------------------------------------------------------ */

function AnnotatedMemorial({
  sectionKey,
  title,
  preview,
  defaultOpen,
  sessionId,
  annotations,
  children,
}: {
  sectionKey: string;
  title: string;
  preview?: string;
  defaultOpen?: boolean;
  sessionId: string;
  annotations: ReturnType<typeof useAnnotations>;
  children: React.ReactNode;
}) {
  const reads = useReadState();

  return (
    <MemorialSection
      title={title}
      preview={preview}
      defaultOpen={defaultOpen}
      isRead={reads.isRead(sectionKey)}
      annotations={
        (annotations.get(sectionKey).length > 0 ||
          annotations.composing === sectionKey) && (
          <VermillionAnnotation
            sessionId={sessionId}
            annotations={annotations.get(sectionKey)}
            onUpdate={(a) => annotations.update(sectionKey, a)}
            isComposing={annotations.composing === sectionKey}
            onComposingChange={(v) =>
              annotations.setComposing(v ? sectionKey : null)
            }
            sectionContext={title}
          />
        )
      }
      actions={
        <>
          <AnnotateButton
            onClick={() =>
              annotations.setComposing(
                annotations.composing === sectionKey ? null : sectionKey,
              )
            }
            disabled={false}
          />
          <ReadStamp
            isRead={reads.isRead(sectionKey)}
            onMark={() => reads.mark(sectionKey)}
          />
        </>
      }
    >
      {children}
    </MemorialSection>
  );
}

/* ------------------------------------------------------------------ */
/*  Imperial Review — OverviewPage                                    */
/* ------------------------------------------------------------------ */

export default function OverviewPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { isExtracting, sseEvents, characters } = useExtraction();
  const [searchOpen, setSearchOpen] = useState(false);
  const annotations = useAnnotations();

  const { data: overview } = useQuery({
    queryKey: ["overview", sessionId],
    queryFn: () => fetchOverview(sessionId!),
    enabled: !!sessionId,
    refetchInterval: isExtracting ? 2000 : false,
  });

  // Tier 1 data: emotion/style/arc/verdict (available in <30s)
  const hasAnalysis = !!overview?.arc_pattern || !!overview?.reader_verdict;
  // Tier 2 data: KG/chapters/characters/outline/rhythm (available in ~1-2 min)
  const hasKG =
    !!overview?.book_outline ||
    !!overview?.overall_summary ||
    (overview?.characters_brief?.length ?? 0) > 0;
  // Anything to show at all
  const hasAnyData = hasAnalysis || hasKG;
  // KG still loading (extracting but no KG yet)
  const kgLoading = isExtracting && !hasKG;

  if (!sessionId) return null;

  return (
    <div className="pb-36">
      {/* Extraction progress */}
      {isExtracting && <ExtractionProgress events={sseEvents} />}

      {/* ── Memorial Fold Stack ──────────────────────── */}
      {hasAnyData && (
        <div className="space-y-0">
          {/* ── Tier 1: Immediate results (emotion/style/verdict) ── */}

          {/* 1. Reader Verdict (Tier 1) */}
          {hasAnalysis && overview?.reader_verdict && (
            <>
              <AnnotatedMemorial
                sectionKey="verdict"
                title="阅读判断"
                preview={overview.reader_verdict.sentence}
                sessionId={sessionId}
                annotations={annotations}
              >
                <VerdictCard verdict={overview.reader_verdict} />
              </AnnotatedMemorial>
              <FoldCrease />
            </>
          )}

          {/* 2. Emotion / Style Analysis (Tier 1) */}
          {hasAnalysis && (
            <>
              <AnnotatedMemorial
                sectionKey="emotion"
                title="情感基调"
                preview={overview?.dominant_emotion ? `主导情绪：${overview.dominant_emotion}` : "全书情感分布"}
                defaultOpen={!hasKG}
                sessionId={sessionId}
                annotations={annotations}
              >
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {overview?.emotion_scores &&
                    overview.emotion_scores.length > 0 && (
                      <EmotionRadar
                        emotionScores={overview.emotion_scores}
                        bookType={overview.book_type}
                      />
                    )}
                  {overview?.valence_series &&
                    overview.valence_series.length > 0 && (
                      <ArcChart
                        valenceSeries={overview.valence_series}
                        arcPattern={overview.arc_pattern}
                      />
                    )}
                </div>
              </AnnotatedMemorial>
              <FoldCrease />
            </>
          )}

          {/* ── Tier 2 loading placeholder ── */}
          {kgLoading && hasAnalysis && (
            <div className="memorial-section px-6 py-8 text-center">
              <div className="flex items-center justify-center gap-3 text-[var(--parchment-text-secondary)]">
                <div className="w-4 h-4 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                <span
                  className="text-sm tracking-wide"
                  style={{ fontFamily: "var(--font-display)", letterSpacing: "0.08em" }}
                >
                  正在提取知识图谱（章节分析、人物、叙事节奏）...
                </span>
              </div>
            </div>
          )}

          {/* ── Tier 2: KG results (outline/chapters/characters/rhythm) ── */}

          {/* 3. Book Outline / Summary (Tier 2) */}
          {(overview?.book_outline || overview?.overall_summary) && (
            <>
              <AnnotatedMemorial
                sectionKey="outline"
                title="全书大纲"
                preview={
                  overview?.book_outline?.slice(0, 60) ||
                  overview?.overall_summary?.slice(0, 60)
                }
                defaultOpen={true}
                sessionId={sessionId}
                annotations={annotations}
              >
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
              </AnnotatedMemorial>
              <FoldCrease />
            </>
          )}

          {/* 4. Chapter Deep Analysis (Tier 2) */}
          {((overview?.chapter_analyses?.length ?? 0) > 0 ||
            (overview?.chapter_summaries?.length ?? 0) > 0) && (
            <>
              <AnnotatedMemorial
                sectionKey="chapters"
                title="章节分析"
                preview={`共 ${overview?.chapter_analyses?.length || overview?.chapter_summaries?.length || 0} 章`}
                sessionId={sessionId}
                annotations={annotations}
              >
                {(overview?.chapter_analyses?.length ?? 0) > 0 ? (
                  <ChapterDeepView chapters={overview!.chapter_analyses!} />
                ) : (
                  <ChapterTimeline
                    chapters={overview?.chapter_summaries ?? []}
                  />
                )}
              </AnnotatedMemorial>
              <FoldCrease />
            </>
          )}

          {/* 5. Character Gallery (Tier 2) */}
          {(overview?.characters_brief?.length ?? 0) > 0 && (
            <>
              <AnnotatedMemorial
                sectionKey="characters"
                title="人物志"
                preview={overview!.characters_brief!
                  .slice(0, 4)
                  .map((c) => c.name)
                  .join("、")}
                sessionId={sessionId}
                annotations={annotations}
              >
                <CharacterGallery
                  characters={overview?.characters_brief ?? []}
                  sessionId={sessionId}
                  bookType={overview?.book_type}
                />
              </AnnotatedMemorial>
              <FoldCrease />
            </>
          )}

          {/* 6. Narrative Rhythm (Tier 2) */}
          {(overview?.narrative_rhythm?.length ?? 0) > 0 && (
            <>
              <AnnotatedMemorial
                sectionKey="rhythm"
                title="叙事节奏"
                preview="全书张力与关键事件标注"
                sessionId={sessionId}
                annotations={annotations}
              >
                <NarrativeRhythmChart points={overview!.narrative_rhythm!} />
              </AnnotatedMemorial>
              <FoldCrease />
            </>
          )}

          {/* 7. Search */}
          <div className="memorial-section">
            <button
              onClick={() => setSearchOpen((v) => !v)}
              className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-[var(--parchment-dark)]/40 transition-colors cursor-pointer"
            >
              <span className="flex items-center gap-3">
                <Search className="w-4 h-4 text-[var(--parchment-text-secondary)]" />
                <span
                  className="text-lg tracking-wide"
                  style={{
                    fontFamily: "var(--font-display)",
                    color: "var(--parchment-text)",
                    letterSpacing: "0.08em",
                  }}
                >
                  全文搜索
                </span>
              </span>
              {searchOpen ? (
                <ChevronDown className="w-4 h-4 text-[var(--parchment-text-secondary)]" />
              ) : (
                <ChevronRight className="w-4 h-4 text-[var(--parchment-text-secondary)]" />
              )}
            </button>
            {searchOpen && (
              <div className="border-t border-[var(--fold-line)] px-6 pb-4">
                <SearchPanel sessionId={sessionId} embedded />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!isExtracting && !hasAnyData && (
        <div className="flex flex-col items-center justify-center h-64 text-[var(--text-secondary)]">
          <p className="text-sm">等待数据... 提取可能尚未开始。</p>
        </div>
      )}

      {/* ── Imperial Brush (fixed bottom input) ──────── */}
      {hasAnyData && (
        <ImperialBrush
          sessionId={sessionId}
          characters={characters}
        />
      )}
    </div>
  );
}
