// ---------------------------------------------------------------------------
// CharacterFlow — 人物叙事流图 / storyline（WP-character-narrative-flow，probe GO）
//
// 点生成 → 调 /api/agent/character-flow（整本进上下文逐章抽同场结构）→ 自写 SVG storyline：
// 横轴 = 章节序，每人一条横线穿过全书；同章同场的人物纵向聚拢成一束、不同场分开；
// 退场线止、登场线起。线粗 = 该章戏份（出场 + 同场对密度）。hover/点同场束看原文。
//
// 排线纵向位置用轻量力学松弛（同场对相吸 + 同列防重叠 + 锚回基线），rAF 驱动，冷却后停、
// 带硬帧上限——照 CharacterGraph 那套防 CPU 空转。不引重图库（CPU-only）。
// evidence-first：verified=false 的同场束画虚线灰，核不过不当实线画。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { usePanZoom } from "./usePanZoom";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { SealButton } from "./SealButton";

interface FlowPair {
  a: string;
  b: string;
  // 章脉转向(出路 B)后同场对只到章级锚,逐字证据点开现取——下面几项不再 upfront 给。
  evidence?: string;
  verified?: boolean;
  match_score?: number;
  chapter?: number;
}

// 点开某条同场对时按需取那一句原文(/agent/spine-evidence,纯检索)。
interface PairEvidence {
  loading: boolean;
  text: string;
  found: boolean;
}

interface FlowChapter {
  chapter: number;
  present: string[];
  pairs: FlowPair[];
}

interface CharacterFlowProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

const W = 880;
const H_MIN = 520;
const LANE_H = 18; // 单条泳道纵向占高:泳道多就把画布撑高(不挤成发丝),同花鸟高度自适应
const PAD_LEFT = 96; // 左边给人名留位
const PAD_RIGHT = 24;
const PAD_TOP = 28;
const PAD_BOTTOM = 28;

// storyline 是横向泳道：每人一条线穿过全书，画不下几百条（一百多回的书上百号人，全铺成
// 泳道会糊成发丝、力学松弛也卡）。所以按出场频次取前 N 个主要角色——这是 storyline 格式的
// 固有约束，不是关系图那种该去掉的帽。caption 透明写「主要 N 人 / 全书共 M 人」。
// 18 太少（原值），抬到 40：泳道还排得开、又能看到更多主要角色。
const TOP_CHARS = 40;

// 选中的同场束：唯一标识 = 章号 + 两人名
interface SelectedPair {
  chapter: number;
  a: string;
  b: string;
}

// 一个人在一章的纵向松弛位置（基线 + 当前偏移）
interface LaneNode {
  y: number; // 当前 y（动画中变）
  vy: number; // 纵向速度
  base: number; // 基线 y（这人的默认 lane）
}

