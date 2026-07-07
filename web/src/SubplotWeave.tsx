// ---------------------------------------------------------------------------
// SubplotWeave — 支线编织图 / braided narrative（WP-subplot-weave，probe GO）
//
// 点生成 → 调 /api/agent/subplot-weave（整本进上下文抽支线 + 逐章活跃 + 交汇）→ 自写 SVG：
// 每条支线一条横向泳道穿过全书章节。
//   · 活跃段（active_chapters 里的章）：实心点睛色的粗段 + 端点，一眼看见这条线在哪几章推进。
//   · 休眠段：灰色细虚线断开——某支线"沉寂二十章又回来"在图上就是灰白后重新亮起。
//   · 交汇点：两条泳道在同一章用一条竖向连接 + 节点勾连，交汇密集的章自然成"高潮带"。
// 点活跃段看该支线原文；点交汇节点看两条支线在该章勾连的两段原文；点支线名高亮整条线。
// evidence-first：verified=false 的支线整条泳道淡化（主观构念不剔）；交汇 BE 已双端核验过
// 才返回（一条腿站不住的交汇不画）。
//
// CPU-only，不引重图库，泳道是横线 + 矩形段、交汇是竖线 + 节点（同伏笔弧线 / 节奏曲线自写
// SVG）。进场逐泳道描画动画（带冷却，重出才再放），rAF 不参与——纯 CSS 动画一次性，绝不空转。
// ---------------------------------------------------------------------------

