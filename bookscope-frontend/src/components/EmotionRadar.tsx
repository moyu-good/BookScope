import { useMemo } from "react";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  ResponsiveContainer,
} from "recharts";
import type { EmotionScore } from "../lib/types";
import { EMOTION_LABELS } from "../lib/constants";

interface EmotionRadarProps {
  emotionScores: EmotionScore[];
}

const EMOTION_KEYS = [
  "joy",
  "trust",
  "anticipation",
  "surprise",
  "fear",
  "sadness",
  "disgust",
  "anger",
] as const;

export default function EmotionRadar({ emotionScores }: EmotionRadarProps) {
  const chartData = useMemo(() => {
    if (emotionScores.length === 0) return [];

    const averages: Record<string, number> = {};
    for (const key of EMOTION_KEYS) {
      const sum = emotionScores.reduce(
        (acc, s) => acc + (s[key] as number),
        0,
      );
      averages[key] = sum / emotionScores.length;
    }

    return EMOTION_KEYS.map((key) => ({
      emotion: EMOTION_LABELS[key] ?? key,
      value: Math.round(averages[key] * 100) / 100,
    }));
  }, [emotionScores]);

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-4">
        情绪画像
      </h2>

      <ResponsiveContainer width="100%" height={280}>
        <RadarChart data={chartData} cx="50%" cy="50%" outerRadius="75%">
          <PolarGrid stroke="var(--border)" />
          <PolarAngleAxis
            dataKey="emotion"
            tick={{ fill: "var(--text-secondary)", fontSize: 11 }}
          />
          <Radar
            name="情绪"
            dataKey="value"
            stroke="var(--accent)"
            fill="var(--accent)"
            fillOpacity={0.2}
            strokeWidth={2}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}
