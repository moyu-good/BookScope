import { useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  ResponsiveContainer,
  CartesianGrid,
  Tooltip,
  ReferenceDot,
} from "recharts";
import { Activity } from "lucide-react";
import type { NarrativePoint } from "../lib/types";

interface NarrativeRhythmChartProps {
  points: NarrativePoint[];
}

const TYPE_LABELS: Record<string, string> = {
  setup: "铺垫",
  rising: "上升",
  climax: "高潮",
  turning: "转折",
  falling: "下降",
  resolution: "收束",
};

/** Sanitize point_type from backend to known Chinese labels */
function localizeType(raw: string): string {
  return TYPE_LABELS[raw] ?? raw;
}

const TYPE_COLORS: Record<string, string> = {
  setup: "var(--text-secondary)",
  rising: "var(--accent)",
  climax: "#e74c3c",
  turning: "#f39c12",
  falling: "var(--text-secondary)",
  resolution: "var(--accent)",
};

const PHASE_DESCRIPTIONS: Record<string, string> = {
  setup: "背景交代，故事铺垫展开",
  rising: "矛盾积累，情节持续上升",
  climax: "全书最激烈的冲突与高潮",
  turning: "关键转折，局势发生逆转",
  falling: "冲突缓解，后续影响显现",
  resolution: "故事收束，结局呈现",
};

function intensityLabel(v: number): string {
  if (v >= 0.8) return "极高张力";
  if (v >= 0.6) return "高张力";
  if (v >= 0.3) return "中等张力";
  return "平缓叙述";
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: { title: string; event_label: string; intensity: number; point_type: string; chapter: string; phaseRange?: string } }> }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  const typeLabel = TYPE_LABELS[d.point_type] ?? d.point_type;
  const typeColor = TYPE_COLORS[d.point_type] ?? "var(--accent)";
  const phaseDesc = PHASE_DESCRIPTIONS[d.point_type] ?? "";

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3.5 py-2.5 shadow-lg max-w-[260px]">
      <p className="text-xs font-medium text-[var(--text)] mb-1">{d.title}</p>
      <p className="text-xs text-[var(--accent)] mb-1.5 leading-relaxed">{d.event_label}</p>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span
          className="inline-block w-2 h-2 rounded-full"
          style={{ backgroundColor: typeColor }}
        />
        <span className="text-[11px] font-medium" style={{ color: typeColor }}>
          {typeLabel}
        </span>
        <span className="text-[10px] text-[var(--text-secondary)]">
          — {phaseDesc}
        </span>
      </div>
      <div className="flex items-center justify-between text-[10px] text-[var(--text-secondary)] pt-1 border-t border-[var(--border)]">
        <span>{intensityLabel(d.intensity)}</span>
        <span className="font-mono">{Math.round(d.intensity * 100)}%</span>
      </div>
    </div>
  );
}

