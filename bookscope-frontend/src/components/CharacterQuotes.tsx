import { Quote } from "lucide-react";

interface CharacterQuotesProps {
  quotes: string[];
}

export default function CharacterQuotes({ quotes }: CharacterQuotesProps) {
  if (quotes.length === 0) return null;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Quote className="w-4 h-4 text-[var(--accent)]" />
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          经典语录
        </h2>
      </div>

      <div className="space-y-3">
        {quotes.map((q, i) => (
          <blockquote
            key={i}
            className="relative pl-4 border-l-2 border-[var(--accent)]/30"
          >
            <p className="text-sm text-[var(--text)] leading-relaxed italic">
              &ldquo;{q}&rdquo;
            </p>
          </blockquote>
        ))}
      </div>
    </div>
  );
}
