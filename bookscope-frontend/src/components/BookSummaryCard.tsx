import { BookOpen } from "lucide-react";

interface BookSummaryCardProps {
  summary: string;
  themes: string[];
}

export default function BookSummaryCard({
  summary,
  themes,
}: BookSummaryCardProps) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-5">
      <div className="flex items-center gap-2 mb-3">
        <BookOpen className="w-4 h-4 text-[var(--accent)]" />
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          摘要
        </h2>
      </div>

      <p className="text-[var(--text)] leading-relaxed text-sm whitespace-pre-line">
        {summary}
      </p>

      {themes.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-4">
          {themes.map((theme) => (
            <span
              key={theme}
              className="px-2.5 py-1 text-xs rounded-full bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/20"
            >
              {theme}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
