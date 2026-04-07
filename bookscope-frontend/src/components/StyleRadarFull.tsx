import { useEffect, useState } from "react";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { fetchStyleRadar, type StyleRadarData } from "../lib/api";

interface StyleRadarFullProps {
  sessionId: string;
}

const STYLE_LABELS: Record<string, string> = {
  avg_sentence_length: "Sentence Length",
  ttr: "Vocabulary Richness",
  noun_ratio: "Noun Density",
  verb_ratio: "Verb Density",
  adj_ratio: "Adjective Use",
  adv_ratio: "Adverb Use",
};

const STYLE_DESCRIPTIONS: Record<string, string> = {
  avg_sentence_length: "Average words per sentence (normalized to 0-1 where 30+ = 1.0)",
  ttr: "Type-Token Ratio — vocabulary diversity",
  noun_ratio: "Proportion of nouns in text",
  verb_ratio: "Proportion of verbs in text",
  adj_ratio: "Proportion of adjectives in text",
  adv_ratio: "Proportion of adverbs in text",
};

export default function StyleRadarFull({ sessionId }: StyleRadarFullProps) {
  const [data, setData] = useState<StyleRadarData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchStyleRadar(sessionId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [sessionId]);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (!data) return <p className="text-sm text-[var(--bs-text-muted)]">Loading style data...</p>;

  const chartData = Object.entries(data.metrics).map(([key, value]) => ({
    metric: STYLE_LABELS[key] ?? key,
    value: key === "avg_sentence_length" ? Math.min(1, value / 30) : value,
    raw: value,
    description: STYLE_DESCRIPTIONS[key] ?? "",
  }));

  return (
    <div className="bg-[var(--bs-surface)] rounded-2xl border border-[var(--bs-border)] p-6">
      <h3 className="text-sm font-medium text-[var(--bs-text-muted)] mb-4 uppercase tracking-wider">
        Writing Style Profile
      </h3>

      <ResponsiveContainer width="100%" height={320}>
        <RadarChart data={chartData}>
          <PolarGrid stroke="var(--bs-border)" />
          <PolarAngleAxis
            dataKey="metric"
            tick={{ fontSize: 10, fill: "var(--bs-text-muted)" }}
          />
          <PolarRadiusAxis
            tick={{ fontSize: 9, fill: "var(--bs-text-muted)" }}
            axisLine={false}
            domain={[0, 1]}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--bs-surface)",
              border: "1px solid var(--bs-border)",
              borderRadius: "8px",
              fontSize: "11px",
            }}
            formatter={(value: number, _name: string, entry: { payload: { raw: number; description: string } }) => [
              `${entry.payload.raw.toFixed(4)}`,
              entry.payload.description,
            ]}
          />
          <Radar
            dataKey="value"
            stroke="var(--bs-accent)"
            fill="var(--bs-accent)"
            fillOpacity={0.15}
            strokeWidth={2}
          />
        </RadarChart>
      </ResponsiveContainer>

      {/* Raw metrics table */}
      <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-3">
        {Object.entries(data.metrics).map(([key, value]) => (
          <div key={key} className="text-center">
            <div className="text-lg font-light text-[var(--bs-text)]">
              {key === "avg_sentence_length" ? value.toFixed(1) : value.toFixed(3)}
            </div>
            <div className="text-[10px] text-[var(--bs-text-muted)]">
              {STYLE_LABELS[key] ?? key}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
