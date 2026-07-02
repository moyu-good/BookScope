// ---------------------------------------------------------------------------
// WritingTechnique — 写作手法分析（学习者发明区，功能队列第 7 个）
//
// 点"分析手法"→ 调 /api/agent/writing-technique（整本分析作者怎么写）→ 手法卡。
// 每条 = 手法名 + 怎么用 + 原文例子（带章号 + 核验过盖钤印）。沿用评点卡 + SealMark。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

interface Technique {
  order: number;
  technique: string;
  how: string;
  chapter: number;
  snippet: string;
  verified?: boolean;
}

interface WritingTechniqueProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export function WritingTechnique({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: WritingTechniqueProps) {
  const [techniques, setTechniques] = useState<Technique[] | null>(null);
  const [scanned, setScanned] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/writing-technique", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const j = (await resp.json().catch(() => null)) as
          | { detail?: { message?: string } }
          | null;
        throw new Error(j?.detail?.message ?? `请求失败（${resp.status}）`);
      }
      const data = (await resp.json()) as {
        techniques: Technique[];
        scanned: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      setScanned(data.scanned);
      setTechniques(data.techniques);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed pr-4">
          看作者怎么写：论证 / 结构 / 铺陈 / 用语的手法，每条配原文例子。学手艺。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="shrink-0 text-xs px-3 py-1.5 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading
            ? "分析中（约 1 分钟）…"
            : techniques
              ? "重新分析"
              : "分析手法"}
        </button>
      </div>

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label="分析全书写作手法" />}

      {!scanned && techniques && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          这本书太大，暂不支持写作手法分析。
        </p>
      )}

      {scanned && techniques && techniques.length === 0 && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          没分析出可锚到原文的显著手法，稍后可重试。
        </p>
      )}

      {techniques && techniques.length > 0 && (
        <ol className="space-y-4">
          {techniques.map((t, i) => (
            <li
              key={i}
              className="rounded-md border pl-4 pr-3 py-3"
              style={{
                borderColor: "var(--color-folio-edge)",
                background: "var(--color-paper-raised)",
              }}
            >
              <div
                className="text-body text-[var(--color-ink)] mb-1"
                style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
              >
                {t.technique}
              </div>
              {t.how && (
                <div className="text-body-sm text-[var(--color-ink-muted)] leading-relaxed mb-2">
                  {t.how}
                </div>
              )}
              {t.snippet && (
                <div className="relative border-l-2 border-[var(--color-seal)]/40 pl-3 py-1">
                  <div className="text-xs text-[var(--color-ink-muted)] mb-1 flex items-center gap-1.5">
                    <span>第 {t.chapter} 章 · 原文例子</span>
                    {t.verified && <SealMark size={17} title="原文已核验" />}
                  </div>
                  <div
                    className="text-body-sm leading-relaxed text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {t.snippet}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}

      {techniques && techniques.length > 0 && !loading && (
        <RunStats trace={trace} note={`${techniques.length} 种手法`} />
      )}
    </div>
  );
}
