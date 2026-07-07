// ---------------------------------------------------------------------------
// ArgumentStructure — 论点结构梳理（学习者发明区，功能队列第 2 个）
//
// 点"梳理论点"→ 调 /api/agent/argument-structure（整本进上下文拆论证骨架）→ 编号论点卡。
// 每条 = 朱批主张 + 原文为证（带章号 + 核验过盖钤印）。沿用评点排版 + SealMark。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { SealButton } from "./SealButton";

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

// #47 复读:主张(claim)跟「原文为证」(evidence)近乎一字不差时,原文区不再抄一遍——
// 只留章号 + 鉴印(核验凭据不丢)。跟办事清单 sameAsTitle 同一套判据:去首尾标点/空白后比,
// 够长(≥8 字)时一方含另一方也算同。(argument-mining 抽的 claim 常是原句复述,故常命中。)
function claimEchoesEvidence(claim: string, evidence: string): boolean {
  const norm = (s: string) => s.trim().replace(/[。;；,，、"「」""'']+/gu, "");
  const c = norm(claim);
  const e = norm(evidence);
  if (!c || !e) return false;
  if (c === e) return true;
  return c.length >= 8 && (e.includes(c) || c.includes(e));
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

  // 空态（还没梳理）：统一入口卡（视觉表现根治 · FeatureEntryCard）
  if (!claims) {
    return (
      <FeatureEntryCard
        title="论点结构"
        lead="拆这本书的论证骨架：作者主张了什么、靠什么撑，每条钉在原文。"
        actionLabel="梳理论点"
        loadingLabel="梳理中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书拆论证，约 1 分钟；命中缓存秒出"
        error={error}
      >
        {loading && <RunningProcess label="梳理论点结构" />}
      </FeatureEntryCard>
    );
  }

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed pr-4">
          拆这本书的论证骨架：作者主张了什么、靠什么撑，每条钉在原文。
        </p>
        <SealButton
          size="sm"
          label="重新梳理"
          loadingLabel="梳理中…"
          loading={loading}
          onClick={load}
          className="shrink-0"
        />
      </div>

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label="梳理论点结构" />}

      {!scanned && claims && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          论点结构没读出来，稍后重试。
        </p>
      )}

      {scanned && claims && claims.length === 0 && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          没梳理出明显的论点结构，稍后可重试。
        </p>
      )}

      {claims && claims.length > 0 && (
        <ol
          className="relative space-y-4 ml-3 pl-7 border-l-2"
          style={{ borderColor: "color-mix(in srgb, var(--color-seal) 25%, transparent)" }}
        >
          <style>{`@keyframes arg-flow{from{opacity:0;transform:translateX(-4px)}to{opacity:1;transform:none}}`}</style>
          {claims.map((c, i) => (
            <li
              key={i}
              className="relative rounded-md border pl-4 pr-3 py-3"
              style={{
                borderColor: "var(--color-folio-edge)",
                background: "var(--color-paper-raised)",
                animation: "arg-flow .5s ease-out",
              }}
            >
              {/* 脉络节点：朱砂序号圈坐在脊线上,论证一脉相承 */}
              <span
                className="absolute top-3 w-6 h-6 rounded-full flex items-center justify-center text-caption"
                style={{ left: "-2.45rem", background: "var(--color-seal)", color: "var(--color-paper)" }}
                aria-hidden
              >
                {c.order}
              </span>
              <div
                className="text-body leading-relaxed text-[var(--color-ink)] mb-2"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {c.claim}
              </div>
              {c.evidence && (
                <div className="relative border-l-2 border-[var(--color-seal)]/40 pl-3 py-1">
                  <div className="text-xs text-[var(--color-ink-muted)] mb-1 flex items-center gap-1.5">
                    {/* claim≈原文 → 标「原文同上」不复读;不同 → 「原文为证」显全文 */}
                    <span>
                      第 {c.chapter} 章 ·{" "}
                      {claimEchoesEvidence(c.claim, c.evidence) ? "原文同上" : "原文为证"}
                    </span>
                    {c.verified && <SealMark size={17} title="原文已核验" />}
                  </div>
                  {!claimEchoesEvidence(c.claim, c.evidence) && (
                    <div
                      className="text-body-sm leading-relaxed text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {c.evidence}
                    </div>
                  )}
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
