import { BookOpen } from "lucide-react";
import type { ReadabilityInfo, ReaderVerdict } from "../lib/api";
import { EMOTION_HEX, EMOTION_LABELS } from "../lib/constants";

interface VerdictCardProps {
  verdict: ReaderVerdict;
  readability: ReadabilityInfo;
  arcPattern: string;
  dominantEmotion: string;
}

export default function VerdictCard({
  verdict,
  readability,
  arcPattern,
  dominantEmotion,
}: VerdictCardProps) {
  const emotionColor = EMOTION_HEX[dominantEmotion] ?? "#7c3aed";
  const emotionLabel = EMOTION_LABELS[dominantEmotion] ?? dominantEmotion;

  return (
    <div className="bg-[var(--bs-surface)] rounded-2xl border border-[var(--bs-border)] p-6 space-y-4">
      {/* Main verdict sentence */}
      <div className="flex items-start gap-4">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: `${emotionColor}15` }}
        >
          <BookOpen className="w-5 h-5" style={{ color: emotionColor }} strokeWidth={1.5} />
        </div>
        <div>
          <p className="text-lg leading-relaxed text-[var(--bs-text)]">
            {verdict.sentence || "Analysis complete."}
          </p>
        </div>
      </div>

      {/* Meta chips */}
      <div className="flex flex-wrap gap-2">
        <Chip label={arcPattern} />
        <Chip label={emotionLabel} color={emotionColor} />
        <Chip label={readability.label} />
      </div>

      {/* For you / Not for you */}
      {(verdict.for_you || verdict.not_for_you) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
          {verdict.for_you && (
            <div className="text-sm">
              <span className="text-[var(--bs-trust)] font-medium">For you if:</span>{" "}
              <span className="text-[var(--bs-text-muted)]">{verdict.for_you}</span>
            </div>
          )}
          {verdict.not_for_you && (
            <div className="text-sm">
              <span className="text-[var(--bs-anger)] font-medium">Not for you if:</span>{" "}
              <span className="text-[var(--bs-text-muted)]">{verdict.not_for_you}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Chip({ label, color }: { label: string; color?: string }) {
  return (
    <span
      className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium border"
      style={{
        borderColor: color ? `${color}30` : "var(--bs-border)",
        color: color ?? "var(--bs-text-muted)",
        backgroundColor: color ? `${color}08` : "transparent",
      }}
    >
      {label}
    </span>
  );
}
