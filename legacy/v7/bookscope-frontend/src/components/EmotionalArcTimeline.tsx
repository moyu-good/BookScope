import { TrendingUp } from "lucide-react";

interface EmotionalStage {
  stage: string;
  emotion: string;
  event: string;
}

interface EmotionalArcTimelineProps {
  stages: EmotionalStage[];
}

const STAGE_LABELS: Record<string, string> = {
  early: "前期",
  middle: "中期",
  late: "后期",
};

const STAGE_COLORS: Record<string, string> = {
  early: "bg-emerald-500",
  middle: "bg-amber-500",
  late: "bg-rose-500",
};

const STAGE_TEXT_COLORS: Record<string, string> = {
  early: "text-emerald-400",
  middle: "text-amber-400",
  late: "text-rose-400",
};

export default function EmotionalArcTimeline({
  stages,
}: EmotionalArcTimelineProps) {
  return (
    <div className="ink-card bg-[var(--surface)] border border-[var(--border)] rounded-xl p-5">
      <div className="flex items-center gap-2 mb-5">
        <TrendingUp className="w-4 h-4 text-[var(--accent)]" />
        <h2 className="text-xl text-[var(--accent)]">
          情感弧线
        </h2>
      </div>

      <div className="relative">
        {/* Connecting line */}
        <div className="absolute left-3 top-3 bottom-3 w-px bg-[var(--border)]" />

        <div className="space-y-6">
          {stages.map((s, i) => {
            const dotColor = STAGE_COLORS[s.stage] ?? "bg-[var(--accent)]";
            const textColor =
              STAGE_TEXT_COLORS[s.stage] ?? "text-[var(--accent)]";
            const label = STAGE_LABELS[s.stage] ?? s.stage;

            return (
              <div key={i} className="relative flex items-start gap-4 pl-0">
                {/* Dot */}
                <div className="relative z-10 shrink-0 mt-0.5">
                  <div
                    className={`w-6 h-6 rounded-full ${dotColor} flex items-center justify-center`}
                  >
                    <div className="w-2 h-2 rounded-full bg-[var(--bg)]" />
                  </div>
                </div>

                {/* Content */}
                <div className="min-w-0 pb-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={`text-xs font-semibold uppercase tracking-wider ${textColor}`}
                    >
                      {label}
                    </span>
                    <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-[var(--surface-hover)] text-[var(--text-secondary)]">
                      {s.emotion}
                    </span>
                  </div>
                  <p className="text-sm text-[var(--text)] leading-relaxed">
                    {s.event}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
