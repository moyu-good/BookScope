// ---------------------------------------------------------------------------
// NarrativePhases — 情节脉络·阶段带（懒生成，WP-narrative-phases）
//
// 点生成 → 调 /api/agent/narrative-phases（章脉派生，先判书型，叙事型才切阶段）→ 画成一条
// 横向阶段带：每个大阶段一段，段宽按它占的章数大致成比例（比如「背景 → 爆发 → 相持 →
// 平定」那样一条带子）。点一段展开这段的概括 + 代表事件原文。
//
// 两个诚实约束：
//   1. 段的填色只用来把相邻两段分开（深浅交替），不编「张力高低」那种没依据的量——
//      编一个原文里没有的强度维度，正好犯 evidence-first 的忌。
//   2. 代表原文过了核验才盖「鉴」印（SealMark）；没核的原样显示，不盖印、也不标吓人的
//      「待核」。
//
// book_type 通过 onBookType 抛给父镜头（NarrativePanorama），父层据它做题材自适应：论述型
// 就把小说专属的几段收起来。论述型没有时间阶段，这里也不硬画，只说一句、照样把书型抛上去。
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { SealButton } from "./SealButton";
import { SealMark } from "./SealMark";

interface Phase {
  name: string;
  start_ch: number;
  end_ch: number;
  gist: string;
  evidence: string;
  verified?: boolean;
  match_score?: number;
}

interface PhasesResult {
  book_type: string;
  phases: Phase[];
}

interface NarrativePhasesProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  /** 把判出来的书型（叙事型 / 论述型）抛给父镜头做题材自适应。 */
  onBookType?: (bookType: string) => void;
}

