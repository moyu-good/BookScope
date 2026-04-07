import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { fetchTimeline, type TimelineData } from "../lib/api";
import { EMOTION_HEX } from "../lib/constants";

interface EmotionTimelineProps {
  sessionId: string;
}

const VISIBLE_EMOTIONS = [
  "joy", "sadness", "anger", "fear", "trust", "surprise",
] as const;

export default function EmotionTimeline({ sessionId }: EmotionTimelineProps) {
  const [data, setData] = useState<TimelineData | null>(null);
  const [error, setError] = useState("");
  const [active, setActive] = useState<Set<string>>(new Set(VISIBLE_EMOTIONS));

  useEffect(() => {
    fetchTimeline(sessionId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [sessionId]);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (!data) return <p className="text-sm text-[var(--bs-text-muted)]">Loading timeline...</p>;

  const chartData = data.chunk_indices.map((idx, i) => {
    const point: Record<string, number> = { chunk: idx + 1 };
    for (const [emotion, values] of Object.entries(data.series)) {
      point[emotion] = values[i];
    }
    return point;
  });

  const toggle = (emotion: string) => {
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(emotion)) next.delete(emotion);
      else next.add(emotion);
      return next;
    });
  };

  return (
    <div className="bg-[var(--bs-surface)] rounded-2xl border border-[var(--bs-border)] p-6">
      <h3 className="text-sm font-medium text-[var(--bs-text-muted)] mb-2 uppercase tracking-wider">
        Emotion Timeline
      </h3>

      {/* Toggle buttons */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        {Object.keys(data.series).map((emotion) => (
          <button
            key={emotion}
            onClick={() => toggle(emotion)}
            className={`text-[10px] px-2 py-0.5 rounded-full transition-all capitalize ${
              active.has(emotion)
                ? "text-white"
                : "text-[var(--bs-text-muted)] bg-[var(--bs-border)]"
            }`}
            style={active.has(emotion) ? {
              backgroundColor: EMOTION_HEX[emotion as keyof typeof EMOTION_HEX] ?? "#6366f1",
            } : undefined}
          >
            {emotion}
          </button>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData}>
          <XAxis
            dataKey="chunk"
            tick={{ fontSize: 10, fill: "var(--bs-text-muted)" }}
            axisLine={{ stroke: "var(--bs-border)" }}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "var(--bs-text-muted)" }}
            axisLine={false}
            tickLine={false}
            width={35}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--bs-surface)",
              border: "1px solid var(--bs-border)",
              borderRadius: "8px",
              fontSize: "11px",
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: "10px" }}
            onClick={(e) => toggle(e.dataKey as string)}
          />
          {Object.keys(data.series).map((emotion) => (
            active.has(emotion) && (
              <Line
                key={emotion}
                type="monotone"
                dataKey={emotion}
                stroke={EMOTION_HEX[emotion as keyof typeof EMOTION_HEX] ?? "#6366f1"}
                strokeWidth={1.5}
                dot={false}
                name={emotion}
              />
            )
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
