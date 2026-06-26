// ---------------------------------------------------------------------------
// CharacterGraph — 人物 / 概念关系图（WP-character-graph，exp-013/014 GO）
//
// 点生成 → 调 /api/agent/character-graph（整本进上下文抽结构化图）→ **实时动画力导向**
// 布局：圆圈自动散开、可拖动；连线按关系亲疏（strength 1-5）调远近 + 粗细。点边看原文。
// 自写力学模拟（弹簧 + 斥力 + 阻尼），rAF 驱动，冷却后停（省 CPU）；不引重图库（CPU-only）。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { NIGHT_SKY, StarNode, StarTwinkleStyle } from "./starSky";

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
  // 点一个人物星子 → 跳到关系演变看他的关系（可选，不传则只能拖动，行为跟以前一样）。
  onSelectPerson?: (name: string) => void;
}

const PAD = 46;

// 默认只渲染戏份最重的前 N 个人物——三国 348 人全量力导向每帧 ~12 万对斥力会卡死。
// 按 degree 取前 N，剩下的折成"还有 N 个次要人物"按钮，点开才全量。力学只算渲染的这些。
const TOP_N = 70;

// 颜色方案 A：节点一律墨色单色，大小=戏份（degree），不再按共现群组多色。
// 夜空底是深色，真墨色（--color-ink）会糊进背景看不见，所以星子用偏暖的星白当"墨色"在夜空里的对应。
const STAR_COLOR = "#d8cfb8";

// 画布按节点数自适应——几百号人挤在小画布会糊成一团，节点多就把画布撑大（给力学更多铺开空间）。
// 上限放到 2400:三国 348 人也铺得开;SVG 按容器宽缩放,逻辑空间大=结构(阵营/主次)散得开。
function canvasSize(nodeCount: number): { w: number; h: number } {
  const w = Math.max(760, Math.min(2400, Math.round(360 + nodeCount * 7)));
  return { w, h: Math.round(w * 0.66) };
}

// 防重叠最小间距:任何两个节点近于此就强分开,免得堆成一坨(节点半径 6~15,留够间隙)。
const MIN_SEP = 30;

// 缩放上下限:太小看不清字、太大一颗星占满屏。
const K_MIN = 0.3;
const K_MAX = 4;

// 视角:缩放比 k + 平移 tx/ty。边和节点都画进 translate(tx ty) scale(k) 的 <g> 里,整图能缩能拖。
interface View {
  k: number;
  tx: number;
  ty: number;
}

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

// 关系类型 → 敌 / 亲 / 中 三类，给边上色（让敌友一眼分明）。
type RelKind = "foe" | "kin" | "neutral";
function relationKind(relation: string): RelKind {
  const r = relation || "";
  if (/敌|政敌|对手|对立|仇|宿敌|交锋|争|叛|反目/.test(r)) return "foe";
  if (/盟|结义|亲|族|父|母|子|女|夫|妻|兄|弟|姐|妹|君臣|主仆|师徒|师|徒|友|挚|同袍|姻/.test(r)) return "kin";
  return "neutral";
}
const EDGE_COLOR: Record<RelKind, string> = {
  foe: "#C0392B", // 敌对 = 红
  kin: "#2E8B6E", // 同盟/亲族 = 青绿
  neutral: "#9A948A", // 一般 = 灰
};
const EDGE_KIND_LABEL: Record<RelKind, string> = { foe: "敌对", kin: "同盟 / 亲族", neutral: "一般" };

