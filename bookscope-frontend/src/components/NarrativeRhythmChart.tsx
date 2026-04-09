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

function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: { title: string; event_label: string; intensity: number; point_type: string } }> }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 shadow-lg max-w-[220px]">
      <p className="text-xs font-medium text-[var(--text)] mb-1">{d.title}</p>
      <p className="text-xs text-[var(--accent)] mb-1">{d.event_label}</p>
      <div className="flex items-center gap-2 text-[10px] text-[var(--text-secondary)]">
        <span>{TYPE_LABELS[d.point_type] ?? d.point_type}</span>
        <span>·</span>
        <span>张力 {Math.round(d.intensity * 100)}%</span>
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

      {/* Event annotation strip */}
      {keyMoments.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {keyMoments.map((m) => (
            <span
              key={m.chapter}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[10px] rounded-full border"
              style={{
                borderColor: TYPE_COLORS[m.point_type] ?? "var(--border)",
                color: TYPE_COLORS[m.point_type] ?? "var(--text-secondary)",
              }}
            >
              <span
                className="w-1.5 h-1.5 rounded-full"
                style={{ backgroundColor: TYPE_COLORS[m.point_type] ?? "var(--accent)" }}
              />
              {m.title}: {m.event_label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