export function NarrativePhases({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  onBookType,
}: NarrativePhasesProps) {
  const [result, setResult] = useState<PhasesResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 点开了哪一段（看它的概括 + 代表原文）。再点一次收起。
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  // 换书就把已生成的阶段清掉——本镜头在 App 里一直挂着（只是切显隐），不清会残留上一本的带子。
  useEffect(() => {
    setResult(null);
    setError(null);
    setTrace(null);
    setOpenIdx(null);
  }, [sessionId]);

  async function load() {
    setLoading(true);
    setError(null);
    setOpenIdx(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/narrative-phases", {
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
        book_type?: string;
        phases?: Phase[];
        scanned?: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      if (!data.scanned) {
        setError("没读出阶段，稍后重试。");
      } else {
        const bookType = data.book_type ?? "";
        setResult({
          book_type: bookType,
          phases: Array.isArray(data.phases) ? data.phases : [],
        });
        // 书型只要判出来了就抛给父镜头（论述型也抛，父层据它收起小说专属的几段）。
        if (bookType) onBookType?.(bookType);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 空态（还没生成）：统一入口卡，点了才发请求。
  if (!result) {
    return (
      <FeatureEntryCard
        title="阶段"
        lead="把整本书分成几个大阶段（比如从开局铺垫到收尾），一条带子看清各阶段占多少篇幅。点一段看这段讲了什么、有哪件代表性的事（原文）。"
        actionLabel="划分阶段"
        loadingLabel="读全书划分阶段中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书理出阶段，约一分钟；读过一次再看就快"
        error={error}
      >
        {loading && (
          <RunningProcess
            label="读全书划分情节阶段"
            hint="把整本书逐章读一遍，理出几个大阶段、每段摘一件代表事件回原文核对，约一分钟。"
          />
        )}
      </FeatureEntryCard>
    );
  }

  const isTreatise = result.book_type === "论述型";
  const phases = result.phases;

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-1">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          阶段
        </h3>
        <SealButton
          size="sm"
          label="重新划分"
          loadingLabel="划分中…"
          loading={loading}
          onClick={load}
        />
      </div>

      <style>{PHASES_CSS}</style>

      {isTreatise || phases.length === 0 ? (
        // 论述型没有时间阶段，不硬画；叙事型偶尔也分不出明显阶段，同样只说一句。
        <div
          className="mt-2 rounded-md border px-4 py-3 text-sm text-[var(--color-ink-muted)] leading-relaxed"
          style={{
            borderColor: "var(--color-folio-edge)",
            background: "var(--color-paper-raised)",
          }}
        >
          {isTreatise
            ? "这本书讲的是道理和观点，不是按时间推进的故事，分不出情节阶段。往下看时间线也许更合适。"
            : "没能分出明显的情节阶段，稍后可以重试。"}
        </div>
      ) : (
        <>
          <p className="text-sm text-[var(--color-ink-muted)] mb-3">
            全书分成 {phases.length} 个大阶段，段的宽窄按它占的章数排。点一段看这段的概括和代表事件的原文。
          </p>

          {/* 阶段带：窄屏放不下就横向滚动看，段宽按章数成比例。 */}
          <div style={{ overflowX: "auto" }}>
            <div className="np-band flex items-stretch gap-1" style={{ minWidth: 320 }}>
              {phases.map((p, i) => {
                const span = Math.max(1, p.end_ch - p.start_ch + 1);
                const open = openIdx === i;
                // 填色只区分相邻段（深浅交替），不编强度——避免造一个原文里没有的量。
                const baseFill =
                  i % 2 === 0
                    ? "color-mix(in oklch, var(--color-seal) 15%, var(--color-paper-raised))"
                    : "color-mix(in oklch, var(--color-seal) 24%, var(--color-paper-raised))";
                return (
                  <button
                    key={`${p.name}-${i}`}
                    type="button"
                    className="np-seg"
                    aria-current={open ? "true" : undefined}
                    aria-expanded={open}
                    onClick={() => setOpenIdx(open ? null : i)}
                    style={{
                      flex: `${span} 1 0%`,
                      minWidth: 76,
                      background: open
                        ? "color-mix(in oklch, var(--color-seal) 38%, var(--color-paper-raised))"
                        : baseFill,
                      boxShadow: open ? "0 0 0 2px var(--color-seal)" : undefined,
                      ["--np-delay" as string]: `${Math.min(i * 80, 480)}ms`,
                    }}
                  >
                    <span className="np-seg-accent" aria-hidden />
                    <span className="np-seg-name">{p.name}</span>
                    <span className="np-seg-range">
                      {p.start_ch === p.end_ch
                        ? `第 ${p.start_ch} 章`
                        : `${p.start_ch}–${p.end_ch} 章`}
                    </span>
                  </button>
                );
              })}
            </div>
            {/* 带子下的一道细朱砂规，把各阶段连成一条脉（从左展开）。 */}
            <div className="np-base" aria-hidden style={{ minWidth: 320 }} />
          </div>

          {/* 点开一段：这段的概括 + 代表事件原文；核过的盖「鉴」印。 */}
          {openIdx !== null && phases[openIdx] && (
            <PhaseDetail phase={phases[openIdx]} />
          )}
        </>
      )}

      {loading ? (
        <RunningProcess label="重新划分情节阶段" />
      ) : (
        <RunStats
          trace={trace}
          note={isTreatise ? "论述型，不分阶段" : `${phases.length} 个阶段`}
        />
      )}
    </div>
  );
}

// 点开一段的详情：阶段名 · 起止章 → 一句概括 → 代表事件原文（核过的盖印）。
function PhaseDetail({ phase }: { phase: Phase }) {
  const verified = !!phase.verified && !!phase.evidence.trim();
  return (
    <div
      className="np-detail mt-4 rounded-md border overflow-hidden"
      style={{
        borderColor: "var(--color-folio-edge)",
        background: "var(--color-paper-raised)",
      }}
    >
      <div
        className="px-4 py-2.5 border-b"
        style={{ borderColor: "var(--color-rule)", background: "var(--color-paper)" }}
      >
        <p
          className="text-sm font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          「{phase.name}」
          <span className="ml-2 text-xs font-normal text-[var(--color-ink-muted)] tabular-nums">
            {phase.start_ch === phase.end_ch
              ? `第 ${phase.start_ch} 章`
              : `第 ${phase.start_ch}–${phase.end_ch} 章`}
          </span>
        </p>
      </div>

      <div className="px-4 py-3">
        {phase.gist.trim() && (
          <p className="text-sm text-[var(--color-ink)] leading-relaxed mb-3">
            {phase.gist}
          </p>
        )}

        <div className="flex items-center gap-2 mb-1.5">
          <span
            className="text-xs font-medium text-[var(--color-ink-muted)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            代表事件原文
          </span>
          {verified && <SealMark size={18} title="原文已核对" />}
        </div>
        <blockquote
          className="border-l-2 pl-3 py-0.5 text-sm text-[var(--color-ink)] leading-relaxed"
          style={{
            fontFamily: "var(--font-display)",
            borderColor: "color-mix(in oklch, var(--color-seal) 40%, transparent)",
          }}
        >
          {phase.evidence.trim() || "这一阶段没摘到代表原文。"}
        </blockquote>
      </div>

      {verified && (
        <p
          className="px-4 py-2 text-xs text-[var(--color-ink-muted)] border-t"
          style={{ borderColor: "var(--color-rule)" }}
        >
          盖「鉴」印的原文已逐字核对过。
        </p>
      )}
    </div>
  );
}

// 入场动画全走 CSS（headless 预览把 rAF 节流，不依赖 JS 动画帧）：
// 各段按 --np-delay 依次浮入；带子下的规从左展开；详情面板淡入。
const PHASES_CSS = `
@keyframes np-seg-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
.np-seg {
  position: relative; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 4px;
  min-height: 72px; padding: 10px 8px; border-radius: 6px;
  border: 1px solid var(--color-folio-edge); cursor: pointer; text-align: center;
  transition: filter .15s ease, transform .15s ease, box-shadow .15s ease, background .2s ease;
  animation: np-seg-in .5s ease-out both; animation-delay: var(--np-delay, 0ms);
}
.np-seg:hover { filter: brightness(1.04); transform: translateY(-2px); }
.np-seg:focus-visible { outline: 2px solid var(--color-seal); outline-offset: 2px; }
.np-seg-accent {
  position: absolute; top: 0; left: 14%; right: 14%; height: 3px;
  border-radius: 0 0 3px 3px; background: var(--color-seal); opacity: .45;
  transition: opacity .15s ease, left .2s ease, right .2s ease;
}
.np-seg:hover .np-seg-accent, .np-seg[aria-current="true"] .np-seg-accent {
  opacity: 1; left: 6%; right: 6%;
}
.np-seg-name {
  font-family: var(--font-display); font-weight: 700; font-size: 14px;
  color: var(--color-ink); line-height: 1.25;
}
.np-seg-range { font-size: 11px; color: var(--color-ink-muted); font-variant-numeric: tabular-nums; }
@keyframes np-base-grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
.np-base {
  height: 2px; margin-top: 6px; transform-origin: left;
  background: linear-gradient(to right, transparent, var(--color-seal) 8%, var(--color-seal) 92%, transparent);
  opacity: .3; animation: np-base-grow .6s ease-out both;
}
@keyframes np-detail-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.np-detail { animation: np-detail-in .28s ease-out both; }
@media (prefers-reduced-motion: reduce) {
  .np-seg, .np-base, .np-detail { animation: none; }
  .np-seg { transition: none; }
}
`;
