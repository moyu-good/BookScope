import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  ResponsiveContainer,
} from "recharts";
import type { EmotionScore } from "../lib/api";
import { EMOTION_FIELDS, EMOTION_HEX, EMOTION_LABELS } from "../lib/constants";

interface EmotionRadarProps {
  emotionScores: EmotionScore[];
}

export default function EmotionRadar({ emotionScores }: EmotionRadarProps) {
  if (!emotionScores.length) return null;

  const n = emotionScores.length;
  const data = EMOTION_FIELDS.map((field) => ({
    emotion: EMOTION_LABELS[field],
    value: emotionScores.reduce((sum, s) => sum + s[field], 0) / n,
  }));

  return (
    <div className="bg-[var(--bs-surface)] rounded-2xl border border-[var(--bs-border)] p-6">
      <h3 className="text-sm font-medium text-[var(--bs-text-muted)] mb-4 uppercase tracking-wider">
        Emotional DNA
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        <RadarChart data={data}>
          <PolarGrid stroke="var(--bs-border)" />
          <PolarAngleAxis
            dataKey="emotion"
            tick={{ fontSize: 11, fill: "var(--bs-text-muted)" }}
          />
          <Radar
            dataKey="value"
            stroke={EMOTION_HEX.trust}
            fill={EMOTION_HEX.trust}
            fillOpacity={0.15}
            strokeWidth={2}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}
