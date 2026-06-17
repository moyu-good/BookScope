import { useState } from "react";
import { BookOpenText, ChevronDown, ChevronUp, Users, Sparkles } from "lucide-react";
import clsx from "clsx";
import type { ChapterAnalysis } from "../lib/types";

interface ChapterDeepViewProps {
  chapters: ChapterAnalysis[];
}

const INITIAL_VISIBLE = 3;

function ChapterCard({
  chapter,
  defaultOpen,
}: {
  chapter: ChapterAnalysis;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border border-[var(--border)] rounded-lg overflow-hidden">
      {/* Header — always visible */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-5 py-3.5 flex items-center gap-3 text-left hover:bg-[var(--surface-hover)] transition-colors cursor-pointer"
      >
        <span className="shrink-0 w-7 h-7 rounded-full bg-[var(--accent)]/10 text-[var(--accent)] flex items-center justify-center text-xs font-medium">
          {chapter.chapter_index}
        </span>
        <span className="flex-1 min-w-0">
          <span className="block text-sm font-medium text-[var(--text)] truncate">
            {chapter.title || `第 ${chapter.chapter_index} 章`}
          </span>
          {!open && chapter.key_points.length > 0 && (
            <span className="block text-xs text-[var(--text-secondary)] mt-0.5 truncate">
              {chapter.key_points[0]}
            </span>
          )}
        </span>
        {open ? (
          <ChevronUp className="w-4 h-4 text-[var(--text-secondary)] shrink-0" />
        ) : (
          <ChevronDown className="w-4 h-4 text-[var(--text-secondary)] shrink-0" />
        )}
      </button>

      {/* Expanded content */}
      {open && (
        <div className="px-5 pb-5 border-t border-[var(--border)] space-y-4">
          {/* Analysis text */}
          <p className="text-sm text-[var(--text)] leading-loose whitespace-pre-line pt-4">
            {chapter.analysis}
          </p>

          {/* Key points */}
          {chapter.key_points.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-[var(--accent)] mb-2 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5" />
                核心要点
              </h4>
              <ul className="space-y-1.5">
                {chapter.key_points.map((point, i) => (
                  <li
                    key={i}
                    className="text-xs text-[var(--text-secondary)] leading-relaxed flex gap-2"
                  >
                    <span className="text-[var(--accent)] shrink-0 mt-0.5">•</span>
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Characters involved */}
          {chapter.characters_involved.length > 0 && (
            <div className="flex items-start gap-2">
              <Users className="w-3.5 h-3.5 text-[var(--text-secondary)] mt-0.5 shrink-0" />
              <div className="flex flex-wrap gap-1.5">
                {chapter.characters_involved.map((name) => (
                  <span
                    key={name}
                    className="px-2 py-0.5 text-[10px] rounded-full bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/20"
                  >
                    {name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Significance */}
          {chapter.significance && (
            <div className="bg-[var(--bg)] rounded-lg px-4 py-3 border-l-2 border-[var(--accent)]">
              <p className="text-xs text-[var(--text-secondary)] leading-relaxed italic">
                {chapter.significance}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ChapterDeepView({ chapters }: ChapterDeepViewProps) {
  const [showAll, setShowAll] = useState(false);
  const sorted = [...chapters].sort(
    (a, b) => a.chapter_index - b.chapter_index,
  );
  const visible = showAll ? sorted : sorted.slice(0, INITIAL_VISIBLE);
  const hasMore = sorted.length > INITIAL_VISIBLE;

  if (sorted.length === 0) return null;

  return (
    <div className="ink-card bg-[var(--surface)] border border-[var(--border)] rounded-xl p-6">
      <div className="flex items-center gap-2 mb-5">
        <BookOpenText className="w-5 h-5 text-[var(--accent)]" />
        <h2 className="text-2xl text-[var(--accent)]">章节深度分析</h2>
        <span className="text-xs text-[var(--text-secondary)] ml-auto">
          共 {sorted.length} 章
        </span>
      </div>

      <div className="space-y-3">
        {visible.map((ch, i) => (
          <ChapterCard
            key={ch.chapter_index}
            chapter={ch}
            defaultOpen={i === 0}
          />
        ))}
      </div>

      {hasMore && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className={clsx(
            "mt-4 flex items-center gap-1.5 text-xs transition-colors duration-200 cursor-pointer",
            "text-[var(--accent)] hover:text-[var(--accent-hover)]",
          )}
        >
          {showAll ? (
            <>
              收起 <ChevronUp className="w-3.5 h-3.5" />
            </>
          ) : (
            <>
              展开全部 {sorted.length} 章 <ChevronDown className="w-3.5 h-3.5" />
            </>
          )}
        </button>
      )}
    </div>
  );
}