import { useMemo, useRef, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { usePanZoom } from "./usePanZoom";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { SealButton } from "./SealButton";

interface Subplot {
  name: string;
  active_chapters: number[];
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface Intersection {
  subplots: [string, string] | string[];
  chapter: number;
  a_evidence: string;
  b_evidence: string;
  a_verified: boolean;
  b_verified: boolean;
  a_match_score: number;
  b_match_score: number;
}

interface SubplotWeaveProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

const W = 880;
const PAD_LEFT = 132; // 左边给支线名留位
const PAD_RIGHT = 28;
const PAD_TOP = 24;
const LANE_H = 46; // 每条泳道纵向间距
const DOT_R = 3; // 活跃章端点半径

export function SubplotWeave({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: SubplotWeaveProps) {
  const [subplots, setSubplots] = useState<Subplot[] | null>(null);
  const [intersections, setIntersections] = useState<Intersection[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 选中：活跃段（支线 index + 章号）或交汇点（交汇 index）
  const [selSegment, setSelSegment] = useState<{ sp: number; chapter: number } | null>(
    null,
  );
  const [selInter, setSelInter] = useState<number | null>(null);
  const [hoverSp, setHoverSp] = useState<number | null>(null);
  // 进场动画：load 成功后 key 变 → 重新触发描画；冷却期内不重复放
  const [animKey, setAnimKey] = useState(0);

  async function load() {
    setLoading(true);
    setError(null);
    setSelSegment(null);
    setSelInter(null);
    setHoverSp(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/subplot-weave", {
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
        subplots: Subplot[];
        intersections: Intersection[];
        scanned?: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      if (!data.subplots || data.subplots.length === 0) {
        setError(
          data.scanned
            ? "扫过全书，没切出成形的情节支线。"
            : "没抽出支线编织图，稍后重试。",
        );
      } else {
        setSubplots(data.subplots);
        setIntersections(data.intersections ?? []);
        setAnimKey((k) => k + 1);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 布局派生量：全书章号范围、各支线 lane y、章号→x 映射
  const layout = useMemo(() => {
    if (!subplots) return null;
    let lo = Infinity;
    let hi = -Infinity;
    for (const s of subplots) {
      for (const ch of s.active_chapters) {
        lo = Math.min(lo, ch);
        hi = Math.max(hi, ch);
      }
    }
    for (const it of intersections) {
      lo = Math.min(lo, it.chapter);
      hi = Math.max(hi, it.chapter);
    }
    if (!Number.isFinite(lo)) {
      lo = 1;
      hi = 1;
    }
    const minCh = lo;
    const maxCh = hi;
    const span = Math.max(1, maxCh - minCh);
    const innerW = W - PAD_LEFT - PAD_RIGHT;
    const xAt = (ch: number) => PAD_LEFT + ((ch - minCh) / span) * innerW;
    // 支线按最早活跃章排序，主线（活跃章最多）也自然偏中——这里按活跃跨度降序定泳道顺序
    const order = subplots
      .map((s, i) => ({ i, span: s.active_chapters.length }))
      .sort((a, b) => b.span - a.span)
      .map((o) => o.i);
    const laneY = new Map<number, number>();
    order.forEach((spIdx, row) => {
      laneY.set(spIdx, PAD_TOP + LANE_H * (row + 0.5));
    });
    const yOf = (spIdx: number) => laneY.get(spIdx) ?? PAD_TOP;
    return { minCh, maxCh, span, xAt, yOf, order };
  }, [subplots, intersections]);

  // ⚠ hooks 必须在任何 early return 之前无条件调用(React Hooks 规则)。否则空态 return 后
  // 这几个 hook 不跑、生成出支线后才跑,hook 数量在两次 render 间变化 → React 直接崩(白屏)。
  // H 用 subplots?.length 兜底,空态也算得出(= PAD_TOP*2)。
  const svgRef = useRef<SVGSVGElement | null>(null);
  const H = PAD_TOP * 2 + LANE_H * (subplots?.length ?? 0);
  const { view, onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onWheel, resetView } =
    usePanZoom(svgRef, { width: W, height: H });

  if (!subplots || !layout) {
    // 空态（还没生成）：统一入口卡（视觉表现根治 · FeatureEntryCard）
    return (
      <FeatureEntryCard
        title="支线编织"
        lead="每条情节支线一条横向泳道穿过全书，活跃段亮、休眠段灰断，两条线同章交汇画连接节点。一眼看见哪条支线断更太久、哪几章是多线交汇的高潮。点活跃段 / 交汇看原文。"
        actionLabel="生成支线编织图"
        loadingLabel="读全书抽支线中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书抽支线 + 交汇，约 1 分钟；命中缓存秒出"
        error={error}
      >
        {loading && (
          <RunningProcess
            label="读全书抽支线编织"
            hint="整本书喂进模型抽情节支线 + 逐章活跃 + 交汇，支线和交汇都回原文核验，约 1 分钟。"
          />
        )}
      </FeatureEntryCard>
    );
  }

  const { minCh, maxCh, xAt, yOf, order } = layout;
  const verifiedSp = subplots.filter((s) => s.verified).length;

  // 交汇点按支线名定位到泳道 y（找到对应支线 index）
  const spIdxByName = new Map<string, number>();
  subplots.forEach((s, i) => spIdxByName.set(s.name, i));

  // 把一条支线的活跃章压成连续段（相邻章号连成一段实线，间断处断开 → 休眠灰段）
  function activeRuns(active: number[]): { from: number; to: number }[] {
    if (active.length === 0) return [];
    const sorted = [...active].sort((a, b) => a - b);
    const runs: { from: number; to: number }[] = [];
    let start = sorted[0];
    let prev = sorted[0];
    for (let k = 1; k < sorted.length; k++) {
      if (sorted[k] === prev + 1) {
        prev = sorted[k];
      } else {
        runs.push({ from: start, to: prev });
        start = sorted[k];
        prev = sorted[k];
      }
    }
    runs.push({ from: start, to: prev });
    return runs;
  }

  const selInterObj = selInter != null ? intersections[selInter] : null;
  const selSegObj =
    selSegment != null ? subplots[selSegment.sp] ?? null : null;

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          支线编织
        </h3>
        <SealButton
          size="sm"
          label="重新生成"
          loadingLabel="重出中…"
          loading={loading}
          onClick={load}
        />
      </div>

      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        {subplots.length} 条支线、{intersections.length} 处交汇（支线证据已核验{" "}
        {verifiedSp}/{subplots.length} 条）。每条横线一条支线，实段 = 活跃、灰虚 = 休眠；竖向节点 = 两线同章交汇。点活跃段看原文、点交汇看两段勾连原文、点支线名高亮整条线；淡化的泳道 = 支线证据没核验上。
      </p>

      <svg
        ref={svgRef}
        key={animKey}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full border border-[var(--color-rule)] rounded touch-none"
        style={{ maxHeight: 560, background: "var(--color-paper)" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onPointerLeave={onPointerUp}
        onWheel={onWheel}
      >
        <style>{`
          @keyframes sw-grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
          .sw-run { animation: sw-grow 0.7s ease-out forwards; transform-origin: left center; }
        `}</style>
        {/* 缩放平移层：泳道 + 活跃段 + 交汇点都在这个 <g> 里，整图能缩能拖、双指捏合看细节 */}
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>

        {/* 章号刻度（min / mid / max，避免百回级糊成一片） */}
        {[minCh, Math.round((minCh + maxCh) / 2), maxCh].map((ch, i) => (
          <text
            key={`x-${i}`}
            x={xAt(ch)}
            y={H - 6}
            textAnchor="middle"
            fontSize={9}
            fill="var(--color-ink-muted)"
          >
            第{ch}章
          </text>
        ))}

        {/* 每条支线一条泳道 */}
        {order.map((spIdx) => {
          const s = subplots[spIdx];
          const y = yOf(spIdx);
          const dimmedByHover = hoverSp != null && hoverSp !== spIdx;
          const dimmedByVerify = !s.verified;
          const baseOpacity = dimmedByHover ? 0.16 : dimmedByVerify ? 0.4 : 1;
          const runs = activeRuns(s.active_chapters);
          return (
            <g
              key={`lane-${spIdx}`}
              onPointerEnter={() => setHoverSp(spIdx)}
              onPointerLeave={() => setHoverSp(null)}
            >
              {/* 休眠底线：整条泳道一条灰虚线（活跃段会盖上实段） */}
              <line
                x1={PAD_LEFT}
                y1={y}
                x2={W - PAD_RIGHT}
                y2={y}
                stroke="#c9c2b6"
                strokeWidth={1}
                strokeDasharray="3 4"
                opacity={baseOpacity * 0.7}
              />

              {/* 活跃段：实线点睛色 + 两端点；单章活跃也画一个可点的圆点 */}
              {runs.map((run, ri) => {
                const x1 = xAt(run.from);
                const x2 = xAt(run.to);
                const selectedRun =
                  selSegment?.sp === spIdx &&
                  selSegment.chapter >= run.from &&
                  selSegment.chapter <= run.to;
                return (
                  <g
                    key={`run-${spIdx}-${ri}`}
                    style={{ cursor: "pointer" }}
                    onClick={() => {
                      setSelSegment({ sp: spIdx, chapter: run.from });
                      setSelInter(null);
                    }}
                  >
                    {/* 透明粗线热区 */}
                    <line
                      x1={x1}
                      y1={y}
                      x2={x2}
                      y2={y}
                      stroke="transparent"
                      strokeWidth={14}
                    />
                    <line
                      className="sw-run"
                      x1={x1}
                      y1={y}
                      x2={x2}
                      y2={y}
                      stroke="var(--color-seal)"
                      strokeWidth={selectedRun ? 4 : 2.4}
                      strokeLinecap="round"
                      opacity={baseOpacity * (selectedRun ? 1 : 0.82)}
                    />
                    <circle
                      cx={x1}
                      cy={y}
                      r={DOT_R}
                      fill="var(--color-seal)"
                      opacity={baseOpacity}
                    />
                    {run.to !== run.from && (
                      <circle
                        cx={x2}
                        cy={y}
                        r={DOT_R}
                        fill="var(--color-seal)"
                        opacity={baseOpacity}
                      />
                    )}
                  </g>
                );
              })}

              {/* 支线名（左栏，点高亮整条线） */}
              <text
                x={PAD_LEFT - 10}
                y={y + 3}
                textAnchor="end"
                fontSize={11}
                fill={
                  dimmedByHover
                    ? "var(--color-ink-muted)"
                    : "var(--color-ink)"
                }
                opacity={dimmedByVerify ? 0.5 : 1}
                style={{ cursor: "pointer", fontFamily: "var(--font-display)" }}
                onClick={() => setHoverSp(hoverSp === spIdx ? null : spIdx)}
              >
                {s.name.length > 11 ? s.name.slice(0, 11) + "…" : s.name}
                <title>{s.name}</title>
              </text>
            </g>
          );
        })}

        {/* 交汇节点：两条支线在同一章用一条竖线 + 中点节点勾连 */}
        {intersections.map((it, ii) => {
          const aIdx = spIdxByName.get(it.subplots[0]);
          const bIdx = spIdxByName.get(it.subplots[1]);
          if (aIdx === undefined || bIdx === undefined) return null;
          const x = xAt(it.chapter);
          const ya = yOf(aIdx);
          const yb = yOf(bIdx);
          const midY = (ya + yb) / 2;
          const active = selInter === ii;
          const dimmed =
            hoverSp != null && hoverSp !== aIdx && hoverSp !== bIdx;
          return (
            <g
              key={`inter-${ii}`}
              style={{ cursor: "pointer" }}
              onClick={() => {
                setSelInter(ii);
                setSelSegment(null);
              }}
              opacity={dimmed ? 0.18 : 1}
            >
              {/* 透明粗线热区 */}
              <line
                x1={x}
                y1={ya}
                x2={x}
                y2={yb}
                stroke="transparent"
                strokeWidth={12}
              />
              <line
                x1={x}
                y1={ya}
                x2={x}
                y2={yb}
                stroke="var(--color-ink)"
                strokeWidth={active ? 1.8 : 1}
                opacity={active ? 0.8 : 0.4}
              />
              <circle
                cx={x}
                cy={midY}
                r={active ? 5 : 3.6}
                fill="var(--color-paper)"
                stroke="var(--color-seal)"
                strokeWidth={active ? 2 : 1.4}
              />
            </g>
          );
        })}
        </g>
      </svg>

      <div className="mt-2">
        <button
          type="button"
          onClick={resetView}
          className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
        >
          重置视角
        </button>
      </div>

      {/* 图例 */}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-ink-muted)]">
        <span className="flex items-center gap-1">
          <svg width="22" height="6" aria-hidden>
            <line x1="1" y1="3" x2="21" y2="3" stroke="var(--color-seal)" strokeWidth={2.4} strokeLinecap="round" />
          </svg>
          活跃
        </span>
        <span className="flex items-center gap-1">
          <svg width="22" height="6" aria-hidden>
            <line x1="1" y1="3" x2="21" y2="3" stroke="#c9c2b6" strokeWidth={1} strokeDasharray="3 3" />
          </svg>
          休眠
        </span>
        <span className="flex items-center gap-1">
          <svg width="14" height="14" aria-hidden>
            <circle cx="7" cy="7" r="3.6" fill="var(--color-paper)" stroke="var(--color-seal)" strokeWidth={1.4} />
          </svg>
          交汇
        </span>
      </div>

      {/* 交汇详情：两段勾连原文 */}
      {selInterObj && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            第 {selInterObj.chapter} 章 · 「{selInterObj.subplots[0]}」与「
            {selInterObj.subplots[1]}」交汇
          </p>
          <div className="mt-2">
            <div className="text-xs text-[var(--color-ink-muted)] mb-0.5">
              「{selInterObj.subplots[0]}」这章原文 · 已核验
            </div>
            <p className="text-sm leading-relaxed text-[var(--color-ink)]">
              {selInterObj.a_evidence || "（无原文）"}
            </p>
          </div>
          <div className="mt-2">
            <div className="text-xs text-[var(--color-ink-muted)] mb-0.5">
              「{selInterObj.subplots[1]}」这章原文 · 已核验
            </div>
            <p className="text-sm leading-relaxed text-[var(--color-ink)]">
              {selInterObj.b_evidence || "（无原文）"}
            </p>
          </div>
        </div>
      )}

      {/* 活跃段详情：该支线的存在原文 */}
      {selSegObj && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            「{selSegObj.name}」· 活跃于第{" "}
            {selSegObj.active_chapters.join("、")} 章
          </p>
          <div className="mt-2">
            <div className="text-xs text-[var(--color-ink-muted)] mb-0.5">
              这条支线的原文依据
              {selSegObj.verified ? " · 已核验" : " · 未在原文比对命中（仅供参考）"}
            </div>
            <p
              className="text-sm leading-relaxed"
              style={{
                color: "var(--color-ink)",
                opacity: selSegObj.verified ? 1 : 0.45,
              }}
            >
              {selSegObj.evidence || "（这条支线没给出原文片段）"}
            </p>
          </div>
        </div>
      )}

      {loading ? (
        <RunningProcess label="重出支线编织图" />
      ) : (
        <RunStats
          trace={trace}
          note={`${subplots.length} 条支线 · ${intersections.length} 处交汇`}
        />
      )}
    </div>
  );
}
