// ---------------------------------------------------------------------------
// CharacterGraph — 人物 / 概念关系图（WP-character-graph，exp-013/014 GO）
//
// 点生成 → 调 /api/agent/character-graph（整本进上下文抽结构化图）→ **实时动画力导向**
// 布局：圆圈自动散开、可拖动；连线按关系亲疏（strength 1-5）调远近 + 粗细。点边看原文。
// 自写力学模拟（弹簧 + 斥力 + 阻尼），rAF 驱动，冷却后停（省 CPU）；不引重图库（CPU-only）。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  strength: number; // 亲疏 1-5（5 最紧密）
  evidence: string;
  verified: boolean;
  chapter: number;
  match_score: number;
}

interface GraphData {
  nodes: string[];
  edges: GraphEdge[];
  trace: Record<string, unknown>;
}

interface CharacterGraphProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

const W = 760;
const H = 560;
const PAD = 46;

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  fixed: boolean;
}

// 关系亲疏 → 弹簧静止长度：越紧密拉得越近（strength 5≈64，1≈168）
const restLen = (s: number) => 64 + (5 - Math.max(1, Math.min(5, s))) * 26;
// 关系亲疏 → 连线粗细（紧密更粗）
const edgeWidth = (s: number) => 1.2 + Math.max(1, Math.min(5, s)) * 0.55;

