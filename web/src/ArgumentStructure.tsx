// ---------------------------------------------------------------------------
// ArgumentStructure — 论点结构梳理（学习者发明区，功能队列第 2 个）
//
// 点"梳理论点"→ 调 /api/agent/argument-structure（整本进上下文拆论证骨架）→ 编号论点卡。
// 每条 = 朱批主张 + 原文为证（带章号 + 核验过盖钤印）。沿用评点排版 + SealMark。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

interface Claim {
  order: number;
  claim: string;
  chapter: number;
  evidence: string;
  verified?: boolean;
}

interface ArgumentStructureProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export function ArgumentStructure({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: ArgumentStructureProps) {
  const [claims, setClaims] = useState<Claim[] | null>(null);
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
      const resp = await fetch("/api/agent/argument-structure", {
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
        claims: Claim[];
        scanned: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      setScanned(data.scanned);
      setClaims(data.claims);
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
          拆这本书的论证骨架——作者主张了什么、靠什么撑，每条钉在原文。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="shrink-0 text-xs px-3 py-1.5 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "梳理中（约 1 分钟）…" : claims ? "重新梳理" : "梳理论点"}
        </button>
      </div>

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label="梳理论点结构" />}

      {!scanned && claims && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          这本书太大，暂不支持论点梳理。
        </p>
      )}

      {scanned && claims && claims.length === 0 && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          没梳理出明显的论点结构，稍后可重试。
        </p>
      )}

      {claims && claims.length > 0 && (
        <ol className="space-y-4">
          {claims.map((c, i) => (
            <li
              key={i}
              className="rounded-md border pl-4 pr-3 py-3"
              style={{
                borderColor: "var(--color-folio-edge)",
                background: "var(--color-paper-raised)",
              }}
            >
              <div className="flex items-baseline gap-2 mb-1.5">
                <span
                  className="text-xs shrink-0"
                  style={{ color: "var(--color-seal)" }}
                >
                  论点 {c.order}
                </span>
              </div>
              <div
                className="text-[15px] leading-relaxed text-[var(--color-ink)] mb-2"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {c.claim}
              </div>
              {c.evidence && (
                <div className="relative border-l-2 border-[var(--color-seal)]/40 pl-3 py-1">
                  <div className="text-xs text-[var(--color-ink-muted)] mb-1 flex items-center gap-1.5">
                    <span>第 {c.chapter} 章 · 原文为证</span>
                    {c.verified && <SealMark size={17} title="原文已核验" />}
                  </div>
                  <div
                    className="text-[13px] leading-relaxed text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {c.evidence}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}

      {claims && claims.length > 0 && !loading && (
        <RunStats trace={trace} note={`${claims.length} 条论点`} />
      )}
    </div>
  );
}