export function CharacterFlow({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: CharacterFlowProps) {
  const [chapters, setChapters] = useState<FlowChapter[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [selected, setSelected] = useState<SelectedPair | null>(null);
  const [selEv, setSelEv] = useState<PairEvidence | null>(null);
  const [hoverChar, setHoverChar] = useState<string | null>(null);

  // 选中某条同场对 → 按需调 /agent/spine-evidence 取那一章里支撑这对人的那句原文(纯检索,不要 key)。
  useEffect(() => {
    if (!selected) {
      setSelEv(null);
      return;
    }
    let cancelled = false;
    setSelEv({ loading: true, text: "", found: false });
    (async () => {
      try {
        const resp = await fetch("/api/agent/spine-evidence", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            book_session_id: sessionId,
            chapter: selected.chapter,
            kind: "pair",
            a: selected.a,
            b: selected.b,
          }),
        });
        const data = (await resp.json()) as { evidence?: string; found?: boolean };
        if (!cancelled) {
          setSelEv({ loading: false, text: data.evidence ?? "", found: !!data.found });
        }
      } catch {
        if (!cancelled) setSelEv({ loading: false, text: "", found: false });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected, sessionId]);

  // 松弛动画：每个 (人, 章) 一个 LaneNode；rAF 驱动，冷却 / 硬帧上限停
  const simRef = useRef<Map<string, LaneNode>>(new Map());
  const rafRef = useRef<number | null>(null);
  const coolRef = useRef(0);
  const [, setFrame] = useState(0);

  async function load() {
    setLoading(true);
    setError(null);
    setSelected(null);
    setHoverChar(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/character-flow", {
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
        chapters: FlowChapter[];
        scanned?: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      if (!data.chapters || data.chapters.length === 0) {
        setError("没抽出叙事流，稍后重试。");
      } else {
        setChapters([...data.chapters].sort((p, q) => p.chapter - q.chapter));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 全书出场总人数（给说明用——穷尽化后可能上百，图里只画前 TOP_CHARS 个）
  const totalCast = useMemo(() => {
    if (!chapters) return 0;
    const all = new Set<string>();
    for (const c of chapters) for (const name of c.present) all.add(name);
    return all.size;
  }, [chapters]);

  // 画图用的视图：只留出场最频繁的前 TOP_CHARS 个角色，pairs 两端都在内才保留。
  // 长尾次要人物（一两章露个脸）不进 storyline——否则泳道糊成一团、力学松弛也卡。
  const view = useMemo(() => {
    if (!chapters) return null;
    const freq = new Map<string, number>();
    for (const c of chapters)
      for (const name of c.present) freq.set(name, (freq.get(name) ?? 0) + 1);
    const kept = new Set(
      [...freq.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, TOP_CHARS)
        .map(([name]) => name),
    );
    return chapters.map((c) => ({
      chapter: c.chapter,
      present: c.present.filter((n) => kept.has(n)),
      pairs: c.pairs.filter((p) => kept.has(p.a) && kept.has(p.b)),
    }));
  }, [chapters]);

  // ----- 布局派生量：人物 lane 基线、各章 x、每人出现区间、每章戏份 -----
  const layout = useMemo(() => {
    if (!view) return null;

    // 每人首/末出现章 index（登场线起、退场线止）
    const firstIdx = new Map<string, number>();
    const lastIdx = new Map<string, number>();
    view.forEach((c, i) => {
      for (const name of c.present) {
        if (!firstIdx.has(name)) firstIdx.set(name, i);
        lastIdx.set(name, i);
      }
    });

    // 人物按总出场次数排序定 lane 顺序（戏多的靠中间更稳，这里简单按登场顺序+频次）
    const freq = new Map<string, number>();
    for (const c of view)
      for (const name of c.present) freq.set(name, (freq.get(name) ?? 0) + 1);
    const names = [...firstIdx.keys()].sort((a, b) => {
      const fa = firstIdx.get(a)!;
      const fb = firstIdx.get(b)!;
      if (fa !== fb) return fa - fb; // 先按登场早晚
      return (freq.get(b) ?? 0) - (freq.get(a) ?? 0);
    });

    // 画布高随泳道数长:泳道少用 H_MIN,多了每条留 LANE_H,免得几十条挤成发丝(viewBox 按容器缩放)
    const H = Math.max(H_MIN, names.length * LANE_H + PAD_TOP + PAD_BOTTOM);

    // lane 基线 y：纵向均分
    const lane = new Map<string, number>();
    const plotTop = PAD_TOP;
    const plotBottom = H - PAD_BOTTOM;
    const span = plotBottom - plotTop;
    const m = Math.max(1, names.length);
    names.forEach((name, i) => {
      lane.set(name, plotTop + (span * (i + 0.5)) / m);
    });

    // 各章 x
    const n = view.length;
    const colW = (W - PAD_LEFT - PAD_RIGHT) / Math.max(1, n - 1 || 1);
    const xAt = (i: number) => PAD_LEFT + (n === 1 ? 0 : i * colW);

    // 每人每章戏份（出场=1 + 同场对数）→ 线粗
    const screen = new Map<string, number>(); // key = name|idx
    view.forEach((c, i) => {
      const pairCount = new Map<string, number>();
      for (const pr of c.pairs) {
        pairCount.set(pr.a, (pairCount.get(pr.a) ?? 0) + 1);
        pairCount.set(pr.b, (pairCount.get(pr.b) ?? 0) + 1);
      }
      for (const name of c.present) {
        screen.set(`${name}|${i}`, 1 + (pairCount.get(name) ?? 0));
      }
    });

    return { names, lane, firstIdx, lastIdx, xAt, n, screen, H };
  }, [view]);

  // 动态画布高(泳道多就高);layout 未就绪时退 H_MIN。step / 渲染 / viewBox 都用这个。
  const H = layout?.H ?? H_MIN;

  // pan/zoom + 双指 pinch（移动端）：大书章数多、viewBox 宽，手机上捏合才看得清谁在哪场。
  // 注：hook 的 view 改名 zoomView，避开下面已有的 view（章数据数组）。
  const svgRef = useRef<SVGSVGElement | null>(null);
  const {
    view: zoomView,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
    onWheel,
    resetView,
  } = usePanZoom(svgRef, { width: W, height: H });

  // 初始化 LaneNode + 启动松弛动画
  useEffect(() => {
    if (!view || !layout) return;
    const sim = new Map<string, LaneNode>();
    view.forEach((c, i) => {
      for (const name of c.present) {
        const base = layout.lane.get(name)!;
        sim.set(`${name}|${i}`, { y: base, vy: 0, base });
      }
    });
    simRef.current = sim;
    coolRef.current = 0;
    setFrame((f) => f + 1); // 立刻按初始坐标画一帧——别等 rAF(后台标签 / 省电模式 rAF 会被掐,否则叙事流空白)
    startSim();
    return stopSim;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, layout]);

  function stopSim() {
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
  }

  function startSim() {
    stopSim();
    coolRef.current = 0;
    let ticks = 0; // 硬上限兜底：万一不收敛也强制停，绝不无限空转烧 CPU
    const tick = () => {
      const maxv = step();
      setFrame((f) => f + 1);
      ticks += 1;
      if (maxv < 0.25) coolRef.current += 1;
      else coolRef.current = 0;
      if (coolRef.current > 30 || ticks > 400) {
        rafRef.current = null; // 冷却（静止）或到硬上限 ~400 帧：停 rAF 省 CPU
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }

  // 一帧纵向松弛：同章同场对相吸（聚束）+ 同章内防重叠 + 锚回基线 + 阻尼
  function step(): number {
    const sim = simRef.current;
    const cur = view;
    if (!sim || !cur || !layout) return 0;
    const fy = new Map<string, number>();
    for (const k of sim.keys()) fy.set(k, 0);

    cur.forEach((c, i) => {
      // 同场对相吸：把这章同场的两人纵向拉近 → 视觉聚束
      for (const pr of c.pairs) {
        const ka = `${pr.a}|${i}`;
        const kb = `${pr.b}|${i}`;
        const na = sim.get(ka);
        const nb = sim.get(kb);
        if (!na || !nb) continue;
        const dy = nb.y - na.y;
        const f = 0.04 * dy;
        fy.set(ka, (fy.get(ka) ?? 0) + f);
        fy.set(kb, (fy.get(kb) ?? 0) - f);
      }
      // 同章内防重叠：present 里彼此太近的互推开
      const present = c.present;
      for (let p = 0; p < present.length; p++) {
        for (let q = p + 1; q < present.length; q++) {
          const kp = `${present[p]}|${i}`;
          const kq = `${present[q]}|${i}`;
          const np = sim.get(kp);
          const nq = sim.get(kq);
          if (!np || !nq) continue;
          const dy = np.y - nq.y;
          const dist = Math.abs(dy) || 0.01;
          const MIN = 16;
          if (dist < MIN) {
            const push = ((MIN - dist) / MIN) * 1.6 * (dy >= 0 ? 1 : -1);
            fy.set(kp, (fy.get(kp) ?? 0) + push);
            fy.set(kq, (fy.get(kq) ?? 0) - push);
          }
        }
      }
    });

    // 锚回基线（别飘太远，保整体可读）+ 积分 + 阻尼 + 边界
    let maxv = 0;
    for (const [k, node] of sim) {
      fy.set(k, (fy.get(k) ?? 0) + (node.base - node.y) * 0.02);
      node.vy = (node.vy + fy.get(k)!) * 0.82;
      node.vy = Math.max(-6, Math.min(6, node.vy));
      node.y = Math.max(PAD_TOP, Math.min(H - PAD_BOTTOM, node.y + node.vy));
      maxv = Math.max(maxv, Math.abs(node.vy));
    }
    return maxv;
  }

  if (!view || !layout) {
    // 空态（还没生成）：统一入口卡（视觉表现根治 · FeatureEntryCard）
    return (
      <FeatureEntryCard
        title="人物叙事流"
        lead="每个人一条横线穿过全书章节，同章同场聚成一束、各自行动分开、退场线止。一眼看见谁何时入场、哪几章是群戏。"
        actionLabel="生成人物叙事流"
        loadingLabel="读全书抽叙事流中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书抽同场结构，约 1 分钟；命中缓存秒出"
        error={error}
      >
        {loading && (
          <RunningProcess
            label="读全书抽人物叙事流"
            hint="整本书喂进模型逐章抽同场结构，每条同场判定都回原文核验，约 1 分钟。"
          />
        )}
      </FeatureEntryCard>
    );
  }

  const sim = simRef.current;
  const { names, firstIdx, lastIdx, xAt, n, screen } = layout;
  const yOf = (name: string, i: number) =>
    sim.get(`${name}|${i}`)?.y ?? layout.lane.get(name) ?? H / 2;

  const totalPairs = view.reduce((acc, c) => acc + c.pairs.length, 0);

  // 选中对在数据里若自带 evidence(demo 老形态 / 真后端没有),当现取失败时的回退。
  const selUpfront = selected
    ? view
        .find((c) => c.chapter === selected.chapter)
        ?.pairs.find(
          (p) =>
            (p.a === selected.a && p.b === selected.b) ||
            (p.a === selected.b && p.b === selected.a),
        )?.evidence
    : undefined;

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          人物叙事流
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
        {totalCast > names.length
          ? `图中主要 ${names.length} 人 / 全书共 ${totalCast} 人`
          : `${names.length} 个人物`}
        、{n} 章（{totalPairs} 条同场）。横线穿全书、线越粗这章戏越多；同场处两线靠拢成束，点束看那一章的原文出处（点开现取）。
      </p>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full border border-[var(--color-rule)] rounded touch-none"
        style={{ maxHeight: 520, background: "var(--color-paper)" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onPointerLeave={onPointerUp}
        onWheel={onWheel}
      >
        {/* 缩放平移层：章刻度 + 泳道 + 同场束都在这个 <g> 里，整图能缩能拖、双指捏合看细节 */}
        <g transform={`translate(${zoomView.tx} ${zoomView.ty}) scale(${zoomView.k})`}>
        {/* 章号刻度（每隔几章标一个，避免拥挤） */}
        {view.map((c, i) =>
          n <= 24 || i % 4 === 0 ? (
            <text
              key={`x-${c.chapter}`}
              x={xAt(i)}
              y={H - 8}
              textAnchor="middle"
              fontSize={9}
              fill="var(--color-ink-muted)"
            >
              {c.chapter}
            </text>
          ) : null,
        )}

        {/* 每人一条线：只画出现区间 [first, last] 的折线 */}
        {names.map((name) => {
          const a = firstIdx.get(name)!;
          const b = lastIdx.get(name)!;
          const pts: string[] = [];
          for (let i = a; i <= b; i++) {
            // 不在 present 的中间章用基线 y 兜底（线不断，但 lane 回归基线）
            pts.push(`${xAt(i)},${yOf(name, i)}`);
          }
          const dimmed = hoverChar != null && hoverChar !== name;
          // 线宽取区间内最大戏份（粗细随章变靠分段画太碎，这里整条取代表值更稳）
          let maxScreen = 1;
          for (let i = a; i <= b; i++)
            maxScreen = Math.max(maxScreen, screen.get(`${name}|${i}`) ?? 1);
          const lw = 1.2 + Math.min(5, maxScreen) * 0.7;
          const midY = yOf(name, Math.floor((a + b) / 2));
          return (
            <g
              key={`line-${name}`}
              onPointerEnter={() => setHoverChar(name)}
              onPointerLeave={() => setHoverChar(null)}
              style={{ cursor: "pointer" }}
            >
              <polyline
                points={pts.join(" ")}
                fill="none"
                stroke="var(--color-seal)"
                strokeWidth={lw}
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={dimmed ? 0.18 : 0.78}
              />
              {/* 登场端点（线起头）小圆点 */}
              <circle
                cx={xAt(a)}
                cy={yOf(name, a)}
                r={2.4}
                fill="var(--color-seal)"
                opacity={dimmed ? 0.2 : 0.9}
              />
              <text
                x={PAD_LEFT - 8}
                y={midY + 3}
                textAnchor="end"
                fontSize={11}
                fill={dimmed ? "var(--color-ink-muted)" : "var(--color-ink)"}
                style={{
                  fontFamily: "var(--font-display)",
                  pointerEvents: "none",
                }}
              >
                {name}
              </text>
            </g>
          );
        })}

        {/* 同场束：每章每条 pair，在该章 x 处画一段连接两人 lane 的竖向束线 */}
        {view.map((c, i) =>
          c.pairs.map((pr, j) => {
            const ya = yOf(pr.a, i);
            const yb = yOf(pr.b, i);
            const x = xAt(i);
            const active =
              selected != null &&
              selected.chapter === c.chapter &&
              ((pr.a === selected.a && pr.b === selected.b) ||
                (pr.a === selected.b && pr.b === selected.a));
            return (
              <g key={`bundle-${c.chapter}-${j}`}>
                <line
                  x1={x}
                  y1={ya}
                  x2={x}
                  y2={yb}
                  stroke={active ? "var(--color-seal)" : "var(--color-ink-muted)"}
                  strokeWidth={active ? 2.6 : 1.4}
                  strokeLinecap="round"
                  opacity={active ? 1 : 0.6}
                />
                {/* 透明粗线作点击热区 */}
                <line
                  x1={x}
                  y1={ya}
                  x2={x}
                  y2={yb}
                  stroke="transparent"
                  strokeWidth={12}
                  style={{ cursor: "pointer" }}
                  onClick={() =>
                    setSelected({ chapter: c.chapter, a: pr.a, b: pr.b })
                  }
                />
              </g>
            );
          }),
        )}
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

      {selected && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            第 {selected.chapter} 章 · {selected.a} 与 {selected.b} 同场
          </p>
          <p className="mt-1 text-sm text-[var(--color-ink)] leading-relaxed">
            {selEv?.loading
              ? "正在从这一章原文里找出处…"
              : (selEv?.found ? selEv.text : selUpfront) ||
                "这一章原文里没比对到支撑这对同场的句子。"}
          </p>
          {selEv && !selEv.loading && (selEv.found || selUpfront) && (
            <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
              原文出处 · 第 {selected.chapter} 章（点开现取）
            </p>
          )}
        </div>
      )}

      {loading ? (
        <RunningProcess label="重出人物叙事流" />
      ) : (
        <RunStats trace={trace} note={`${totalPairs} 条同场`} />
      )}
    </div>
  );
}