// 社区发现(label propagation,按 strength 加权):把关系网分成几个群 ≈ 阵营。
// 纯算法、不调 LLM;颜色方案 A 弃掉了按群上色,群现在只用来布局聚拢(同群往一处拉),近似(三国大致分出魏蜀吴)。
function detectCommunities(nodes: string[], edges: GraphEdge[]): Map<string, number> {
  const adj = new Map<string, [string, number][]>();
  for (const n of nodes) adj.set(n, []);
  for (const e of edges) {
    if (!adj.has(e.source) || !adj.has(e.target)) continue;
    const w = Math.max(1, Math.min(5, e.strength || 3));
    adj.get(e.source)!.push([e.target, w]);
    adj.get(e.target)!.push([e.source, w]);
  }
  const label = new Map<string, string>();
  nodes.forEach((n) => label.set(n, n));
  for (let iter = 0; iter < 12; iter++) {
    let changed = false;
    for (const n of nodes) {
      const nbrs = adj.get(n)!;
      if (nbrs.length === 0) continue;
      const wsum = new Map<string, number>();
      for (const [nb, s] of nbrs) {
        const lb = label.get(nb)!;
        wsum.set(lb, (wsum.get(lb) ?? 0) + s);
      }
      let best = label.get(n)!;
      let bestW = -1;
      for (const [lb, ww] of wsum) {
        if (ww > bestW || (ww === bestW && lb < best)) {
          best = lb;
          bestW = ww;
        }
      }
      if (best !== label.get(n)) {
        label.set(n, best);
        changed = true;
      }
    }
    if (!changed) break;
  }
  // 按群大小降序重映射成 0..k-1(最大的群拿朱砂)
  const sizes = new Map<string, number>();
  for (const n of nodes) sizes.set(label.get(n)!, (sizes.get(label.get(n)!) ?? 0) + 1);
  const order = [...sizes.entries()].sort((a, b) => b[1] - a[1]).map(([lb]) => lb);
  const labToId = new Map(order.map((lb, i) => [lb, i]));
  const out = new Map<string, number>();
  for (const n of nodes) out.set(n, labToId.get(label.get(n)!) ?? 0);
  return out;
}

