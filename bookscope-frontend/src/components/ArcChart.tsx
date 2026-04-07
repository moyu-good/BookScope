import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

interface ArcChartProps {
  valenceSeries: number[];
  arcPattern: string;
}

export default function ArcChart({ valenceSeries, arcPattern }: ArcChartProps) {
  if (!valenceSeries.length) return null;

  const data = valenceSeries.map((v, i) => ({
    index: i,
    valence: v,
  }));

  return (
    <div className="bg-[var(--bs-surface)] rounded-2xl border border-[var(--bs-border)] p-6">
      <h3 className="text-sm font-medium text-[var(--bs-text-muted)] mb-1 uppercase tracking-wider">
        Story Shape
      </h3>
      <p className="text-xs text-[var(--bs-text-muted)] mb-4">{arcPattern}</p>
      <ResponsiveContainer width="100%" height={250}>
        <AreaChart data={data}>
          <defs>
            <linearGradient id="valenceGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--bs-joy)" stopOpacity={0.3} />
              <stop offset="50%" stopColor="var(--bs-trust)" stopOpacity={0.05} />
              <stop offset="100%" stopColor="var(--bs-sadness)" stopOpacity={0.3} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="index"
            tick={false}
            axisLine={{ stroke: "var(--bs-border)" }}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "var(--bs-text-muted)" }}
            axisLine={false}
            tickLine={false}
            width={30}
          />
          <ReferenceLine y={0} stroke="var(--bs-border)" strokeDasharray="3 3" />
          <Area
            type="monotone"
            dataKey="valence"
            stroke="var(--bs-accent)"
            strokeWidth={2}
            fill="url(#valenceGrad)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
