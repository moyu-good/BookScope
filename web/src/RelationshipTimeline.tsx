// ---------------------------------------------------------------------------
// RelationshipTimeline — 关系随时间演变（WP-relationship-over-time，probe GO）
//
// 点生成 → 调 /api/agent/relationship-timeline（整本进上下文逐对关系抽逐章强度 + 转折）
// → 两个视图共用一份数据，自写 SVG（CPU-only，不引重图库）：
//   · 时间轴快照：拖时间轴到第 N 章 → 力导向关系网只显示截至此章已成立的边，
//     连线粗细 = 截至此章强度（线性插值）；新关系淡入、衰减的边变细。带冷却省 CPU。
//   · 单对曲线：选一对关系 → 横轴章节、纵轴强度的折线 + 转折点标注，点转折看原文。
// evidence-first：转折 verified=false 的标灰/标低置信（核不过不当确定结论画）。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
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

const W = 760;
const H = 540;
const PAD = 46;

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  fixed: boolean;
}

// 强度 0-10 → 连线粗细（越紧越粗）
const edgeWidth = (s: number) => 0.8 + Math.max(0, Math.min(10, s)) * 0.42;

// 一对关系截至第 ch 章的强度：在 points 上线性插值。
// ch 早于第一个点 → 关系还没成立（返 null，不画）；晚于最后一个点 → 维持最后值。
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

  // 视图：snapshot（时间轴快照）/ curve（单对强度曲线）
  const [view, setView] = useState<"snapshot" | "curve">("snapshot");
  // 快照：当前拖到第几章
  const [cursor, setCursor] = useState(1);
  // 单对曲线：选中的关系下标 + 选中的转折下标
  const [selRel, setSelRel] = useState<number | null>(null);
  const [selTp, setSelTp] = useState<number | null>(null);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const simRef = useRef<Map<string, Node>>(new Map());
  const rafRef = useRef<number | null>(null);
  const coolRef = useRef(0);
  const dragRef = useRef<string | null>(null);
  const [, setFrame] = useState(0);

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

  // 全书章号范围（取所有 points + turning_points 的章号），拖动条用
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
    if (!isFinite(lo) || !isFinite(hi)) return [1, 1];
    return [lo, hi];
  }, [relations]);

  // 关系网全部节点（人名）
  const nodes = useMemo(() => {
    const set = new Set<string>();
    if (relations) {
      for (const r of relations) {
        set.add(r.a);
        set.add(r.b);
      }
    }
    return [...set];
  }, [relations]);

  // 拉到全书末尾，让初始快照展示完整关系网
  useEffect(() => {
    if (relations) setCursor(maxCh);
  }, [relations, maxCh]);

  // 截至 cursor 章已成立的边（强度可插值出来 = 关系已出现）
  const activeEdges = useMemo(() => {
    if (!relations) return [];
    const out: { a: string; b: string; relation: string; strength: number }[] = [];
    for (const r of relations) {
      const s = strengthAt(r.points, cursor);
      if (s == null) continue;
      out.push({ a: r.a, b: r.b, relation: r.relation, strength: s });
    }
    return out;
  }, [relations, cursor]);

  // 初始化节点（圆周）+ 启动力导向动画
  useEffect(() => {
    if (!relations || nodes.length === 0) return;
    const sim = new Map<string, Node>();
    const n = Math.max(1, nodes.length);
    nodes.forEach((name, i) => {
      const ang = (2 * Math.PI * i) / n;
      sim.set(name, {
        x: W / 2 + Math.cos(ang) * W * 0.28,
        y: H / 2 + Math.sin(ang) * H * 0.28,
        vx: 0,
        vy: 0,
        fixed: false,
      });
    });
    simRef.current = sim;
    coolRef.current = 0;
    if (view === "snapshot") startSim();
    return stopSim;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [relations, nodes]);

  // 拖时间轴改了边集 → 重新激活模拟（让网随时间重排）
  useEffect(() => {
    if (view === "snapshot" && relations && rafRef.current == null) {
      coolRef.current = 0;
      startSim();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursor, view]);

  function stopSim() {
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
  }

  function startSim() {
    stopSim();
    coolRef.current = 0;
    let ticks = 0; // 硬上限兜底：力学不收敛也强制停，绝不无限空转烧 CPU
    const tick = () => {
      const maxv = step();
      setFrame((f) => f + 1);
      ticks += 1;
      if (dragRef.current == null && maxv < 0.4) coolRef.current += 1;
      else coolRef.current = 0;
      if (coolRef.current > 40 || ticks > 600) {
        rafRef.current = null; // 冷却（静止）或到硬上限 ~600 帧：停 rAF 省 CPU
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }

  // 一帧物理：斥力(全对) + 弹簧(沿当前活动边，强度越大拉得越近) + 居中 + 阻尼
  function step(): number {
    const sim = simRef.current;
    if (!sim || nodes.length === 0) return 0;
    const fx = new Map<string, number>();
    const fy = new Map<string, number>();
    for (const nm of nodes) {
      const p = sim.get(nm)!;
      fx.set(nm, (W / 2 - p.x) * 0.008); // 居中
      fy.set(nm, (H / 2 - p.y) * 0.008);
    }
    // 斥力
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = sim.get(nodes[i])!;
        const b = sim.get(nodes[j])!;
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let d = Math.hypot(dx, dy);
        if (d < 0.01) {
          dx = Math.random() - 0.5;
          dy = Math.random() - 0.5;
          d = 0.01;
        }
        const rep = 4200 / (d * d);
        const ux = dx / d;
        const uy = dy / d;
        fx.set(nodes[i], fx.get(nodes[i])! + ux * rep);
        fy.set(nodes[i], fy.get(nodes[i])! + uy * rep);
        fx.set(nodes[j], fx.get(nodes[j])! - ux * rep);
        fy.set(nodes[j], fy.get(nodes[j])! - uy * rep);
      }
    }
    // 弹簧（只沿截至 cursor 章活动的边；静止长 = 强度越大越近）
    for (const e of activeEdges) {
      const a = sim.get(e.a);
      const b = sim.get(e.b);
      if (!a || !b) continue;
      const rest = 64 + (10 - Math.max(0, Math.min(10, e.strength))) * 11;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 0.01;
      const f = 0.03 * (d - rest);
      const ux = dx / d;
      const uy = dy / d;
      fx.set(e.a, fx.get(e.a)! + ux * f);
      fy.set(e.a, fy.get(e.a)! + uy * f);
      fx.set(e.b, fx.get(e.b)! - ux * f);
      fy.set(e.b, fy.get(e.b)! - uy * f);
    }
    // 积分 + 阻尼 + 边界
    let maxv = 0;
    for (const nm of nodes) {
      const p = sim.get(nm)!;
      if (p.fixed) {
        p.vx = 0;
        p.vy = 0;
        continue;
      }
      p.vx = (p.vx + fx.get(nm)!) * 0.85;
      p.vy = (p.vy + fy.get(nm)!) * 0.85;
      p.vx = Math.max(-8, Math.min(8, p.vx));
      p.vy = Math.max(-8, Math.min(8, p.vy));
      p.x = Math.max(PAD, Math.min(W - PAD, p.x + p.vx));
      p.y = Math.max(PAD, Math.min(H - PAD, p.y + p.vy));
      maxv = Math.max(maxv, Math.abs(p.vx), Math.abs(p.vy));
    }
    return maxv;
  }

  function toSvg(clientX: number, clientY: number): { x: number; y: number } {
    const svg = svgRef.current;
    if (!svg || !svg.getScreenCTM) return { x: 0, y: 0 };
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const loc = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    return { x: loc.x, y: loc.y };
  }

  function onNodeDown(name: string, e: React.PointerEvent) {
    e.stopPropagation();
    dragRef.current = name;
    const p = simRef.current.get(name);
    if (p) p.fixed = true;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    if (rafRef.current == null) startSim();
  }

  function onMove(e: React.PointerEvent) {
    const name = dragRef.current;
    if (!name) return;
    const { x, y } = toSvg(e.clientX, e.clientY);
    const p = simRef.current.get(name);
    if (p) {
      p.x = Math.max(PAD, Math.min(W - PAD, x));
      p.y = Math.max(PAD, Math.min(H - PAD, y));
      p.vx = 0;
      p.vy = 0;
    }
    setFrame((f) => f + 1);
  }

  function onUp() {
    const name = dragRef.current;
    if (name) {
      const p = simRef.current.get(name);
      if (p) p.fixed = false;
    }
    dragRef.current = null;
    coolRef.current = 0;
    if (rafRef.current == null && view === "snapshot") startSim();
  }

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
          给冻住的关系网加一根时间轴——拖到第几章，就看截至那一刻谁和谁多亲近；选一对人，看他们的关系怎么一章一章走到这一步。每个转折点都钉得到原文。
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

  const sim = simRef.current;
  const cur = selRel != null ? relations[selRel] : null;
  const tp = cur && selTp != null ? cur.turning_points[selTp] : null;
  const totalTurns = relations.reduce((s, r) => s + r.turning_points.length, 0);
  const verifiedTurns = relations.reduce(
    (s, r) => s + r.turning_points.filter((t) => t.verified).length,
    0,
  );

  // ---- 单对曲线视图几何 ----
  const curveW = W;
  const curveH = 260;
  const cPadL = 34;
  const cPadR = 16;
  const cPadT = 16;
  const cPadB = 28;
  const innerW = curveW - cPadL - cPadR;
  const innerH = curveH - cPadT - cPadB;
  const chSpan = Math.max(1, maxCh - minCh);
  const cx = (ch: number) => cPadL + ((ch - minCh) / chSpan) * innerW;
  const cy = (s: number) =>
    cPadT + innerH - (Math.max(0, Math.min(10, s)) / 10) * innerH;
  const curvePts =
    cur && cur.points.length > 0
      ? cur.points.map((p) => `${cx(p.chapter)},${cy(p.strength)}`).join(" ")
      : "";

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          关系演变
        </h3>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setView("snapshot")}
            className={`text-xs px-2 py-1 rounded border transition-colors ${
              view === "snapshot"
                ? "border-[var(--color-seal)] text-[var(--color-seal)]"
                : "border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)]"
            }`}
          >
            时间轴快照
          </button>
          <button
            type="button"
            onClick={() => setView("curve")}
            className={`text-xs px-2 py-1 rounded border transition-colors ${
              view === "curve"
                ? "border-[var(--color-seal)] text-[var(--color-seal)]"
                : "border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)]"
            }`}
          >
            单对曲线
          </button>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
          >
            {loading ? "重出中…" : "重新生成"}
          </button>
        </div>
      </div>

      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        {relations.length} 对关系、{totalTurns} 个转折（原文核验 {verifiedTurns}/
        {totalTurns}）。
        {view === "snapshot"
          ? "拖下面的时间轴，关系网随章节变——连线越粗 = 截至此章越亲密；早章关系少，往后铺开。可拖动节点。"
          : "选一对关系看它的强度逐章曲线，曲线上的点是转折，点转折看原文。"}
      </p>

      {!loading && <RunStats trace={trace} note={`${relations.length} 对关系`} />}

      {view === "snapshot" ? (
        <>
          {/* 时间轴拖动条 */}
          <div className="flex items-center gap-3 my-3">
            <span className="text-xs text-[var(--color-ink-muted)] shrink-0">
              第 {minCh} 章
            </span>
            <input
              type="range"
              min={minCh}
              max={maxCh}
              value={cursor}
              onChange={(e) => setCursor(Number(e.target.value))}
              className="flex-1 accent-[var(--color-seal)]"
              aria-label="时间轴：拖到第几章"
            />
            <span
              className="text-sm font-bold shrink-0"
              style={{ color: "var(--color-seal)", fontFamily: "var(--font-display)" }}
            >
              截至第 {cursor} 章
            </span>
          </div>

          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            className="w-full border border-[var(--color-rule)] rounded touch-none"
            style={{ maxHeight: 540, background: "#0f1730" }}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerLeave={onUp}
          >
            {/* 星图：截至此章的关系网,人物=星、连线=星座(跟人物关系图同族同皮)。闪烁纯 CSS。 */}
            <style>{`@keyframes rt-twinkle{0%,100%{opacity:.6}50%{opacity:1}}`}</style>
            {/* 活动边：星座连线 */}
            {activeEdges.map((e, i) => {
              const a = sim.get(e.a);
              const b = sim.get(e.b);
              if (!a || !b) return null;
              return (
                <line
                  key={`e-${e.a}-${e.b}-${i}`}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke="#8190b0"
                  strokeWidth={edgeWidth(e.strength)}
                  strokeLinecap="round"
                  opacity={0.32 + (Math.max(0, Math.min(10, e.strength)) / 10) * 0.5}
                />
              );
            })}
            {/* 节点：只画截至此章已登场的（有活动边的）+ 度数为 0 的暗示性留位 */}
            {nodes.map((name) => {
              const p = sim.get(name);
              if (!p) return null;
              const deg = activeEdges.filter(
                (e) => e.a === name || e.b === name,
              ).length;
              const present = deg > 0;
              const r = 6 + Math.min(9, deg * 1.6);
              return (
                <g
                  key={`n-${name}`}
                  style={{ cursor: "grab" }}
                  onPointerDown={(ev) => onNodeDown(name, ev)}
                  opacity={present ? 1 : 0.18}
                >
                  {present ? (
                    <>
                      <circle cx={p.x} cy={p.y} r={r * 2.3} fill="var(--color-seal)" opacity={0.13} />
                      <line x1={p.x - r * 1.8} y1={p.y} x2={p.x + r * 1.8} y2={p.y} stroke="var(--color-seal)" strokeWidth={0.8} opacity={0.45} />
                      <line x1={p.x} y1={p.y - r * 1.8} x2={p.x} y2={p.y + r * 1.8} stroke="var(--color-seal)" strokeWidth={0.8} opacity={0.45} />
                      <circle
                        cx={p.x}
                        cy={p.y}
                        r={r}
                        fill="var(--color-seal)"
                        stroke="#fdf6e3"
                        strokeWidth={0.9}
                        style={{ animation: `rt-twinkle ${2.4 + (deg % 4) * 0.7}s ease-in-out infinite` }}
                      />
                      <text
                        x={p.x}
                        y={p.y - r - 5}
                        textAnchor="middle"
                        fontSize={12}
                        fill="#e8e0cf"
                        style={{ fontFamily: "var(--font-display)", pointerEvents: "none" }}
                      >
                        {name}
                      </text>
                    </>
                  ) : (
                    <circle cx={p.x} cy={p.y} r={4} fill="#6b7a99" opacity={0.4} />
                  )}
                </g>
              );
            })}
          </svg>
        </>
      ) : (
        <>
          {/* 选一对关系 */}
          <div className="flex flex-wrap gap-1.5 my-3">
            {relations.map((r, i) => (
              <button
                key={`rel-${r.a}-${r.b}-${i}`}
                type="button"
                onClick={() => {
                  setSelRel(i);
                  setSelTp(null);
                }}
                className={`text-xs px-2 py-1 rounded border transition-colors ${
                  selRel === i
                    ? "border-[var(--color-seal)] text-[var(--color-seal)]"
                    : "border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)]"
                }`}
              >
                {r.a}—{r.b}
              </button>
            ))}
          </div>

          {cur ? (
            <>
              <svg
                viewBox={`0 0 ${curveW} ${curveH}`}
                className="w-full border border-[var(--color-rule)] rounded bg-white"
              >
                {/* 强度参考横线 */}
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
                {/* 强度折线 */}
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
                {/* 强度点 */}
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
                {/* 转折点：竖线 + 标记，verified=false 淡化 */}
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
                        stroke={
                          active ? "var(--color-seal)" : "var(--color-ink-muted)"
                        }
                        strokeWidth={active ? 1.2 : 0.7}
                        strokeDasharray={t.verified ? undefined : "3 3"}
                        opacity={t.verified ? (active ? 0.7 : 0.4) : 0.25}
                      />
                      <circle
                        cx={x}
                        cy={y}
                        r={active ? 6 : 4.5}
                        fill={
                          t.verified ? "var(--color-seal)" : "var(--color-paper)"
                        }
                        stroke="var(--color-seal)"
                        strokeWidth={t.verified ? 0 : 1.4}
                        opacity={t.verified ? 0.95 : 0.6}
                        style={{ cursor: "pointer" }}
                        onClick={() => setSelTp(i)}
                      />
                    </g>
                  );
                })}
                {/* 章号刻度（首尾 + 每个转折章） */}
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
            </>
          ) : (
            <p className="my-6 text-sm text-[var(--color-ink-muted)]">
              选一对关系，看它的强度怎么一章章走到这一步。
            </p>
          )}
        </>
      )}

      {/* 转折详情：点原文 */}
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

      {loading && <RunningProcess label="重出关系演变" />}
    </div>
  );
}