export function CharacterGraph({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  onSelectPerson,
}: CharacterGraphProps) {
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [selEv, setSelEv] = useState<{ loading: boolean; text: string; found: boolean } | null>(
    null,
  );
  const [unit, setUnit] = useState<"person" | "concept">("person");
  // 视角:缩放 + 平移。默认无缩放无平移,等节点冷却后 fit 一次铺满。
  const [view, setView] = useState<View>({ k: 1, tx: 0, ty: 0 });
  // 默认只渲染戏份前 TOP_N 个;点"展开次要人物"才全量。次要人物多才显示这个开关。
  const [expanded, setExpanded] = useState(false);
  // 鼠标悬停的节点名——人多时只给主要角色标名,hover 任意一颗也临时显名。
  const [hovered, setHovered] = useState<string | null>(null);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const simRef = useRef<Map<string, Node>>(new Map());
  const rafRef = useRef<number | null>(null);
  const coolRef = useRef(0);
  const dragRef = useRef<string | null>(null);
  // 已对当前这批数据做过 fit 没有——只 fit 一次,免得每帧重算抖。
  const fittedRef = useRef(false);
  // 在空白背景按下拖动 = 平移整图;记起点的 SVG 坐标 + 按下那刻的 tx/ty。
  const panRef = useRef<{ sx: number; sy: number; tx: number; ty: number } | null>(null);
  // 记录在某个节点上按下的起点——松手时若几乎没动（是「点」不是「拖」）就当点击，跳关系演变。
  const downRef = useRef<{ name: string; x: number; y: number; moved: boolean } | null>(null);
  const [, setFrame] = useState(0);

  // 选中某条边 → 若边没带 upfront 证据(章脉转向后的人物图,出路 B),按需调
  // /agent/spine-evidence 取那一章里支撑这对人的那句原文;边自带证据(概念图/旧路径)则直接用、不取。
  useEffect(() => {
    const edge = selected != null ? data?.edges[selected] : null;
    if (!edge || edge.evidence) {
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
            chapter: edge.chapter,
            kind: "pair",
            a: edge.source,
            b: edge.target,
          }),
        });
        const d = (await resp.json()) as { evidence?: string; found?: boolean };
        if (!cancelled) setSelEv({ loading: false, text: d.evidence ?? "", found: !!d.found });
      } catch {
        if (!cancelled) setSelEv({ loading: false, text: "", found: false });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected, data, sessionId]);

  // 画布大小随节点数自适应(多就撑大、不糊团);社区发现给每个节点一个阵营 id。
  const { w: W, h: H } = useMemo(() => canvasSize(data?.nodes.length ?? 0), [data]);
  const communities = useMemo(
    () => (data ? detectCommunities(data.nodes, data.edges) : new Map<string, number>()),
    [data],
  );

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

  // 渲染子集:默认只取戏份(degree)前 TOP_N 个人物;点"展开"后才全量。
  // 力学、画节点、画边都只认这个子集——三国 348 人挤进力导向每帧 ~12 万对斥力会卡死,
  // 砍到 70 人后每帧只 ~2400 对,跑得动。剩下的折成按钮(hiddenCount)。
  const rendered = useMemo(() => {
    const empty = {
      nodes: [] as string[],
      nodeSet: new Set<string>(),
      edges: [] as GraphEdge[],
      hiddenCount: 0,
    };
    if (!data) return empty;
    const all = data.nodes;
    let keep: string[];
    if (expanded || all.length <= TOP_N) {
      keep = all;
    } else {
      // 按 degree 降序取前 TOP_N;degree 相同就按原顺序稳定(免得每次抖)。
      keep = [...all]
        .map((nm, i) => ({ nm, dg: degree.get(nm) ?? 0, i }))
        .sort((a, b) => b.dg - a.dg || a.i - b.i)
        .slice(0, TOP_N)
        .map((x) => x.nm);
    }
    const nodeSet = new Set(keep);
    // 只留两端都在子集里的边——否则边会连到没画出来的人。
    const edges = data.edges.filter((e) => nodeSet.has(e.source) && nodeSet.has(e.target));
    return { nodes: keep, nodeSet, edges, hiddenCount: all.length - keep.length };
  }, [data, expanded, degree]);

  // 初始化节点（圆周）+ 启动动画模拟。
  // 依赖 rendered:换数据 或 展开/收起次要人物 都重排一次。展开时已有的节点保留原位(不抖),
  // 新冒出来的次要人物按圆周补进来,再让力学收一次。
  useEffect(() => {
    if (!data) return;
    const prev = simRef.current;
    const sim = new Map<string, Node>();
    const names = rendered.nodes;
    const n = Math.max(1, names.length);
    names.forEach((name, i) => {
      const existing = prev.get(name);
      if (existing) {
        sim.set(name, { ...existing, fixed: false });
        return;
      }
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
    fittedRef.current = false; // 重排了没 fit 过,等冷却后再 fit
    setFrame((f) => f + 1); // 立刻按初始坐标画一帧——别等 rAF（后台标签页 / 省电模式 rAF 会被掐，否则图空白）
    startSim();
    return stopSim;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rendered]);

  // 换数据(不只是展开/收起)时复位视角,免得拿上一批的缩放看新图。展开/收起不复位,保住用户当前视角。
  useEffect(() => {
    setExpanded(false);
    setView({ k: 1, tx: 0, ty: 0 });
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
      if (coolRef.current > 40 || ticks > 1000) {
        rafRef.current = null; // 冷却（静止）或到硬上限 ~600 帧：停 rAF 省 CPU
        // 布局定型了,对这批数据 fit 一次铺满(只第一次,后面拖/缩放不再自动覆盖用户视角)。
        if (!fittedRef.current) {
          fittedRef.current = true;
          fitToBounds();
        }
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }

  // 一帧物理：斥力(渲染子集两两) + 弹簧(沿边，静止长由亲疏定) + 阵营锚 + 阻尼。
  // 只算 rendered 子集——默认 ≤TOP_N 人,斥力 O(n²) 才扛得住。
  function step(): number {
    const sim = simRef.current;
    if (!sim || !data) return 0;
    const names = rendered.nodes;
    const fx = new Map<string, number>();
    const fy = new Map<string, number>();
    // 阵营锚点:前几大社区在画布上沿环分散,各自成员往自己阵营锚拉 → 阵营空间分开、不糊团。
    const ids = [...communities.values()];
    const numC = ids.length ? Math.max(...ids) + 1 : 1;
    const ringN = Math.max(1, Math.min(numC, 6));
    const anchorAt = (cid: number): { x: number; y: number } => {
      if (numC <= 1 || cid >= ringN) return { x: W / 2, y: H / 2 };
      const ang = (2 * Math.PI * cid) / ringN - Math.PI / 2;
      return { x: W / 2 + Math.cos(ang) * W * 0.3, y: H / 2 + Math.sin(ang) * H * 0.3 };
    };
    for (const nm of names) {
      const p = sim.get(nm)!;
      const an = anchorAt(communities.get(nm) ?? 0);
      fx.set(nm, (an.x - p.x) * 0.011);
      fy.set(nm, (an.y - p.y) * 0.011);
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
        let rep = ((W * H) / 100) / (d * d);
        // 防重叠:近于 MIN_SEP 的两点额外强分,保证不堆成一坨(线性硬推,比 1/d² 在近距更可靠)。
        if (d < MIN_SEP) rep += (MIN_SEP - d) * 0.45;
        const ux = dx / d;
        const uy = dy / d;
        fx.set(names[i], fx.get(names[i])! + ux * rep);
        fy.set(names[i], fy.get(names[i])! + uy * rep);
        fx.set(names[j], fx.get(names[j])! - ux * rep);
        fy.set(names[j], fy.get(names[j])! - uy * rep);
      }
    }
    // 弹簧（沿边，静止长 = restLen(strength)）
    for (const e of rendered.edges) {
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

  // SVG viewBox 坐标 → 节点逻辑坐标:节点画在 translate(tx ty) scale(k) 的 <g> 里,
  // 屏幕(viewBox)坐标 = tx + k * 逻辑坐标,反推 逻辑 = (viewBox - t) / k。拖节点必须扣这步否则跟手错位。
  function svgToLogical(sx: number, sy: number, v: View): { x: number; y: number } {
    return { x: (sx - v.tx) / v.k, y: (sy - v.ty) / v.k };
  }

  // 算所有节点的包围盒,设视角让它带 ~10% 余量铺满视口(viewBox W×H),再居中。
  // 一打开就铺满可读,不是缩成一小撮。节点没初始化好就跳过。
  function fitToBounds() {
    const sim = simRef.current;
    if (!sim || sim.size === 0) return;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const p of sim.values()) {
      if (p.x < minX) minX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.x > maxX) maxX = p.x;
      if (p.y > maxY) maxY = p.y;
    }
    if (!isFinite(minX)) return;
    const bw = Math.max(1, maxX - minX);
    const bh = Math.max(1, maxY - minY);
    // 0.9 = 留 10% 余量,别贴边
    let k = Math.min(W / bw, H / bh) * 0.9;
    k = Math.max(K_MIN, Math.min(K_MAX, k));
    // 把盒中心摆到视口中心:viewport_center = t + k * box_center → t = vpCenter - k*boxCenter
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    setView({ k, tx: W / 2 - k * cx, ty: H / 2 - k * cy });
  }

  function onNodeDown(name: string, e: React.PointerEvent) {
    e.stopPropagation();
    dragRef.current = name;
    downRef.current = { name, x: e.clientX, y: e.clientY, moved: false };
    const p = simRef.current.get(name);
    if (p) p.fixed = true;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    if (rafRef.current == null) startSim();
  }

  function onMove(e: React.PointerEvent) {
    // 在空白背景上按下拖动 = 平移整图(只改 tx/ty,不动任何节点)。
    const pan = panRef.current;
    if (pan) {
      const { x: sx, y: sy } = toSvg(e.clientX, e.clientY);
      setView((v) => ({ ...v, tx: pan.tx + (sx - pan.sx), ty: pan.ty + (sy - pan.sy) }));
      return;
    }
    const name = dragRef.current;
    if (!name) return;
    // 起点挪过 4px 就算真在拖（不是手抖的点），松手时不再触发跳转。
    const dn = downRef.current;
    if (dn && !dn.moved && Math.hypot(e.clientX - dn.x, e.clientY - dn.y) > 4) {
      dn.moved = true;
    }
    // 节点画在 transform 过的 <g> 里,toSvg 给的是 viewBox 坐标,要扣掉缩放平移回到逻辑坐标,否则跟手错位。
    const { x: sx, y: sy } = toSvg(e.clientX, e.clientY);
    const { x, y } = svgToLogical(sx, sy, view);
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
    // 结束背景平移
    if (panRef.current) {
      panRef.current = null;
      return;
    }
    const name = dragRef.current;
    if (name) {
      const p = simRef.current.get(name);
      if (p) p.fixed = false;
    }
    // 在节点上按下、几乎没动就松手 = 点这个人 → 跳关系演变。拖过了不触发，不破坏拖动。
    // 只对人物图开放：概念节点跳关系演变（讲的是人）没意义。
    const dn = downRef.current;
    if (dn && !dn.moved && dn.name === name && unit === "person" && onSelectPerson) {
      onSelectPerson(dn.name);
    }
    downRef.current = null;
    dragRef.current = null;
    coolRef.current = 0;
    if (rafRef.current == null) startSim();
  }

  // 滚轮缩放,朝光标缩:缩放后光标下那个点不动。cx/cy 是光标在 viewBox 里的位置。
  // 经典式 newT = cx - (cx - t) * (newK/k),x/y 同理。k 夹在 K_MIN~K_MAX。
  function onWheel(e: React.WheelEvent) {
    e.preventDefault();
    const { x: cx, y: cy } = toSvg(e.clientX, e.clientY);
    setView((v) => {
      const factor = Math.exp(-e.deltaY * 0.0015); // 上滚放大、下滚缩小,指数让缩放手感均匀
      const newK = Math.max(K_MIN, Math.min(K_MAX, v.k * factor));
      const ratio = newK / v.k;
      return { k: newK, tx: cx - (cx - v.tx) * ratio, ty: cy - (cy - v.ty) * ratio };
    });
  }

  // 在空白背景按下 = 准备平移。节点的 onNodeDown 已 stopPropagation,所以按在节点上收不到这个,正好分开。
  function onBgDown(e: React.PointerEvent) {
    const { x: sx, y: sy } = toSvg(e.clientX, e.clientY);
    setView((v) => {
      panRef.current = { sx, sy, tx: v.tx, ty: v.ty };
      return v;
    });
    (e.target as Element).setPointerCapture?.(e.pointerId);
  }

  // 围着光标按钮缩放(+/−):以视口中心为锚,跟滚轮一个算法。
  function zoomBy(factor: number) {
    const cx = W / 2;
    const cy = H / 2;
    setView((v) => {
      const newK = Math.max(K_MIN, Math.min(K_MAX, v.k * factor));
      const ratio = newK / v.k;
      return { k: newK, tx: cx - (cx - v.tx) * ratio, ty: cy - (cy - v.ty) * ratio };
    });
  }

  // 重置视角:重新按当前节点位置 fit 铺满(不是死板复位到 k=1,那样大图又缩成一小撮)。
  function resetView() {
    fitToBounds();
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
          整本书分段抽取再合并，大书也能抽，约 1-3 分钟。
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
          {/* 缩放 / 平移控制:滚轮也能缩、空白处拖能平移,这几个按钮给不爱滚轮的人。 */}
          <button
            type="button"
            onClick={() => zoomBy(1.25)}
            disabled={loading}
            title="放大"
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
          >
            ＋
          </button>
          <button
            type="button"
            onClick={() => zoomBy(0.8)}
            disabled={loading}
            title="缩小"
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
          >
            －
          </button>
          <button
            type="button"
            onClick={resetView}
            disabled={loading}
            title="把整张图重新铺满视口"
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
          >
            重置视角
          </button>
        </div>
      </div>

      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        {data.nodes.length} 个{noun}、{data.edges.length} 条关系
        {rendered.hiddenCount > 0 && `（先画戏份最重的 ${rendered.nodes.length} 个）`}
        。星图：每个{noun}是一颗星、戏份越重星越大；连线=关系（敌红、亲绿、一般灰，越粗越亲密）；滚轮缩放、空白处拖动平移、拖星子挪位、点连线看那一章的原文出处（点开现取）。
      </p>
      {/* 图例:只剩关系类型(颜色方案 A 弃掉了按群上色,节点统一墨色、大小=戏份) */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mb-2 text-xs text-[var(--color-ink-muted)]">
        {(["foe", "kin", "neutral"] as RelKind[]).map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span style={{ display: "inline-block", width: 16, borderTop: `3px solid ${EDGE_COLOR[k]}` }} />
            {EDGE_KIND_LABEL[k]}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: STAR_COLOR }} />
          星越大 = 戏份越重
        </span>
      </div>
      {rendered.hiddenCount > 0 && (
        <div className="mb-2">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] transition-colors"
          >
            展开剩下 {rendered.hiddenCount} 个次要{noun}
          </button>
          <span className="ml-2 text-[11px] text-[var(--color-ink-muted)] opacity-70">
            全量节点多，力学会慢一点。
          </span>
        </div>
      )}
      {expanded && data.nodes.length > TOP_N && (
        <div className="mb-2">
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] transition-colors"
          >
            只看主要 {TOP_N} 个{noun}
          </button>
        </div>
      )}

      {!loading && (
        <RunStats trace={data.trace as RunTrace} note={`${data.edges.length} 条关系`} />
      )}

      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full border border-[var(--color-rule)] rounded touch-none"
        style={{ maxHeight: 560, background: NIGHT_SKY, cursor: "grab" }}
        onPointerDown={onBgDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={onUp}
        onWheel={onWheel}
      >
        {/* 星图：夜空底 + 人物=星(亮度按戏份)+ 阵营=星色 + 关系=星座连线。闪烁用纯 CSS,不靠 rAF。 */}
        {/* StarTwinkleStyle 是 <style> 不能进 transform 的 <g>(否则被当图形元素),留在外层。 */}
        <StarTwinkleStyle />
        {/* 缩放平移层:边和节点都在这个 <g> 里,整图能缩能拖。defs / style 留在外面。 */}
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>
        {/* 边：星座连线。只画渲染子集里的边;selected 仍是 data.edges 里的原索引,保证证据查询对得上。 */}
        {rendered.edges.map((e) => {
          const a = sim.get(e.source);
          const b = sim.get(e.target);
          if (!a || !b) return null;
          const origIdx = data.edges.indexOf(e); // 原数组索引(证据 effect / sel 都按它取)
          const active = selected === origIdx;
          return (
            <g key={`e-${origIdx}`}>
              <line
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={active ? "var(--color-seal)" : EDGE_COLOR[relationKind(e.relation)]}
                strokeWidth={active ? edgeWidth(e.strength) + 1.5 : edgeWidth(e.strength)}
                strokeLinecap="round"
                strokeDasharray={e.evidence && !e.verified ? "4 3" : undefined}
                opacity={active ? 1 : e.evidence && !e.verified ? 0.4 : 0.72}
              />
              <line
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="transparent"
                strokeWidth={14}
                style={{ cursor: "pointer" }}
                onClick={() => setSelected(origIdx)}
              />
            </g>
          );
        })}
        {/* 节点（颜色方案 A:统一墨色星、大小=戏份;缩放够大 / hover / 戏份重才标名,免得人多糊一脸） */}
        {rendered.nodes.map((name) => {
          const p = sim.get(name);
          if (!p) return null;
          const deg = degree.get(name) ?? 0;
          const r = 6 + Math.min(9, deg * 1.5);
          // 标名规则:节点少 / 戏份重(deg≥4) / 放大到一定程度 / 正悬停在它上面——任一满足就标。
          // 人多时缩着看不糊,放大或 hover 任意一颗都看得见名字。
          const showLabel =
            rendered.nodes.length <= 60 || deg >= 4 || view.k >= 1.6 || hovered === name;
          const dur = 2.4 + (deg % 4) * 0.7; // 错开闪烁,别齐刷刷
          return (
            <g
              key={`n-${name}`}
              style={{ cursor: unit === "person" && onSelectPerson ? "pointer" : "grab" }}
              onPointerDown={(ev) => onNodeDown(name, ev)}
              onPointerEnter={() => setHovered(name)}
              onPointerLeave={() => setHovered((h) => (h === name ? null : h))}
            >
              {unit === "person" && onSelectPerson && (
                <title>{`点 ${name} 看他的关系演变（拖动可挪位）`}</title>
              )}
              {/* 加大点击 / hover 命中区:透明大圈,半径比星子大一截,小星子也好点中、好 hover。 */}
              <circle cx={p.x} cy={p.y} r={Math.max(r + 12, 18)} fill="transparent" />
              <StarNode cx={p.x} cy={p.y} r={r} color={STAR_COLOR} twinkleDur={dur} />
              {showLabel && (
                <text
                  x={p.x}
                  y={p.y - r - 5}
                  textAnchor="middle"
                  fontSize={hovered === name ? 13 : 12}
                  fill="#f0e8d4"
                  fontWeight={hovered === name ? 700 : 400}
                  style={{ fontFamily: "var(--font-display)", pointerEvents: "none" }}
                >
                  {name}
                </text>
              )}
            </g>
          );
        })}
        </g>
      </svg>

      {sel && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            {sel.source} — {sel.relation} — {sel.target}
            <span className="ml-2 text-xs font-normal text-[var(--color-seal)]">
              {sel.strength >= 4 ? "紧密" : sel.strength >= 2 ? "一般" : "疏离"}
              <span className="text-[var(--color-ink-muted)]">（模型判读）</span>
            </span>
          </p>
          <p className="mt-1 text-sm text-[var(--color-ink)] leading-relaxed">
            {selEv?.loading
              ? "正在从这一章原文里找出处…"
              : (selEv?.found ? selEv.text : sel.evidence) ||
                "这一章原文里没比对到支撑这条关系的句子。"}
          </p>
          {(selEv?.found || sel.evidence) && (
            <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
              原文出处{sel.chapter > 0 ? ` · 第 ${sel.chapter} 章` : ""}（点开现取）
            </p>
          )}
        </div>
      )}
    </div>
  );
}
