import { useEffect, useState } from "react";
import { fetchHeatmap, type HeatmapData } from "../lib/api";
import { EMOTION_HEX } from "../lib/constants";

interface EmotionHeatmapProps {
  sessionId: string;
}

const EMOTION_ORDER = [
  "anger", "anticipation", "disgust", "fear",
  "joy", "sadness", "surprise", "trust",
] as const;

function intensityColor(value: number, emotion: string): string {
  const hex = EMOTION_HEX[emotion as keyof typeof EMOTION_HEX] ?? "#6366f1";
  const alpha = Math.max(0.05, Math.min(0.9, value));
  return `${hex}${Math.round(alpha * 255).toString(16).padStart(2, "0")}`;
}

export default function EmotionHeatmap({ sessionId }: EmotionHeatmapProps) {
  const [data, setData] = useState<HeatmapData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchHeatmap(sessionId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [sessionId]);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (!data) return <p className="text-sm text-[var(--bs-text-muted)]">Loading heatmap...</p>;

  const maxChunks = 60;
  const step = data.matrix.length > maxChunks ? Math.ceil(data.matrix.length / maxChunks) : 1;
  const sampled = data.matrix.filter((_, i) => i % step === 0);
  const sampledLabels = data.chunk_labels.filter((_, i) => i % step === 0);

  return (
    <div className="bg-[var(--bs-surface)] rounded-2xl border border-[var(--bs-border)] p-6">
      <h3 className="text-sm font-medium text-[var(--bs-text-muted)] mb-4 uppercase tracking-wider">
        Emotion Heatmap
      </h3>

      <div className="overflow-x-auto">
        <div className="min-w-[500px]">
          {/* Header row */}
          <div className="flex gap-0.5 mb-1">
            <div className="w-16 flex-shrink-0" />
            {sampledLabels.map((label, i) => (
              <div
                key={i}
                className="flex-1 text-[8px] text-[var(--bs-text-muted)] text-center truncate"
                title={label}
              >
                {i % Math.max(1, Math.floor(sampledLabels.length / 8)) === 0 ? label.replace("Chunk ", "") : ""}
              </div>
            ))}
          </div>

          {/* Rows */}
          {EMOTION_ORDER.map((emotion, ei) => (
            <div key={emotion} className="flex gap-0.5 mb-0.5">
              <div className="w-16 flex-shrink-0 text-[10px] text-[var(--bs-text-muted)] text-right pr-2 leading-5 capitalize">
                {emotion}
              </div>
              {sampled.map((row, ci) => (
                <div
                  key={ci}
                  className="flex-1 h-5 rounded-sm"
                  style={{ backgroundColor: intensityColor(row[ei], emotion) }}
                  title={`${emotion}: ${row[ei].toFixed(3)} (${sampledLabels[ci]})`}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2 mt-3 justify-end">
        <span className="text-[10px] text-[var(--bs-text-muted)]">Low</span>
        <div className="flex gap-0.5">
          {[0.1, 0.25, 0.4, 0.6, 0.8].map((v) => (
            <div
              key={v}
              className="w-4 h-3 rounded-sm"
              style={{ backgroundColor: `rgba(99, 102, 241, ${v})` }}
            />
          ))}
        </div>
        <span className="text-[10px] text-[var(--bs-text-muted)]">High</span>
      </div>
    </div>
  );
}