export default function NarrativeRhythmChart({
  points,
}: NarrativeRhythmChartProps) {
  const chartData = useMemo(
    () =>
      points.map((p) => ({
        chapter: `${p.chapter_index}`,
        title: p.title || `第${p.chapter_index}章`,
        intensity: Math.round(p.intensity * 1000) / 1000,
        event_label: p.event_label,
        point_type: p.point_type,
      })),
    [points],
  );

  // Identify key moments (climax + turning) for annotation dots
  const keyMoments = useMemo(
    () =>
      chartData.filter(
        (d) => d.point_type === "climax" || d.point_type === "turning",
      ),
    [chartData],
  );

  // Group consecutive chapters by phase for the interval summary
  const phaseGroups = useMemo(() => {
    if (chartData.length === 0) return [];
    const groups: Array<{
      phase: string;
      chapters: typeof chartData;
      startChapter: string;
      endChapter: string;
      avgIntensity: number;
    }> = [];
    let current = chartData[0].point_type;
    let group = [chartData[0]];

    for (let i = 1; i < chartData.length; i++) {
      if (chartData[i].point_type === current) {
        group.push(chartData[i]);
      } else {
        const avg = group.reduce((s, d) => s + d.intensity, 0) / group.length;
        groups.push({
          phase: current,
          chapters: group,
          startChapter: group[0].chapter,
          endChapter: group[group.length - 1].chapter,
          avgIntensity: avg,
        });
        current = chartData[i].point_type;
        group = [chartData[i]];
      }
    }
    const avg = group.reduce((s, d) => s + d.intensity, 0) / group.length;
    groups.push({
      phase: current,
      chapters: group,
      startChapter: group[0].chapter,
      endChapter: group[group.length - 1].chapter,
      avgIntensity: avg,
    });
    return groups;
  }, [chartData]);

  if (points.length === 0) return null;

  return (
    <div className="ink-card bg-[var(--surface)] border border-[var(--border)] rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Activity className="w-5 h-5 text-[var(--accent)]" />
        <h2 className="text-xl text-[var(--accent)]">叙事节奏</h2>
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={chartData} margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="rhythmGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--border)"
            vertical={false}
          />
          <XAxis
            dataKey="chapter"
            tick={{ fill: "var(--text-secondary)", fontSize: 10 }}
            axisLine={{ stroke: "var(--border)" }}
            tickLine={false}
            label={{
              value: "章节",
              position: "insideBottomRight",
              offset: -5,
              style: { fill: "var(--text-secondary)", fontSize: 10 },
            }}
          />
          <YAxis
            domain={[0, 1]}
            tick={{ fill: "var(--text-secondary)", fontSize: 10 }}
            axisLine={{ stroke: "var(--border)" }}
            tickLine={false}
            width={30}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
          />
          <Tooltip content={<CustomTooltip />} />
          <Area
            type="monotone"
            dataKey="intensity"
            stroke="var(--accent)"
            strokeWidth={2}
            fill="url(#rhythmGradient)"
          />
          {/* Highlight climax and turning points */}
          {keyMoments.map((m) => (
            <ReferenceDot
              key={m.chapter}
              x={m.chapter}
              y={m.intensity}
              r={5}
              fill={TYPE_COLORS[m.point_type] ?? "var(--accent)"}
              stroke="var(--surface)"
              strokeWidth={2}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>

      {/* Phase interval summary */}
      {phaseGroups.length > 0 && (
        <div className="mt-4 space-y-1.5">
          <p className="text-[10px] text-[var(--text-secondary)] tracking-wider mb-2">叙事区间</p>
          {phaseGroups.map((g, i) => {
            const color = TYPE_COLORS[g.phase] ?? "var(--text-secondary)";
            const label = TYPE_LABELS[g.phase] ?? g.phase;
            const range = g.startChapter === g.endChapter
              ? `第${g.startChapter}章`
              : `第${g.startChapter}-${g.endChapter}章`;
            const topEvent = g.chapters.reduce((best, d) =>
              d.intensity > best.intensity ? d : best,
            );
            return (
              <div
                key={`${g.phase}-${i}`}
                className="flex items-start gap-2.5 px-3 py-2 rounded-lg bg-[var(--bg)]/50 border border-[var(--border)]/50"
              >
                <span
                  className="w-2 h-2 rounded-full mt-1 shrink-0"
                  style={{ backgroundColor: color }}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-[11px] font-medium" style={{ color }}>
                      {label}
                    </span>
                    <span className="text-[10px] text-[var(--text-secondary)]">
                      {range}
                    </span>
                    <span className="text-[10px] text-[var(--text-secondary)] ml-auto font-mono">
                      {Math.round(g.avgIntensity * 100)}%
                    </span>
                  </div>
                  <p className="text-[10px] text-[var(--text-secondary)] leading-relaxed">
                    {topEvent.event_label}
                    {g.chapters.length > 1 && topEvent !== g.chapters[0] && g.chapters[0].event_label &&
                      `；${g.chapters[0].event_label}`}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
