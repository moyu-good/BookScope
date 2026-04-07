import { ThumbsUp, ThumbsDown } from "lucide-react";
import type { ReaderVerdict } from "../lib/types";

interface VerdictCardProps {
  verdict: ReaderVerdict;
}

export default function VerdictCard({ verdict }: VerdictCardProps) {
  const lowConfidence = verdict.confidence < 0.3;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-5 border-l-4 border-l-[var(--accent)]">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">
        读者判断
      </h2>

      <p className="text-[var(--text)] text-base font-medium leading-relaxed mb-4">
        {verdict.sentence}
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* For you */}
        <div className="flex gap-2.5">
          <ThumbsUp className="w-4 h-4 text-[var(--trust)] shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-medium text-[var(--trust)] mb-1">
              适合你如果...
            </p>
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
              {verdict.for_you}
            </p>
          </div>
        </div>

        {/* Not for you */}
        <div className="flex gap-2.5">
          <ThumbsDown className="w-4 h-4 text-[var(--anger)] shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-medium text-[var(--anger)] mb-1">
              不太适合如果...
            </p>
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
              {verdict.not_for_you}
            </p>
          </div>
        </div>
      </div>

      {lowConfidence && (
        <p className="mt-4 text-xs text-[var(--text-secondary)] italic bg-[var(--bg)] rounded-lg px-3 py-2">
          低置信度 — 此判断基于有限的文本信号，可能未能完全反映本书的吸引力。
        </p>
      )}
    </div>
  );
}
