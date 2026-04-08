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
  progress?: string;
}

export default function ExtractionProgress({
  events,
}: ExtractionProgressProps) {
  const stages = useMemo<Stage[]>(() => {
    // Collect event types seen
    const seenTypes = new Set(events.map((e) => e.type));
    const isDone = seenTypes.has("done");

    // Track per-stage progress from progress events
    const stageProgress: Record<string, { current: number; total: number }> = {};
    for (const e of events) {
      if (e.type === "progress" && e.stage) {
        stageProgress[String(e.stage)] = {
          current: Number(e.current ?? 0),
          total: Number(e.total ?? 0),
        };
      }
    }

    // Tier 1 complete when tier1_ready or analysis_ready seen
    const tier1Done = seenTypes.has("tier1_ready") || seenTypes.has("analysis_ready") || isDone;
    // Tier 2 complete when kg_ready seen
    const tier2Done = seenTypes.has("kg_ready") || isDone;

    const emotionP = stageProgress["emotion"];
    const styleP = stageProgress["style"];
    const kgP = stageProgress["kg"];

    return [
      {
        key: "emotion",
        label: tier1Done ? "情感分析完成" : "正在分析情感...",
        done: tier1Done,
        progress: emotionP && !tier1Done
          ? `${emotionP.current}/${emotionP.total}`
          : undefined,
      },
      {
        key: "style",
        label: tier1Done ? "文风分析完成" : "正在分析文风...",
        done: tier1Done,
        progress: styleP && !tier1Done
          ? `${styleP.current}/${styleP.total}`
          : undefined,
      },
      {
        key: "kg",
        label: tier2Done ? "知识图谱提取完成" : "正在提取知识图谱...",
        done: tier2Done,
        progress: kgP && !tier2Done
          ? `${kgP.current}/${kgP.total}`
          : undefined,
      },
    ];
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
              <span>{stage.label}</span>
              {stage.progress && (
                <span className="ml-1 text-xs opacity-60">({stage.progress})</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
