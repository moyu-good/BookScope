// ---------------------------------------------------------------------------
// ArgumentStructure — 论证骨架树（理论书，probe exp034 GO）
//
// 点"梳理论点"→ 调 /api/agent/argument-tree（整本长上下文拆论证骨架）→ 中心论点根卡 +
// 论点树。旧版是平铺朱砂编号竖脊清单（看着像时间轴、不表达结构），改成:
//   · 顶上一张**中心论点(主脉)**根卡（朱边、评点体、带原文钤印）;
//   · 下面按 supports 关系建树——撑中心论点的挂一级、撑某条论点的嵌它下面（缩进折线）;
//     同一层按逻辑角色阅读序排（前提→支撑→递进→反驳→论据→结论）。
//   · 每条论点带角色标签 + 原文引证（核过盖鉴印、没核到标待核）。
// 拓扑平（论点都并列撑主脉）时也读得出论证推进（靠角色序 + 主脉根卡），不回退成流水清单。
// ---------------------------------------------------------------------------

import { type ReactNode, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { SealButton } from "./SealButton";

interface TreeClaim {
  id: string;
  claim: string;
  role: string;
  supports: string;
  quote: string;
  quote_verified: boolean;
  chapter: number;
  brief: string;
}
interface Thesis {
  claim: string;
  quote: string;
  quote_verified: boolean;
  chapter: number;
  from_book: string;
}
interface TreeResult {
  scanned: boolean;
  thesis: Thesis | null;
  claims: TreeClaim[];
}

interface ArgumentStructureProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 逻辑角色阅读序：一层论点按这个排，读起来是「立前提→撑→递进→反驳→举据→收结论」的推进。
const ROLE_ORDER = ["中心", "前提", "支撑", "递进", "反驳", "论据", "结论"];

// 角色标签配色：反驳 = 对立(墨蓝冷),其余 = 支撑系(朱)。只分「撑 / 反」,不彩虹。
function roleTone(role: string): { bg: string; fg: string } {
  if (role === "反驳") {
    return { bg: "color-mix(in oklch, #2E6B82 14%, var(--color-paper))", fg: "#2E6B82" };
  }
  return { bg: "var(--color-seal-soft)", fg: "var(--color-seal)" };
}

// claim 综括跟原文近乎一字不差时，原文区不复读，只留章号 + 鉴印（同旧版 #47 判据）。
function echoesEvidence(claim: string, evidence: string): boolean {
  const norm = (s: string) => s.trim().replace(/[。;；,，、"「」“”'']+/gu, "");
  const c = norm(claim);
  const e = norm(evidence);
  if (!c || !e) return false;
  if (c === e) return true;
  return c.length >= 8 && (e.includes(c) || c.includes(e));
}

function SourceLine({
  chapter,
  quote,
  verified,
  claim,
}: {
  chapter: number;
  quote: string;
  verified: boolean;
  claim: string;
}) {
  if (!quote) return null;
  const echo = echoesEvidence(claim, quote);
  const badge = verified ? (
    <SealMark size={16} title="原文已核验" />
  ) : (
    <span className="text-[10px] px-1 rounded border border-[var(--color-rule)]">待核</span>
  );
  if (echo) {
    return (
      <div className="mt-1 text-xs text-[var(--color-ink-muted)] flex items-center gap-1.5">
        <span>第 {chapter} 章 · 原文同上</span>
        {badge}
      </div>
    );
  }
  return (
    <div
      className="mt-1.5 border-l-2 pl-3 py-1"
      style={{ borderColor: "color-mix(in oklch, var(--color-seal) 40%, transparent)" }}
    >
      <div className="text-xs text-[var(--color-ink-muted)] mb-1 flex items-center gap-1.5">
        <span>第 {chapter} 章 · 原文为证</span>
        {badge}
      </div>
      <blockquote
        className="text-body-sm leading-relaxed text-[var(--color-ink)]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        {quote}
      </blockquote>
    </div>
  );
}

export function ArgumentStructure({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: ArgumentStructureProps) {
  const [result, setResult] = useState<TreeResult | null>(null);
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
      const resp = await fetch("/api/agent/argument-tree", {
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
      const d = (await resp.json()) as TreeResult & { trace?: RunTrace };
      setTrace(d.trace ?? null);
      setResult({
        scanned: Boolean(d.scanned),
        thesis: d.thesis ?? null,
        claims: d.claims ?? [],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  // 空态（还没梳理）：统一入口卡
  if (!result) {
    return (
      <FeatureEntryCard
        title="论点结构"
        lead="拆这本书的论证骨架：中心论点是什么、下面靠哪些论点撑，每条钉在原文。"
        actionLabel="梳理论点"
        loadingLabel="梳理中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书拆论证骨架，约 1 分钟；命中缓存秒出"
        error={error}
      >
        {loading && <RunningProcess label="梳理论证骨架" />}
      </FeatureEntryCard>
    );
  }

  const { scanned, thesis, claims } = result;
  const empty = !scanned || !thesis || claims.length === 0;

  // 建树：每条论点归到它 supports 的父桶（指向不存在的 id / 自指 → 挂 thesis）；每桶按角色阅读序排。
  const childrenOf = new Map<string, TreeClaim[]>();
  const ids = new Set(claims.map((c) => c.id));
  for (const c of claims) {
    const parent = c.supports !== c.id && ids.has(c.supports) ? c.supports : "thesis";
    const arr = childrenOf.get(parent);
    if (arr) arr.push(c);
    else childrenOf.set(parent, [c]);
  }
  const byRole = (a: TreeClaim, b: TreeClaim) => {
    const ra = ROLE_ORDER.indexOf(a.role);
    const rb = ROLE_ORDER.indexOf(b.role);
    return (ra < 0 ? 99 : ra) - (rb < 0 ? 99 : rb);
  };
  for (const arr of childrenOf.values()) arr.sort(byRole);

  // 一级 = 撑中心论点的。防环兜底：万一没有任何论点挂到 thesis（互指成环），全平铺当一级。
  let roots = childrenOf.get("thesis") ?? [];
  if (roots.length === 0 && claims.length > 0) roots = [...claims].sort(byRole);

  function renderClaim(c: TreeClaim, depth: number, visited: Set<string>): ReactNode {
    if (visited.has(c.id) || depth > 4) return null;
    visited.add(c.id);
    const kids = childrenOf.get(c.id) ?? [];
    const tone = roleTone(c.role);
    return (
      <div key={c.id} className="mt-2.5" style={{ animation: "arg-rise .4s ease-out" }}>
        <div className="flex items-start gap-2">
          <span className="arg-elbow" aria-hidden />
          <div className="flex-1 rounded-md border border-[var(--color-rule)] bg-[var(--color-paper-raised)] px-3 py-2.5">
            <span
              className="inline-block text-xs px-2 py-0.5 rounded-full mb-1"
              style={{ background: tone.bg, color: tone.fg }}
            >
              {c.role}
            </span>
            <div
              className="text-body text-[var(--color-ink)] leading-relaxed"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {c.claim}
            </div>
            <SourceLine
              chapter={c.chapter}
              quote={c.quote}
              verified={c.quote_verified}
              claim={c.claim}
            />
          </div>
        </div>
        {kids.length > 0 && (
          <div className="ml-3 pl-3 border-l border-dashed border-[var(--color-rule)]">
            {kids.map((k) => renderClaim(k, depth + 1, visited))}
          </div>
        )}
      </div>
    );
  }

  const visited = new Set<string>();

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed pr-4">
          拆这本书的论证骨架：中心论点是什么、下面靠哪些论点撑，每条钉在原文。
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
        <p className="text-sm mb-2" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label="梳理论证骨架" />}

      {!loading && empty && (
        <div className="rounded border border-dashed border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-5 text-sm text-[var(--color-ink-muted)] leading-relaxed">
          这本书没梳理出明显的论证骨架。论点结构是给理论 / 论述类书准备的：拆出中心论点、看下面靠哪些论点撑。叙事类的书没有这种骨架，稍后也可换本再试。
        </div>
      )}

      {!loading && !empty && thesis && (
        <>
          <style>{`.arg-elbow{flex:0 0 auto;width:14px;height:2px;background:var(--color-rule);margin-top:20px}
@keyframes arg-rise{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}`}</style>

          {/* 中心论点根卡（全书主脉） */}
          <div
            className="rounded-lg border-2 px-4 py-3"
            style={{
              borderColor: "color-mix(in oklch, var(--color-seal) 55%, transparent)",
              background: "var(--color-seal-soft)",
              animation: "arg-rise .4s ease-out",
            }}
          >
            <div className="text-xs mb-1" style={{ color: "var(--color-seal)" }}>
              全书主脉 · 中心论点
            </div>
            <div
              className="text-base font-bold text-[var(--color-ink)] leading-relaxed"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {thesis.claim}
            </div>
            <SourceLine
              chapter={thesis.chapter}
              quote={thesis.quote}
              verified={thesis.quote_verified}
              claim={thesis.claim}
            />
            {thesis.from_book && (
              <p className="mt-1.5 text-xs text-[var(--color-ink-muted)] leading-relaxed">
                依据本书原文：{thesis.from_book}
              </p>
            )}
          </div>

          {/* 论点树：撑主脉的挂一级，撑某条论点的嵌它下面 */}
          <div className="mt-1 ml-3 pl-3 border-l border-[var(--color-rule)]">
            {roots.map((c) => renderClaim(c, 0, visited))}
          </div>

          <p className="mt-3 text-xs text-[var(--color-ink-muted)] leading-relaxed">
            顶上是全书主脉，下面每条论点标了它在论证里的角色（前提、支撑、论据、反驳、结论），撑着谁；每条都钉在原文，核验过盖「鉴」印，没核到标「待核」。
          </p>
        </>
      )}

      {!loading && !empty && <RunStats trace={trace} note={`${claims.length} 条论点`} />}
    </div>
  );
}
