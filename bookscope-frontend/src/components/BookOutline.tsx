import { BookOpen, Layers } from "lucide-react";
import type { ThemeAnalysis } from "../lib/types";

interface BookOutlineProps {
  outline: string;
  themes?: ThemeAnalysis[];
  /** Legacy fallback: simple string summary when outline not yet available */
  legacySummary?: string;
  legacyThemes?: string[];
}

export default function BookOutline({
  outline,
  themes,
  legacySummary,
  legacyThemes,
}: BookOutlineProps) {
  const displayText = outline || legacySummary || "";
  if (!displayText) return null;

  const hasDeepThemes = themes && themes.length > 0;
  const displayThemes = hasDeepThemes
    ? themes
    : (legacyThemes ?? []).map((t) => ({ theme: t, description: "" }));

  return (
    <div className="ink-card bg-[var(--surface)] border border-[var(--border)] rounded-xl p-6">
      <div className="flex items-center gap-2 mb-4">
        <BookOpen className="w-5 h-5 text-[var(--accent)]" />
        <h2 className="text-2xl text-[var(--accent)]">
          {outline ? "全书大纲" : "摘要"}
        </h2>
      </div>

      {/* Outline / summary text */}
      <div className="text-[var(--text)] leading-loose text-sm whitespace-pre-line mb-6">
        {displayText}
      </div>

      {/* Themes */}
      {displayThemes.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Layers className="w-4 h-4 text-[var(--accent)]" />
            <h3 className="text-lg text-[var(--accent)]">核心主题</h3>
          </div>
          {hasDeepThemes ? (
            <div className="space-y-3">
              {themes!.map((t) => (
                <div
                  key={t.theme}
                  className="bg-[var(--bg)] border border-[var(--border)] rounded-lg px-4 py-3"
                >
                  <h4 className="text-sm font-medium text-[var(--accent)] mb-1">
                    {t.theme}
                  </h4>
                  <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                    {t.description}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {displayThemes.map((t) => (
                <span
                  key={t.theme}
                  className="px-2.5 py-1 text-xs rounded-full bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/20"
                >
                  {t.theme}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
