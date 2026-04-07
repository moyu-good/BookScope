import { useMemo } from "react";
import { Loader2 } from "lucide-react";
import clsx from "clsx";
import type { SSEEvent } from "../lib/types";

interface ExtractionProgressProps {
  events: SSEEvent[];
}

interface Stage {
  key: string;
  label: string;
  done: boolean;
}

export default function ExtractionProgress({
  events,
}: ExtractionProgressProps) {
  const stages = useMemo<Stage[]>(() => {
    const completedTypes = new Set(
      events
        .filter(
          (e) => e.type === "stage_complete" || e.type === "kg_complete" || e.type === "analysis_complete",
        )
        .map((e) => String(e.stage ?? e.type)),
    );

    const currentType =
      events.length > 0 ? events[events.length - 1].type : "";

    return [
      {
        key: "kg",
        label: "正在提取知识图谱...",
        done:
          completedTypes.has("kg") ||
          completedTypes.has("kg_complete"),
      },
      {
        key: "emotions",
        label: "正在分析情绪...",
        done:
          completedTypes.has("emotions") ||
          completedTypes.has("analysis_complete"),
      },
      {
        key: "style",
        label: "正在分析文风...",
        done:
          completedTypes.has("style") ||
          completedTypes.has("analysis_complete"),
      },
    ].map((s) => ({
      ...s,
      done:
        s.done ||
        (currentType === "done" || currentType === "complete"),
    }));
  }, [events]);

  const doneCount = stages.filter((s) => s.done).length;
  const progress = Math.round((doneCount / stages.length) * 100);

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-5">
      {/* Progress bar */}
      <div className="h-1.5 bg-[var(--border)] rounded-full overflow-hidden mb-4">
        <div
          className="h-full bg-[var(--accent)] rounded-full transition-all duration-700 ease-out"
          style={{ width: `${Math.max(progress, 8)}%` }}
        />
      </div>

      {/* Stages */}
      <div className="space-y-2">
        {stages.map((stage) => {
          const isActive = !stage.done && stages.findIndex((s) => !s.done) === stages.indexOf(stage);
          return (
            <div
              key={stage.key}
              className={clsx(
                "flex items-center gap-2 text-sm transition-all duration-200",
                stage.done
                  ? "text-[var(--trust)]"
                  : isActive
                    ? "text-[var(--text)]"
                    : "text-[var(--text-secondary)]",
              )}
            >
              {stage.done ? (
                <span className="w-4 h-4 flex items-center justify-center text-xs">
                  ✓
                </span>
              ) : isActive ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <span className="w-4 h-4 flex items-center justify-center text-xs opacity-40">
                  ○
                </span>
              )}
              {stage.label}
            </div>
          );
        })}
      </div>
    </div>
  );
}