export function CharacterGraph({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: CharacterGraphProps) {
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [unit, setUnit] = useState<"person" | "concept">("person");

  const svgRef = useRef<SVGSVGElement | null>(null);
  const simRef = useRef<Map<string, Node>>(new Map());
  const rafRef = useRef<number | null>(null);
  const coolRef = useRef(0);
  const dragRef = useRef<string | null>(null);
  const [, setFrame] = useState(0);

  async function load(u: "person" | "concept") {
    setUnit(u);
    setLoading(true);
    setError(null);
    setSelected(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        unit: u,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/character-graph", {
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
      setData((await resp.json()) as GraphData);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const degree = useMemo(() => {
    const d = new Map<string, number>();
    if (data) {
      for (const e of data.edges) {
        d.set(e.source, (d.get(e.source) ?? 0) + 1);
        d.set(e.target, (d.get(e.target) ?? 0) + 1);
      }
    }
    return d;
  }, [data]);

  // 初始化节点（圆周）+ 启动动画模拟
  useEffect(() => {
    if (!data) return;
    const sim = new Map<string, Node>();
    const n = Math.max(1, data.nodes.length);
    data.nodes.forEach((name, i) => {
      const a = (2 * Math.PI * i) / n;
      sim.set(name, {
        x: W / 2 + Math.cos(a) * W * 0.28,
        y: H / 2 + Math.sin(a) * H * 0.28,
        vx: 0,
        vy: 0,
        fixed: false,
      });
    });
    simRef.current = sim;
    coolRef.current = 0;
    startSim();
    return stopSim;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  function stopSim() {
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
  }

  function startSim() {
    stopSim();
    coolRef.current = 0;
    let ticks = 0; // 硬上限兜底：力学万一不收敛也强制停，绝不无限空转烧 CPU
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

  // 一帧物理：斥力(全对) + 弹簧(沿边，静止长由亲疏定) + 居中 + 阻尼
  function step(): number {
    const sim = simRef.current;
    const cur = data;
    if (!sim || !cur) return 0;
    const names = cur.nodes;
    const fx = new Map<string, number>();
    const fy = new Map<string, number>();
    for (const nm of names) {
      const p = sim.get(nm)!;
      fx.set(nm, (W / 2 - p.x) * 0.008); // 居中
      fy.set(nm, (H / 2 - p.y) * 0.008);
    }
    // 斥力
    for (let i = 0; i < names.length; i++) {
      for (let j = i + 1; j < names.length; j++) {
        const a = sim.get(names[i])!;
        const b = sim.get(names[j])!;
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
        fx.set(names[i], fx.get(names[i])! + ux * rep);
        fy.set(names[i], fy.get(names[i])! + uy * rep);
        fx.set(names[j], fx.get(names[j])! - ux * rep);
        fy.set(names[j], fy.get(names[j])! - uy * rep);
      }
    }
    // 弹簧（沿边，静止长 = restLen(strength)）
    for (const e of cur.edges) {
      const a = sim.get(e.source);
      const b = sim.get(e.target);
      if (!a || !b) continue;
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 0.01;
      const f = 0.03 * (d - restLen(e.strength));
      const ux = dx / d;
      const uy = dy / d;
      fx.set(e.source, fx.get(e.source)! + ux * f);
      fy.set(e.source, fy.get(e.source)! + uy * f);
      fx.set(e.target, fx.get(e.target)! - ux * f);
      fy.set(e.target, fy.get(e.target)! - uy * f);
    }
    // 积分 + 阻尼 + 边界
    let maxv = 0;
    for (const nm of names) {
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
    if (rafRef.current == null) startSim();
  }

  if (!data) {
    const cardCls =
      "flex flex-col items-start gap-1.5 p-4 rounded-lg border text-left transition-colors " +
      "border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] " +
      "disabled:opacity-50 disabled:hover:border-[var(--color-rule)]";
    return (
      <div className="pt-4">
        <p className="text-sm text-[var(--color-ink-muted)] mb-4">
          把整本书的关系网画成可拖动的动态图——连线越粗、节点越近 = 关系越紧密，每条边点得到原文。挑一种生成：
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <button
            type="button"
            onClick={() => load("person")}
            disabled={loading || !apiKey}
            className={cardCls}
          >
            <svg
              width="30"
              height="30"
              viewBox="0 0 28 28"
              fill="none"
              stroke="var(--color-seal)"
              strokeWidth="1.6"
              strokeLinecap="round"
            >
              <circle cx="10" cy="9" r="4" />
              <circle cx="20.5" cy="12" r="3.2" />
              <path d="M3 24c0-4 3.4-6.5 7-6.5s7 2.5 7 6.5" />
              <path d="M18 24c.4-3 2.6-4.8 5.2-4.8" />
            </svg>
            <span className="text-base font-bold text-[var(--color-ink)]">
              {loading && unit === "person" ? "抽取中…" : "人物关系图"}
            </span>
            <span className="text-xs text-[var(--color-ink-muted)]">
              谁和谁、什么关系、多亲近
            </span>
            <span className="text-xs text-[var(--color-seal)]">
              适合 小说 · 历史 · 传记
            </span>
          </button>
          <button
            type="button"
            onClick={() => load("concept")}
            disabled={loading || !apiKey}
            className={cardCls}
          >
            <svg
              width="30"
              height="30"
              viewBox="0 0 28 28"
              fill="none"
              stroke="var(--color-seal)"
              strokeWidth="1.6"
              strokeLinecap="round"
            >
              <path d="M7.5 9.2l11-1.4M8 11l5 7.5M20 9.3l-5.6 9" />
              <circle cx="6" cy="8" r="2.6" fill="var(--color-paper)" />
              <circle cx="22" cy="7" r="2.6" fill="var(--color-paper)" />
              <circle cx="14" cy="21" r="2.6" fill="var(--color-paper)" />
            </svg>
            <span className="text-base font-bold text-[var(--color-ink)]">
              {loading && unit === "concept" ? "抽取中…" : "概念关系图"}
            </span>
            <span className="text-xs text-[var(--color-ink-muted)]">
              核心概念怎么勾连、多紧密
            </span>
            <span className="text-xs text-[var(--color-seal)]">
              适合 理论书 · 论文
            </span>
          </button>
        </div>
        {error && (
          <p className="mt-3 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {loading && (
          <RunningProcess
            label={`抽取${unit === "concept" ? "概念" : "人物"}关系图`}
            hint="整本书喂进模型抽关系网——每条边都要回原文核验，约 1 分钟。"
          />
        )}
        {!apiKey && (
          <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
            填了 API key 才能生成。
          </p>
        )}
        <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
          整本书进上下文现抽，约 1 分钟；超大书暂不支持。
        </p>
      </div>
    );
  }

  const sel = selected != null ? data.edges[selected] : null;
  const noun = unit === "concept" ? "概念" : "人物";
  const title = unit === "concept" ? "概念关系图" : "人物关系图";
  const otherUnit = unit === "concept" ? "person" : "concept";
  const otherTitle = unit === "concept" ? "人物关系图" : "概念关系图";
  const sim = simRef.current;

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {title}
        </h3>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => load(unit)}
            disabled={loading}
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
          >
            {loading ? "抽取中…" : "重新生成"}
          </button>
          <button
            type="button"
            onClick={() => load(otherUnit)}
            disabled={loading}
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
          >
            换成{otherTitle}
          </button>
        </div>
      </div>

      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        {data.nodes.length} 个{noun}、{data.edges.length} 条关系（已核验原文{" "}
        {data.edges.filter((e) => e.verified).length} 条）。连线越粗越近 = 越亲密；
        可拖动节点；点边看原文出处。
      </p>

      {!loading && (
        <RunStats trace={data.trace as RunTrace} note={`${data.edges.length} 条关系`} />
      )}

      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full border border-[var(--color-rule)] rounded touch-none"
        style={{ maxHeight: 560, background: "var(--color-paper)" }}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={onUp}
      >
        {/* 边 */}
        {data.edges.map((e, i) => {
          const a = sim.get(e.source);
          const b = sim.get(e.target);
          if (!a || !b) return null;
          const active = selected === i;
          return (
            <g key={`e-${i}`}>
              <line
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={
                  active
                    ? "var(--color-seal)"
                    : e.verified
                      ? "var(--color-ink-muted)"
                      : "#c9c2b6"
                }
                strokeWidth={active ? edgeWidth(e.strength) + 1.5 : edgeWidth(e.strength)}
                strokeLinecap="round"
                strokeDasharray={e.verified ? undefined : "4 3"}
                opacity={active ? 1 : 0.7}
              />
              <line
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="transparent"
                strokeWidth={14}
                style={{ cursor: "pointer" }}
                onClick={() => setSelected(i)}
              />
            </g>
          );
        })}
        {/* 节点 */}
        {data.nodes.map((name) => {
          const p = sim.get(name);
          if (!p) return null;
          const r = 6 + Math.min(9, (degree.get(name) ?? 0) * 1.5);
          return (
            <g
              key={`n-${name}`}
              style={{ cursor: "grab" }}
              onPointerDown={(ev) => onNodeDown(name, ev)}
            >
              <circle
                cx={p.x}
                cy={p.y}
                r={r}
                fill="var(--color-seal)"
                opacity={0.88}
                stroke="var(--color-paper)"
                strokeWidth={1.5}
              />
              <text
                x={p.x}
                y={p.y - r - 4}
                textAnchor="middle"
                fontSize={12}
                fill="var(--color-ink)"
                style={{ fontFamily: "var(--font-display)", pointerEvents: "none" }}
              >
                {name}
              </text>
            </g>
          );
        })}
      </svg>

      {sel && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            {sel.source} — {sel.relation} — {sel.target}
            <span className="ml-2 text-xs font-normal text-[var(--color-seal)]">
              亲疏 {sel.strength}/5
            </span>
          </p>
          <p className="mt-1 text-sm text-[var(--color-ink)] leading-relaxed">
            {sel.evidence || "（这条关系没给出原文片段）"}
          </p>
          <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
            {sel.verified
              ? `原文已核验${sel.chapter > 0 ? ` · 第 ${sel.chapter} 章` : ""}`
              : "原文未在书中比对命中（仅供参考）"}
          </p>
        </div>
      )}
    </div>
  );
}
