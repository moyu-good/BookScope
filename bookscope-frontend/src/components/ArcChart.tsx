import { useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

interface ArcChartProps {
  valenceSeries: number[];
  arcPattern?: string;
}

export default function ArcChart({ valenceSeries, arcPattern }: ArcChartProps) {
  const chartData = useMemo(
    () =>
      valenceSeries.map((v, i) => ({
        index: i + 1,
        valence: Math.round(v * 1000) / 1000,
      })),
    [valenceSeries],
  );

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          叙事弧线
        </h2>
        {arcPattern && (
          <span className="px-2.5 py-1 text-xs rounded-full bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/20">
            {arcPattern}
          </span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="valenceGradient" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="0%"
                stopColor="var(--accent)"
                stopOpacity={0.3}
              />
              <stop
                offset="100%"
                stopColor="var(--accent)"
                stopOpacity={0}
              />
            </linearGradient>
          </defs>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--border)"
            vertical={false}
          />
          <XAxis
            dataKey="index"
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
          />
          <Area
            type="monotone"
            dataKey="valence"
            stroke="var(--accent)"
            strokeWidth={2}
            fill="url(#valenceGradient)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
