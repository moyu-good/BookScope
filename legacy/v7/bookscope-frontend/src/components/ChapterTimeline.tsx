import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import clsx from "clsx";
import type { ChapterSummary } from "../lib/types";

interface ChapterTimelineProps {
  chapters: ChapterSummary[];
}

const INITIAL_VISIBLE = 5;

export default function ChapterTimeline({ chapters }: ChapterTimelineProps) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? chapters : chapters.slice(0, INITIAL_VISIBLE);
  const hasMore = chapters.length > INITIAL_VISIBLE;

  return (
    <div className="ink-card bg-[var(--surface)] border border-[var(--border)] rounded-xl p-5">
      <h2 className="text-xl text-[var(--accent)] mb-4">
        章节时间线
      </h2>

      <div className="relative">
        {/* Vertical line */}
        <div className="absolute left-[7px] top-2 bottom-2 w-px bg-[var(--border)]" />

        <div className="space-y-4">
          {visible.map((ch, i) => (
            <div key={ch.chunk_index} className="relative pl-7">
              {/* Dot */}
              <div
                className={clsx(
                  "absolute left-0 top-1.5 w-[15px] h-[15px] rounded-full border-2",
                  i === 0
                    ? "border-[var(--accent)] bg-[var(--accent)]/20"
                    : "border-[var(--border)] bg-[var(--surface)]",
                )}
              />

              <div>
                <h3 className="text-sm font-medium text-[var(--text)]">
                  {ch.title || `第 ${ch.chunk_index + 1} 章`}
                </h3>
                <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed">
                  {ch.summary}
                </p>

                {ch.characters_mentioned.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {ch.characters_mentioned.map((name) => (
                      <span
                        key={name}
                        className="px-2 py-0.5 text-[10px] rounded-full bg-[var(--bg)] text-[var(--text-secondary)] border border-[var(--border)]"
                      >
                        {name}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {hasMore && (
        <button
          onClick={() => setExpanded((p) => !p)}
          className="mt-4 flex items-center gap-1 text-xs text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors duration-200 cursor-pointer"
        >
          {expanded ? (
            <>
              收起 <ChevronUp className="w-3 h-3" />
            </>
          ) : (
            <>
              展开全部 {chapters.length} 章{" "}
              <ChevronDown className="w-3 h-3" />
            </>
          )}
        </button>
      )}
    </div>
  );
}
