// ---------------------------------------------------------------------------
// RelationshipTimeline — 关系随时间演变（WP-relationship-over-time）
//
// 关系演变的命根子是「时间」——一对关系怎么一章章从疏到紧到裂。和关系图（谁连谁的
// 静态节点网）彻底分工：这里不再画节点网（那是关系图的活，画了就撞脸），只看演变。
//   · 默认：小多图时间线——挑戏份最重的 N 对，每对一行横向 sparkline（线高 = 紧 / 低 = 疏）
//     + 转折点标记，一眼扫到所有关键关系怎么起落。
//   · 点一行 → 下钻看那对的强度逐章大图 + 转折点，点转折看原文。
// evidence-first：转折 verified=false 标灰 / 虚线（核不过不当确定结论画）。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";

interface StrengthPoint {
  chapter: number;
  strength: number; // 0-10
}

interface TurningPoint {
  chapter: number;
  change: string;
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface Relation {
  a: string;
  b: string;
  relation: string;
  points: StrengthPoint[];
  turning_points: TurningPoint[];
}

interface RelationshipTimelineProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 一对关系第 ch 章的强度：在 points 上线性插值（早于首点 → null 不画；晚于末点 → 维持末值）。
function strengthAt(points: StrengthPoint[], ch: number): number | null {
  if (points.length === 0) return null;
  if (ch < points[0].chapter) return null;
  if (ch >= points[points.length - 1].chapter)
    return points[points.length - 1].strength;
  for (let i = 0; i < points.length - 1; i++) {
    const p = points[i];
    const q = points[i + 1];
    if (ch >= p.chapter && ch <= q.chapter) {
      const span = q.chapter - p.chapter;
      if (span <= 0) return p.strength;
      const t = (ch - p.chapter) / span;
      return p.strength + (q.strength - p.strength) * t;
    }
  }
  return points[points.length - 1].strength;
}

// ---- 小多图几何 ----
const SM_W = 760;
const SM_PAD_L = 122; // 左边给关系名留位
const SM_PAD_R = 18;
const SM_PAD_T = 26; // 顶部给章号刻度
const ROW_H = 40;
const TOP_PAIRS = 14; // 默认一屏画戏份最重的几对，点关系名外的「看全部」展开

export function RelationshipTimeline({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: RelationshipTimelineProps) {
  const [relations, setRelations] = useState<Relation[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [selRel, setSelRel] = useState<number | null>(null); // 下钻到哪一对
  const [selTp, setSelTp] = useState<number | null>(null); // 选中的转折
  const [showAll, setShowAll] = useState(false); // 小多图是否画全部关系

  async function load() {
    setLoading(true);
    setError(null);
    setSelRel(null);
    setSelTp(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/relationship-timeline", {
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
        relations: Relation[];
        scanned?: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      if (!data.relations || data.relations.length === 0) {
        setError("没抽出关系演变，稍后重试。");
      } else {
        setRelations(data.relations);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 全书章号范围（所有 points + turning_points 的章号）
  const [minCh, maxCh] = useMemo(() => {
    if (!relations) return [1, 1];
    let lo = Infinity;
    let hi = -Infinity;
    for (const r of relations) {
      for (const p of r.points) {
        lo = Math.min(lo, p.chapter);
        hi = Math.max(hi, p.chapter);
      }
      for (const t of r.turning_points) {
        lo = Math.min(lo, t.chapter);
        hi = Math.max(hi, t.chapter);
      }
    }
    if (!Number.isFinite(lo)) return [1, 1];
    return [lo, hi];
  }, [relations]);

  // 重要度排序：转折多 + 逐章点多 = 戏份重，靠前
  const ranked = useMemo(() => {
    if (!relations) return [];
    return relations
      .map((r, i) => ({ r, i }))
      .sort(
        (x, y) =>
          y.r.turning_points.length * 2 +
          y.r.points.length -
          (x.r.turning_points.length * 2 + x.r.points.length),
      );
  }, [relations]);

  // ---- 未生成：入口卡片 ----
  if (!relations) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          关系演变
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          一眼看全书每对关键关系怎么一章章走——从疏到紧、从合到裂。选一对看它的强度曲线，每个转折都钉得到原文。（谁和谁的整张关系网看「关系图」。）
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读全书抽关系演变中（约 1 分钟）…" : "生成关系演变"}
        </button>
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {!apiKey && (
          <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
            填了 API key 才能生成。
          </p>
        )}
        {loading && (
          <RunningProcess
            label="读全书抽关系演变"
            hint="整本书喂进模型，逐对关系判逐章强度 + 转折——每个转折都回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  const totalTurns = relations.reduce((s, r) => s + r.turning_points.length, 0);
  const verifiedTurns = relations.reduce(
    (s, r) => s + r.turning_points.filter((t) => t.verified).length,
    0,
  );
  const chSpan = Math.max(1, maxCh - minCh);

  // ---- 下钻：单对曲线几何 ----
  const cur = selRel != null ? relations[selRel] : null;
  const tp = cur && selTp != null ? cur.turning_points[selTp] : null;
  const curveW = SM_W;
  const curveH = 260;
  const cPadL = 34;
  const cPadR = 16;
  const cPadT = 16;
  const cPadB = 28;
  const innerW = curveW - cPadL - cPadR;
  const innerH = curveH - cPadT - cPadB;
  const cx = (ch: number) => cPadL + ((ch - minCh) / chSpan) * innerW;
  const cy = (s: number) =>
    cPadT + innerH - (Math.max(0, Math.min(10, s)) / 10) * innerH;
  const curvePts =
    cur && cur.points.length > 0
      ? cur.points.map((p) => `${cx(p.chapter)},${cy(p.strength)}`).join(" ")
      : "";

  // ---- 小多图几何 ----
  const shown = showAll ? ranked : ranked.slice(0, TOP_PAIRS);
  const smInnerW = SM_W - SM_PAD_L - SM_PAD_R;
  const smH = SM_PAD_T + shown.length * ROW_H + 14;
  const smX = (ch: number) => SM_PAD_L + ((ch - minCh) / chSpan) * smInnerW;
  const smY = (idx: number, s: number) => {
    const top = SM_PAD_T + idx * ROW_H + 9;
    const bot = SM_PAD_T + (idx + 1) * ROW_H - 7;
    return bot - (Math.max(0, Math.min(10, s)) / 10) * (bot - top);
  };
  const axisTicks = [minCh, Math.round((minCh + maxCh) / 2), maxCh];

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          关系演变
        </h3>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "重出中…" : "重新生成"}
        </button>
      </div>

      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        {relations.length} 对关系、{totalTurns} 个转折（原文核验 {verifiedTurns}/
        {totalTurns}）。
        {cur
          ? "这一对的强度逐章变化，圆点是转折——实心 = 已核验、空心虚线 = 没核验上。点转折看原文。"
          : "每行一对，线往上 = 越来越紧、往下 = 渐疏，圆点是转折。点一行看那对的细节。"}
      </p>

      {!loading && <RunStats trace={trace} note={`${relations.length} 对关系`} />}

      {cur ? (
        // ── 下钻：单对强度曲线 ──
        <>
          <button
            type="button"
            onClick={() => {
              setSelRel(null);
              setSelTp(null);
            }}
            className="mt-2 mb-1 text-xs text-[var(--color-seal)] hover:underline"
          >
            ‹ 返回所有关系
          </button>
          <svg
            viewBox={`0 0 ${curveW} ${curveH}`}
            className="w-full border border-[var(--color-rule)] rounded bg-white"
          >
            {[2, 4, 6, 8, 10].map((lvl) => (
              <line
                key={`g-${lvl}`}
                x1={cPadL}
                y1={cy(lvl)}
                x2={curveW - cPadR}
                y2={cy(lvl)}
                stroke="var(--color-rule)"
                strokeWidth={0.5}
              />
            ))}
            <text x={cPadL - 5} y={cy(10) + 3} textAnchor="end" fontSize={9} fill="var(--color-ink-muted)">紧</text>
            <text x={cPadL - 5} y={cy(2) + 3} textAnchor="end" fontSize={9} fill="var(--color-ink-muted)">疏</text>
            {curvePts && (
              <polyline
                points={curvePts}
                fill="none"
                stroke="var(--color-seal)"
                strokeWidth={1.8}
                strokeLinejoin="round"
                strokeLinecap="round"
                opacity={0.85}
              />
            )}
            {cur.points.map((p) => (
              <circle
                key={`p-${p.chapter}`}
                cx={cx(p.chapter)}
                cy={cy(p.strength)}
                r={2.4}
                fill="var(--color-seal)"
                opacity={0.7}
              />
            ))}
            {cur.turning_points.map((t, i) => {
              const x = cx(t.chapter);
              const s = strengthAt(cur.points, t.chapter);
              const y = s != null ? cy(s) : cPadT + innerH / 2;
              const active = selTp === i;
              return (
                <g key={`tp-${t.chapter}-${i}`}>
                  <line
                    x1={x}
                    y1={cPadT}
                    x2={x}
                    y2={cPadT + innerH}
                    stroke={active ? "var(--color-seal)" : "var(--color-ink-muted)"}
                    strokeWidth={active ? 1.2 : 0.7}
                    strokeDasharray={t.verified ? undefined : "3 3"}
                    opacity={t.verified ? (active ? 0.7 : 0.4) : 0.25}
                  />
                  <circle
                    cx={x}
                    cy={y}
                    r={active ? 6 : 4.5}
                    fill={t.verified ? "var(--color-seal)" : "var(--color-paper)"}
                    stroke="var(--color-seal)"
                    strokeWidth={t.verified ? 0 : 1.4}
                    opacity={t.verified ? 0.95 : 0.6}
                    style={{ cursor: "pointer" }}
                    onClick={() => setSelTp(i)}
                  />
                </g>
              );
            })}
            {[minCh, maxCh, ...cur.turning_points.map((t) => t.chapter)].map(
              (ch, i) => (
                <text
                  key={`xt-${ch}-${i}`}
                  x={cx(ch)}
                  y={curveH - 8}
                  textAnchor="middle"
                  fontSize={9}
                  fill="var(--color-ink-muted)"
                >
                  {ch}
                </text>
              ),
            )}
          </svg>
          <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
            {cur.a} 与 {cur.b}（{cur.relation || "关系"}）的强度逐章变化。圆点是转折，
            实心 = 原文已核验、空心虚线 = 没核验上（仅供参考）。点转折看原文。
          </p>

          {tp && (
            <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
              <p className="text-sm font-bold text-[var(--color-ink)]">
                第 {tp.chapter} 章 · {tp.change || "关系转折"}
              </p>
              <p className="mt-1 text-sm text-[var(--color-ink)] leading-relaxed">
                {tp.evidence || "（这个转折没给出原文片段）"}
              </p>
              <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
                {tp.verified
                  ? "原文已核验"
                  : "原文未在书中比对命中——这个转折仅供参考"}
              </p>
            </div>
          )}
        </>
      ) : (
        // ── 默认：小多图时间线 ──
        <>
          <svg
            viewBox={`0 0 ${SM_W} ${smH}`}
            className="w-full border border-[var(--color-rule)] rounded bg-white"
          >
            {/* 章号竖向参考线 + 顶部刻度 */}
            {axisTicks.map((ch, i) => (
              <g key={`ax-${ch}-${i}`}>
                <line
                  x1={smX(ch)}
                  y1={SM_PAD_T}
                  x2={smX(ch)}
                  y2={smH - 6}
                  stroke="var(--color-rule)"
                  strokeWidth={0.5}
                />
                <text
                  x={smX(ch)}
                  y={SM_PAD_T - 8}
                  textAnchor="middle"
                  fontSize={9}
                  fill="var(--color-ink-muted)"
                >
                  第{ch}章
                </text>
              </g>
            ))}

            {shown.map(({ r, i }, idx) => {
              const yMid = SM_PAD_T + idx * ROW_H + ROW_H / 2;
              const linePts = r.points
                .map((p) => `${smX(p.chapter)},${smY(idx, p.strength)}`)
                .join(" ");
              const label = `${r.a}—${r.b}`;
              return (
                <g
                  key={`row-${i}`}
                  style={{ cursor: "pointer" }}
                  onClick={() => {
                    setSelRel(i);
                    setSelTp(null);
                  }}
                >
                  {/* 整行点击热区 */}
                  <rect
                    x={0}
                    y={SM_PAD_T + idx * ROW_H}
                    width={SM_W}
                    height={ROW_H}
                    fill="transparent"
                  />
                  {/* 行分隔 */}
                  {idx > 0 && (
                    <line
                      x1={4}
                      y1={SM_PAD_T + idx * ROW_H}
                      x2={SM_W - 4}
                      y2={SM_PAD_T + idx * ROW_H}
                      stroke="var(--color-rule)"
                      strokeWidth={0.4}
                      opacity={0.5}
                    />
                  )}
                  {/* 关系名 */}
                  <text
                    x={6}
                    y={yMid + 3}
                    fontSize={11}
                    fill="var(--color-ink)"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {label.length > 11 ? label.slice(0, 11) + "…" : label}
                    <title>{label}（{r.relation || "关系"}）</title>
                  </text>
                  {/* 强度 sparkline */}
                  {linePts && (
                    <polyline
                      points={linePts}
                      fill="none"
                      stroke="var(--color-seal)"
                      strokeWidth={1.5}
                      strokeLinejoin="round"
                      strokeLinecap="round"
                      opacity={0.85}
                    />
                  )}
                  {/* 转折标记 */}
                  {r.turning_points.map((t, ti) => {
                    const s = strengthAt(r.points, t.chapter);
                    return (
                      <circle
                        key={`smtp-${i}-${ti}`}
                        cx={smX(t.chapter)}
                        cy={smY(idx, s ?? 5)}
                        r={2.6}
                        fill={t.verified ? "var(--color-seal)" : "var(--color-paper)"}
                        stroke="var(--color-seal)"
                        strokeWidth={t.verified ? 0 : 1.1}
                        opacity={t.verified ? 0.9 : 0.55}
                      />
                    );
                  })}
                </g>
              );
            })}
          </svg>
          <div className="mt-2 flex items-center justify-between">
            <p className="text-xs text-[var(--color-ink-muted)]">
              画了戏份最重的 {shown.length} 对 / 全书 {relations.length} 对（点一行看那对细节）。
            </p>
            {relations.length > TOP_PAIRS && (
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="text-xs text-[var(--color-seal)] hover:underline shrink-0"
              >
                {showAll ? "只看戏份最重的" : `看全部 ${relations.length} 对`}
              </button>
            )}
          </div>
        </>
      )}

      {loading && <RunningProcess label="重出关系演变" />}
    </div>
  );
}
