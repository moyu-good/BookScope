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
  FeatureGuide,
} from "../components/imperial/MemorialSection";
import ImperialBrush from "../components/imperial/ImperialBrush";
import BookOutline from "../components/BookOutline";
import BookSummaryCard from "../components/BookSummaryCard";
import VerdictHero from "../components/VerdictHero";
import ChapterDeepView from "../components/ChapterDeepView";
import ChapterTimeline from "../components/ChapterTimeline";
import CharacterGallery from "../components/CharacterGallery";
import NarrativeRhythmChart from "../components/NarrativeRhythmChart";
import SearchPanel from "../components/SearchPanel";

type SectionKey = string;

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
  children,
}: {
  sectionKey: string;
  title: string;
  preview?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const reads = useReadState();

  const askAboutSection = () => {
    window.dispatchEvent(
      new CustomEvent("bookscope:ask-section", {
        detail: { title, sectionKey },
      }),
    );
  };

  return (
    <MemorialSection
      title={title}
      preview={preview}
      defaultOpen={defaultOpen}
      isRead={reads.isRead(sectionKey)}
      actions={
        <>
          <AnnotateButton onClick={askAboutSection} disabled={false} />
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
    <div className="pb-48">
      {/* Extraction progress */}
      {isExtracting && <ExtractionProgress events={sseEvents} />}

      {/* ══════════════════════════════════════════════════════════
          HERO — 阅读判断（唯一答案，不可折叠，视觉顶层）
         ══════════════════════════════════════════════════════════ */}
      {hasAnalysis && overview?.reader_verdict && (
        <VerdictHero
          verdict={overview.reader_verdict}
          bookTitle={overview.title}
        />
      )}

      {/* One-shot feature guide — shown once then dismissed forever */}
      {hasAnyData && (
        <div className="px-6 sm:px-10 pt-2">
          <FeatureGuide />
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════
          EVIDENCE — 支撑判断的证据链（折叠栈）
         ══════════════════════════════════════════════════════════ */}
      {hasAnyData && (
        <div className="space-y-0">
          {/* Divider: 以下为证据链 */}
          {(hasAnalysis || hasKG) && (
            <div className="px-6 sm:px-10 py-3 flex items-center gap-3">
              <div
                className="flex-1 h-px"
                style={{ background: "var(--fold-line)" }}
              />
              <span
                className="text-[11px] tracking-widest uppercase"
                style={{
                  color: "var(--parchment-text-secondary)",
                  fontFamily: "var(--font-display)",
                  letterSpacing: "0.2em",
                }}
              >
                以下为支撑此判断的证据
              </span>
              <div
                className="flex-1 h-px"
                style={{ background: "var(--fold-line)" }}
              />
            </div>
          )}

          {/* ── Tier 2 loading placeholder ── */}
          {kgLoading && (
            <div className="memorial-section px-6 py-8 text-center">
              <div className="flex items-center justify-center gap-3 text-[var(--parchment-text-secondary)]">
                <div className="w-4 h-4 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                <span
                  className="text-sm tracking-wide"
                  style={{ fontFamily: "var(--font-display)", letterSpacing: "0.08em" }}
                >
                  正在提取证据链（章节分析、人物、叙事节奏）...
                </span>
              </div>
            </div>
          )}

          {/* ── 1. Book Outline / Summary (Tier 2) ── */}
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

          {/* ── 2. Chapter Deep Analysis (Tier 2) ── */}
          {((overview?.chapter_analyses?.length ?? 0) > 0 ||
            (overview?.chapter_summaries?.length ?? 0) > 0) && (
            <>
              <AnnotatedMemorial
                sectionKey="chapters"
                title="章节分析"
                preview={`共 ${overview?.chapter_analyses?.length || overview?.chapter_summaries?.length || 0} 章`}
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

          {/* ── 3. Character Gallery (Tier 2) ── */}
          {(overview?.characters_brief?.length ?? 0) > 0 && (
            <>
              <AnnotatedMemorial
                sectionKey="characters"
                title="人物志"
                preview={overview!.characters_brief!
                  .slice(0, 4)
                  .map((c) => c.name)
                  .join("、")}
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

          {/* ── 4. Narrative Rhythm (Tier 2) ── */}
          {(overview?.narrative_rhythm?.length ?? 0) > 0 && (
            <>
              <AnnotatedMemorial
                sectionKey="rhythm"
                title="叙事节奏"
                preview="全书张力与关键事件标注"
              >
                <NarrativeRhythmChart points={overview!.narrative_rhythm!} />
              </AnnotatedMemorial>
              <FoldCrease />
            </>
          )}

          {/* ── 5. Search ── */}
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
