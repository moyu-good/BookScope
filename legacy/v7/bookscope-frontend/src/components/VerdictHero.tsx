import { useMemo } from "react";
import type { ReaderVerdict } from "../lib/types";

interface VerdictHeroProps {
  verdict: ReaderVerdict;
  bookTitle?: string;
}

/**
 * Hero-first verdict card — Song Edition (宋版刻本) theme.
 * Top archival metadata strip · Drop Cap headline · For/Not-for twin columns ·
 * Upright imperial seal mark with archive number.
 * Sits at top of OverviewPage, unfoldable, visually dominant.
 */
export default function VerdictHero({ verdict, bookTitle }: VerdictHeroProps) {
  const lowConfidence = verdict.confidence < 0.3;

  // Archive date — pure presentation, formatted like a published masthead.
  const archiveDate = useMemo(() => {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}.${m}.${day}`;
  }, []);

  const title = bookTitle || "御览";

  return (
    <section
      className="relative w-full"
      style={{
        background: "var(--parchment)",
        paddingTop: "clamp(48px, 8vw, 96px)",
        paddingBottom: "clamp(40px, 6vw, 72px)",
        paddingLeft: "clamp(24px, 6vw, 96px)",
        paddingRight: "clamp(24px, 6vw, 96px)",
      }}
    >
      <div className="max-w-4xl">
        {/* ── Archival metadata strip ────────────────────── */}
        <div className="flex items-center gap-5 pb-4 mb-10 border-b border-[var(--border)]">
          <span className="seal-stamp-large">御览</span>
          <span className="archive-label">{title}</span>
          <span className="flex-1" />
          <span className="archive-number">{archiveDate}</span>
          <span className="archive-number">№ 一</span>
        </div>

        {/* ── Headline with drop cap ───────────────────── */}
        <h1
          className="drop-cap"
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: 500,
            fontSize: "clamp(26px, 4.5vw, 44px)",
            lineHeight: 1.3,
            letterSpacing: "0.005em",
            color: "var(--parchment-text)",
            marginBottom: "2.5rem",
          }}
        >
          {verdict.sentence}
        </h1>

        {/* ── Thin editorial rule ─────────────────── */}
        <div
          aria-hidden
          className="mb-8"
          style={{ height: 1, background: "var(--fold-line)" }}
        />

        {/* ── For you / Not for you — minimal twin column ── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-10 md:gap-16">
          <div>
            <p className="archive-label mb-3" style={{ color: "var(--trust)" }}>
              适合你
            </p>
            <p
              className="text-sm leading-[1.85]"
              style={{
                color: "var(--parchment-text)",
                fontFamily: "var(--font-body)",
              }}
            >
              {verdict.for_you}
            </p>
          </div>
          <div>
            <p className="archive-label mb-3">不适合</p>
            <p
              className="text-sm leading-[1.85]"
              style={{
                color: "var(--parchment-text-secondary)",
                fontFamily: "var(--font-body)",
              }}
            >
              {verdict.not_for_you}
            </p>
          </div>
        </div>

        {lowConfidence && (
          <p
            className="mt-10 text-[11px] italic max-w-2xl"
            style={{ color: "var(--parchment-text-secondary)" }}
          >
            * 低置信度 · 基于有限文本信号。下方证据章节可能更准确。
          </p>
        )}
      </div>
    </section>
  );
}
