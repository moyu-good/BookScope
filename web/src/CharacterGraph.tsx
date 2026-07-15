// ---------------------------------------------------------------------------
// CharacterGraph — 人物 / 概念关系图（WP-character-graph，exp-013/014 GO）
//
// 点生成 → 调 /api/agent/character-graph（整本进上下文抽结构化图）→ **实时动画力导向**
// 布局：圆圈自动散开、可拖动；连线按关系亲疏（strength 1-5）调远近 + 粗细。点边看原文。
// 自写力学模拟（弹簧 + 斥力 + 阻尼），rAF 驱动，冷却后停（省 CPU）；不引重图库（CPU-only）。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { GRAPH_BG, StarNode } from "./starSky";
import { usePanZoom } from "./usePanZoom";
import { useVizFocus } from "./viz/vizFocus";
import { vizTokens } from "./viz/vizTokens";
import { useSvgExport } from "./viz/useSvgExport";
import { ExportButton } from "./ExportButton";
import { EvidenceBadge, type EvidenceStrength } from "./viz/EvidenceBadge";

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  strength: number; // 亲疏 1-5（5 最紧密）
  evidence: string;
  verified: boolean;
  chapter: number;
  match_score: number;
  // 关系极性 友/敌/中——后端锚原文判(character_graph.py 的 polarity)。老数据可能没有 → 前端回落正则。
  polarity?: string;
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
  // 点一个人物节点 → 广播选中给别的镜头(可选,不传则只能拖动,行为跟以前一样)。
  onSelectPerson?: (name: string) => void;
  // 锁定分析单位:从「思想·理论」的概念关系图入口进来时传 "concept",跳过人物/概念选择卡直接出概念图。
  // 不传 = 老行为(先选人物 / 概念)。叙事书人物全景里的关系图不传,行为不变。
  defaultUnit?: "person" | "concept";
}

const PAD = 46;

// 默认只渲染戏份最重的前 N 个人物——三国 348 人全量力导向每帧 ~12 万对斥力会卡死。
// 按 degree 取前 N，剩下的折成"还有 N 个次要人物"按钮，点开才全量。力学只算渲染的这些。
const TOP_N = 70;

// 节点按阵营(社区发现)上色。detectCommunities 早算好了群。改成浅底后,旧那套给黑底调的亮色
// (#E0A08C 等)在浅纸上会发虚,换成 vizTokens 的分类盘——那套本就是给浅底设计的低饱和暖调
// (朱砂/墨/青绿/赭黄/靛/藤…),彼此分得开、跟善本调性搭。最大的群(id 0)拿朱砂,呼应善本;id 循环取色。
function factionColor(communityId: number): string {
  const p = vizTokens.categoricalPalette;
  return p[communityId % p.length];
}

// 概念节点按中心度(degree)深浅:越核心越深。中心度是概念真能编的维度(不像对概念无意义的"阵营")。
// 墨蓝一色系从浅到深插值——经济制裁那种巨型核心概念自然最深,一眼拎出核心。
function conceptColor(deg: number, maxDeg: number): string {
  const t = maxDeg > 0 ? Math.min(1, deg / maxDeg) : 0;
  const lerp = (a: number, b: number) => Math.round(a + (b - a) * t);
  return `rgb(${lerp(0x9d, 0x1c)},${lerp(0xc0, 0x46)},${lerp(0xcc, 0x57)})`;
}

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
  // 只认明确的敌对(政敌/宿敌/死敌/敌对/仇/反目/叛)。旧正则含「争 / 交锋 / 对立 / 对手 / 裸敌」太宽,
  // 会把君臣间的「兵权之争 / 猜忌」误判成敌对——唐肃宗和郭子仪就是被 /争/ 误成敌红的。宁可漏不可错报。
  if (/政敌|宿敌|死敌|敌对|仇|反目|叛/.test(r)) return "foe";
  if (/盟|结义|亲|族|父|母|子|女|夫|妻|兄|弟|姐|妹|君臣|主仆|师徒|师|徒|友|挚|同袍|姻/.test(r)) return "kin";
  return "neutral";
}
// 边的敌友底色:优先用后端锚原文判的 polarity(友/敌/中);老数据没这字段才回落 relationKind 正则(保守)。
// 这样敌友是证据来的、不是前端拿字符串猜的——唐肃宗郭子仪那类君臣不再被误判成敌对。
function edgePolarity(e: GraphEdge): RelKind {
  if (e.polarity === "敌") return "foe";
  if (e.polarity === "友") return "kin";
  if (e.polarity === "中") return "neutral";
  return relationKind(e.relation); // 老数据(抽取时还没 polarity)兜底
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
  defaultUnit,
}: CharacterGraphProps) {
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [selEv, setSelEv] = useState<{ loading: boolean; text: string; found: boolean } | null>(
    null,
  );
  const [unit, setUnit] = useState<"person" | "concept">(defaultUnit ?? "person");
  // 默认只渲染戏份前 TOP_N 个;点"展开次要人物"才全量。次要人物多才显示这个开关。
  const [expanded, setExpanded] = useState(false);
  // 鼠标悬停的节点名——人多时只给主要角色标名,hover 任意一颗也临时显名,
  // 还用来高亮它的邻居、淡化无关(见下面 neighbor useMemo)。
  const [hovered, setHovered] = useState<string | null>(null);
  // 图例筛选:选中哪几类边只看哪几类(可多选)。空 = 全部都看。复用 relationKind 分类。
  const [edgeKinds, setEdgeKinds] = useState<Set<RelKind>>(new Set());
  // 联动总线:点人物星子时广播"选中这个人"(见 onUp),别的镜头也能把选中的人广播过来让本图高亮。
  const { focus, setFocus } = useVizFocus();

  const svgRef = useRef<SVGSVGElement | null>(null);
  const simRef = useRef<Map<string, Node>>(new Map());
  const rafRef = useRef<number | null>(null);
  const coolRef = useRef(0);
  const dragRef = useRef<string | null>(null);
  // 已对当前这批数据做过 fit 没有——只 fit 一次,免得每帧重算抖。
  const fittedRef = useRef(false);
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
  // pan/zoom + 双指 pinch（移动端）：从自写逻辑提炼到 hook。节点拖拽靠 stopPropagation
  // 与背景指隔离——两指在背景 pinch 整图、一指在星子拖星子。
  const {
    view,
    setView,
    onPointerDown: onBgDown,
    onPointerMove: hookMove,
    onPointerUp: hookUp,
    onWheel,
    zoomBy,
    toSvg,
    svgToLogical,
    clampK,
  } = usePanZoom(svgRef, { width: W, height: H, minK: K_MIN, maxK: K_MAX });
  const communities = useMemo(
    () => (data ? detectCommunities(data.nodes, data.edges) : new Map<string, number>()),
    [data],
  );

  // 存图:把当前这张关系网导出成 PNG(带标题/来源/水印)。落款现取,人物/概念图各自命名。
  const { onExport } = useSvgExport(svgRef, () => ({
    title: `${unit === "concept" ? "概念" : "人物"}关系网`,
    source: `共 ${data?.nodes.length ?? 0} 个${unit === "concept" ? "概念" : "人物"}、${data?.edges.length ?? 0} 条关系`,
    filename: `${unit === "concept" ? "概念" : "人物"}关系图`,
  }));

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

  // 概念图节点按中心度上色要的最大度(归一分母)。人物图不用(它按阵营色)。
  const maxDeg = useMemo(() => Math.max(1, ...degree.values()), [degree]);

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

  // 阵营名册：把社区发现分出的群摊成文字（作者：既然分好阵营，就该在图外用文字列出来）。
  // 只认渲染子集，跟图上的点色一一对应；按群大小降序、群内按戏份降序；单点不成群略去。
  // 诚实：这是按关系亲疏（strength 加权 label propagation）自动分的群，不等于书里的正式阵营。
  const factions = useMemo(() => {
    if (!data) return [] as { id: number; members: string[] }[];
    const byId = new Map<number, string[]>();
    for (const name of rendered.nodes) {
      const id = communities.get(name) ?? 0;
      const arr = byId.get(id);
      if (arr) arr.push(name);
      else byId.set(id, [name]);
    }
    return [...byId.entries()]
      .map(([id, members]) => ({
        id,
        members: [...members].sort((a, b) => (degree.get(b) ?? 0) - (degree.get(a) ?? 0)),
      }))
      .filter((g) => g.members.length >= 2)
      .sort((a, b) => b.members.length - a.members.length);
  }, [data, rendered, communities, degree]);

  // 有效聚焦的人:鼠标 hover 优先(即时),没 hover 时看总线——别的镜头广播了一个人、
  // 且这人正画在图里,就聚焦他。这样 hover 和跨镜头联动共用同一套高亮/淡化。
  const focusedName =
    hovered ?? (focus?.kind === "person" && rendered.nodeSet.has(focus.id) ? focus.id : null);

  // 高亮邻居:聚焦一个节点时,算出「它 + 它的直接邻居」名字集合,和「跟它相连的边」的原始索引集合。
  // 渲染时不在集合里的节点/边压暗、相连的边加粗高亮。纯前端 O(edges)。
  // 只按 focusedName 算,拖拽的门放到用下面(见 hoverFocus)——dragRef 是 ref 进不了 memo 依赖,
  // 在这里判会拿旧缓存,得在渲染时读 dragRef.current 现值才准。
  const hoverFocusRaw = useMemo(() => {
    if (!focusedName || !rendered.nodeSet.has(focusedName)) return null;
    const names = new Set<string>([focusedName]);
    const edgeIdx = new Set<number>();
    for (const e of rendered.edges) {
      if (e.source === focusedName) {
        names.add(e.target);
        edgeIdx.add(data!.edges.indexOf(e));
      } else if (e.target === focusedName) {
        names.add(e.source);
        edgeIdx.add(data!.edges.indexOf(e));
      }
    }
    return { names, edgeIdx };
  }, [focusedName, rendered, data]);
  // 拖拽进行中(dragRef 非空)就不做高亮淡化,免得跟拖拽打架。渲染每帧都跑到这,读的是 dragRef 现值。
  const hoverFocus = dragRef.current ? null : hoverFocusRaw;

  // 图例筛选态:哪些边过筛(kind 命中)、哪些节点还连着过筛的边。空筛选 = 全过。
  // 用来在开了筛选时把不相干的边隐藏、把没有过筛边的节点压暗(方便只看某一派)。
  const kindFilter = useMemo(() => {
    if (edgeKinds.size === 0) return null; // 全部都看,不筛
    const nodesWithEdge = new Set<string>();
    for (const e of rendered.edges) {
      if (edgeKinds.has(edgePolarity(e))) {
        nodesWithEdge.add(e.source);
        nodesWithEdge.add(e.target);
      }
    }
    return { nodesWithEdge };
  }, [edgeKinds, rendered]);

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

  // 换数据(不只是展开/收起)时复位视角 + 清图例筛选,免得拿上一批的缩放/筛选看新图。
  // 展开/收起不复位,保住用户当前视角。
  useEffect(() => {
    setExpanded(false);
    setEdgeKinds(new Set());
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

  // 算所有节点的包围盒,设视角让它带 ~10% 余量铺满视口(viewBox W×H),再居中。
  // 一打开就铺满可读,不是缩成一小撮。节点没初始化好就跳过。
  // 读 simRef（节点逻辑坐标）→ 算 bounds → 用 hook 的 setView/clampK 落地。
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
    const k = clampK(Math.min(W / bw, H / bh) * 0.9);
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

  // 背景拖动（平移/pinch）交给 hook；节点拖拽（dragRef）自己处理。
  // 节点的 onNodeDown 已 stopPropagation，背景指才会进 hook 的 pointersRef。
  function onMove(e: React.PointerEvent) {
    const name = dragRef.current;
    if (!name) {
      hookMove(e);
      return;
    }
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

  function onUp(e: React.PointerEvent) {
    const name = dragRef.current;
    if (name) {
      const p = simRef.current.get(name);
      if (p) p.fixed = false;
      // 在节点上按下、几乎没动就松手 = 点这个人 → 原地选中并广播到联动总线,别的已打开的镜头会跟着高亮,
      // 但不强制切视图(强制跳走太霸道,用户可能只想选一下)。拖过了不触发,不破坏拖动。
      // 只对人物图开放:概念节点讲的不是人,广播没意义。
      const dn = downRef.current;
      if (dn && !dn.moved && dn.name === name && unit === "person") {
        // 再点同一个人 = 取消选中(作者反馈"点了怎么都取消不了");点别人 = 选中并广播到联动总线。
        // 不强制切视图(强制跳走太霸道,用户可能只想选一下)。
        const already = focus?.kind === "person" && focus.id === dn.name;
        setFocus(
          already
            ? null
            : { kind: "person", id: dn.name, label: dn.name, bookSessionId: sessionId },
        );
        // 过渡期:App 若还传着 onSelectPerson 就一并调,两边都不炸;主 Claude 之后会停传它。
        if (!already) onSelectPerson?.(dn.name);
      }
      downRef.current = null;
      dragRef.current = null;
      coolRef.current = 0;
      if (rafRef.current == null) startSim();
      return;
    }
    // 背景指释放交给 hook（清 pointersRef / pinch 态）
    hookUp(e);
  }

  // 重置视角:重新按当前节点位置 fit 铺满(不是死板复位到 k=1,那样大图又缩成一小撮)。
  function resetView() {
    fitToBounds();
  }

  // 点图例里某类边 → 切换只看这一类(可多选)。已选再点取消。空集 = 全部都看。
  function toggleEdgeKind(k: RelKind) {
    setEdgeKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  if (!data) {
    const cardCls =
      "flex flex-col items-start gap-1.5 p-4 rounded-lg border text-left transition-colors " +
      "border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] " +
      "disabled:opacity-50 disabled:hover:border-[var(--color-rule)]";
    // 从「思想·理论」概念关系图入口进来:锁 concept,只给一张卡直接生成,不摆人物/概念选择。
    if (defaultUnit) {
      const isConcept = defaultUnit === "concept";
      const noun = isConcept ? "概念" : "人物";
      return (
        <div className="pt-4">
          <p className="text-sm text-[var(--color-ink-muted)] mb-4">
            {isConcept
              ? "把书里的核心概念画成关系网：定义 / 包含 / 对立 / 因果，连线越粗越紧密，每条边点得到原文。"
              : "把整本书的人物关系网画成可拖动的动态图，每条边点得到原文。"}
          </p>
          <button
            type="button"
            onClick={() => load(defaultUnit)}
            disabled={loading || !apiKey}
            className={cardCls}
            style={{ maxWidth: 360 }}
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
              {loading ? "抽取中…" : `生成${noun}关系图`}
            </span>
            <span className="text-xs text-[var(--color-ink-muted)]">
              {isConcept ? "核心概念怎么勾连、多紧密" : "谁和谁、什么关系、多亲近"}
            </span>
          </button>
          {error && (
            <p className="mt-3 text-sm" style={{ color: "var(--color-seal)" }}>
              {error}
            </p>
          )}
          {loading && (
            <RunningProcess
              label={`抽取${noun}关系图`}
              hint="整本书喂进模型抽关系网，每条边都要回原文核验，约 1 分钟。"
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
    return (
      <div className="pt-4">
        <p className="text-sm text-[var(--color-ink-muted)] mb-4">
          把整本书的关系网画成可拖动的动态图，连线越粗、节点越近 = 关系越紧密，每条边点得到原文。挑一种生成：
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
            hint="整本书喂进模型抽关系网，每条边都要回原文核验，约 1 分钟。"
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
  // 这条边的证据强度:让"原文撑得硬不硬"一眼可见(EvidenceBadge 四态)。
  //   强锚 = 核验过 + 贴合度 match_score≥0.6;弱锚 = 核验过但贴合弱(<0.6);
  //   部分 = 有原文但没核验过(含按需现取到的那句,只知道找到、没打分);待核 = 没原文/取不到。
  // 边自带证据(概念图/旧路径)用边上的 verified/match_score 判;按需现取的(selEv)只知 found,归"部分"。
  const selStrength: EvidenceStrength | null = !sel
    ? null
    : sel.evidence
      ? sel.verified
        ? sel.match_score >= 0.6
          ? "strong"
          : "weak"
        : "partial"
      : selEv?.found
        ? "partial"
        : "unverified";
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
          {/* 锁定单位（defaultUnit，如从「概念关系图」入口进来）时不给"换成X"——一个入口只干一件事，
              人物 / 概念不再互相切,消掉跨题材选择带来的重复入口。 */}
          {!defaultUnit && (
            <button
              type="button"
              onClick={() => load(otherUnit)}
              disabled={loading}
              className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
            >
              换成{otherTitle}
            </button>
          )}
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
          <ExportButton onExport={onExport} disabled={loading || !data} />
        </div>
      </div>

      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        {data.nodes.length} 个{noun}、{data.edges.length} 条关系
        {rendered.hiddenCount > 0 && `（先画戏份最重的 ${rendered.nodes.length} 个）`}
。{unit === "concept"
          ? "每个概念是一个点、关联越多点越大；连线 = 概念关系（定义 / 包含 / 对立 / 因果，越粗越紧密）。滚轮缩放、空白处拖动平移、拖节点挪位、点连线看原文出处（点开现取）。鼠标停在一个点上，只亮它和跟它相连的一圈。"
          : "每个人物是一个点、戏份越重点越大，颜色按阵营分群；连线 = 关系（敌红、亲绿、一般灰，越粗越亲密）；滚轮缩放、空白处拖动平移、拖节点挪位、点连线看那一章的原文出处（点开现取）。鼠标停在一个点上，只亮它和跟它相连的一圈；点下面图例某类关系，只看这一类。"}
      </p>
      {/* 图例:关系类型可点筛选(点一类只看这一类,可多选,再点取消);节点统一墨色、大小=戏份那条只作说明不可点。 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 mb-2 text-xs text-[var(--color-ink-muted)]">
        {unit === "concept" ? (
          // 概念图没有敌友 / 阵营:连线只表概念关系(定义/包含/对立/因果)、粗细表紧密,不套人物那套敌友色。
          <span>连线 = 概念关系（定义 / 包含 / 对立 / 因果），越粗越紧密 · 点越大越深 = 越核心（关联越多）</span>
        ) : (
          <>
        {(["foe", "kin", "neutral"] as RelKind[]).map((k) => {
          const on = edgeKinds.has(k);
          const dimmed = edgeKinds.size > 0 && !on; // 开了筛选、又没选中这类 = 淡掉,让选中项更显眼
          return (
            <button
              key={k}
              type="button"
              onClick={() => toggleEdgeKind(k)}
              title={on ? `取消,不再单看${EDGE_KIND_LABEL[k]}` : `只看${EDGE_KIND_LABEL[k]}的关系`}
              className={
                "inline-flex items-center gap-1.5 px-2 py-0.5 rounded border cursor-pointer transition-colors " +
                (on
                  ? "border-[var(--color-seal)] bg-[var(--color-seal-soft)] text-[var(--color-ink)]"
                  : "border-transparent hover:border-[var(--color-rule)]")
              }
              style={{ opacity: dimmed ? 0.45 : 1 }}
            >
              <span style={{ display: "inline-block", width: 16, borderTop: `3px solid ${EDGE_COLOR[k]}` }} />
              {EDGE_KIND_LABEL[k]}
            </button>
          );
        })}
        {edgeKinds.size > 0 && (
          <button
            type="button"
            onClick={() => setEdgeKinds(new Set())}
            title="取消筛选,看全部关系"
            className="px-2 py-0.5 rounded border border-[var(--color-rule)] bg-white cursor-pointer hover:border-[var(--color-seal)] transition-colors text-[var(--color-ink)]"
          >
            看全部
          </button>
        )}
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-flex items-center gap-0.5">
            {vizTokens.categoricalPalette.slice(0, 4).map((c) => (
              <span
                key={c}
                style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: c }}
              />
            ))}
          </span>
          颜色 = 阵营（自动分群）· 点越大 = 戏份
        </span>
          </>
        )}
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
          <span className="ml-2 text-caption text-[var(--color-ink-muted)] opacity-70">
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
        style={{ maxHeight: 560, background: GRAPH_BG, cursor: "grab" }}
        onPointerDown={onBgDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={onUp}
        onWheel={onWheel}
      >
        {/* 浅底网络图：节点=实心圆点(大小按戏份)+ 阵营=点色 + 关系=连线。静止不闪。 */}
        {/* 缩放平移层:边和节点都在这个 <g> 里,整图能缩能拖。defs / style 留在外面。 */}
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>
        {/* 边：星座连线。只画渲染子集里的边;selected 仍是 data.edges 里的原索引,保证证据查询对得上。
            两层叠加:图例筛选(kindFilter)先把不看的这类边压到很暗且不接点击;hover 高亮(hoverFocus)再把
            跟悬停节点无关的边压暗、相连的边加粗高亮。selected(点开取证据的那条)始终最显眼,不被这两层盖掉。 */}
        {rendered.edges.map((e) => {
          const a = sim.get(e.source);
          const b = sim.get(e.target);
          if (!a || !b) return null;
          const origIdx = data.edges.indexOf(e); // 原数组索引(证据 effect / sel 都按它取)
          const active = selected === origIdx;
          const kind = edgePolarity(e);
          // 图例筛选:开了筛选又不属于选中类 = 这条被筛掉,压到很暗、也不再接点击(免得抢命中)。
          const filteredOut = edgeKinds.size > 0 && !edgeKinds.has(kind);
          // hover 高亮:悬停某节点时,不跟它相连的边算"无关",压暗;相连的加粗高亮。
          const isNeighborEdge = !!hoverFocus && hoverFocus.edgeIdx.has(origIdx);
          const dimByHover = !!hoverFocus && !isNeighborEdge && !active;
          // 基础不透明度:未核验的边本来就更淡(虚线);已核验的边在浅底上稍压低一点点(0.72→0.6)
          // 让画面更静、留白更透,颜色语义(敌红/亲绿/中灰)不动。再叠筛选/hover 的压暗。
          // 高亮不改颜色:连线颜色始终走敌友语义(敌红 / 亲绿 / 中灰)。active / 邻居的强调只靠"更亮 + 更粗"。
          // 之前 hover 把相连边全盖成朱砂一个色,同盟和敌对线就分不出了(作者反馈)——现在颜色专管敌友、
          // 明暗粗细专管聚焦,两个通道各管各的:hover 一个人,一眼看清他跟谁是盟(绿)、跟谁是敌(红)。
          const baseOp = active ? 1 : e.evidence && !e.verified ? 0.4 : 0.6;
          const emphOp = active ? 1 : isNeighborEdge ? 0.92 : baseOp;
          const opacity = filteredOut ? 0.1 : dimByHover ? 0.15 : emphOp;
          // 概念关系没有敌友,连线统一中性灰(粗细仍表紧密);人物图才按敌友极性上色。
          const stroke = unit === "concept" ? "#9A948A" : EDGE_COLOR[kind];
          const strokeWidth =
            active || isNeighborEdge ? edgeWidth(e.strength) + 1.5 : edgeWidth(e.strength);
          return (
            <g key={`e-${origIdx}`}>
              <line
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={stroke}
                strokeWidth={strokeWidth}
                strokeLinecap="round"
                strokeDasharray={e.evidence && !e.verified ? "4 3" : undefined}
                opacity={opacity}
              />
              {/* 被筛掉的边不接点击,免得从暗线上抢走命中区。 */}
              {!filteredOut && (
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
              )}
            </g>
          );
        })}
        {/* 节点（颜色方案 A:统一墨色星、大小=戏份;缩放够大 / hover / 戏份重才标名,免得人多糊一脸） */}
        {rendered.nodes.map((name) => {
          const p = sim.get(name);
          if (!p) return null;
          const deg = degree.get(name) ?? 0;
          // 重要度=戏份(degree):主角的星明显更大,一眼拎出来(范围约 6~20,拉开到约 3 倍)。
          const r = 6 + Math.min(14, deg * 2);
          // 聚焦态(hover 或总线广播过来的同一个人):放大 + 加粗标名,跟高亮邻居保持一致。
          const isHovered = focusedName === name;
          // 淡化判断:hover 高亮时,不在「悬停节点+其邻居」集合里的压暗;图例筛选时,不连着过筛边的压暗。
          // 悬停的节点本身永远最亮。两层各自算,取更暗的那个(都命中就叠加最狠)。
          const dimByHover = !!hoverFocus && !hoverFocus.names.has(name);
          const dimByFilter = !!kindFilter && !kindFilter.nodesWithEdge.has(name);
          const nodeOpacity = dimByHover || dimByFilter ? 0.15 : 1;
          // 标名规则:节点少 / 戏份重(deg≥4) / 放大到一定程度 / 正悬停在它上面——任一满足就标。
          // 人多时缩着看不糊,放大或 hover 任意一颗都看得见名字。淡化掉的节点不标名,免得暗图上飘一堆字。
          const showLabel =
            (rendered.nodes.length <= 60 || deg >= 4 || view.k >= 1.6 || isHovered) &&
            !(dimByHover || dimByFilter);
          return (
            <g
              key={`n-${name}`}
              style={{ cursor: unit === "person" && onSelectPerson ? "pointer" : "grab" }}
              onPointerDown={(ev) => onNodeDown(name, ev)}
              onPointerEnter={() => setHovered(name)}
              onPointerLeave={() => setHovered((h) => (h === name ? null : h))}
            >
              {unit === "person" && onSelectPerson && (
                <title>{`${name}（点选·拖动挪位）`}</title>
              )}
              {/* 加大点击 / hover 命中区:透明大圈,半径比星子大一截,小星子也好点中、好 hover。
                  透明圈单独放在淡化 <g> 外面——淡化只是视觉,命中区不受影响,淡下去的星照样能拖能点能 hover。 */}
              <circle cx={p.x} cy={p.y} r={Math.max(r + 12, 18)} fill="transparent" />
              {/* 星子本体 + 名字包在一个 <g> 里统一压暗;悬停的星 opacity=1 最醒目。 */}
              <g opacity={nodeOpacity}>
                <StarNode cx={p.x} cy={p.y} r={isHovered ? r + 1.5 : r} color={unit === "concept" ? conceptColor(deg, maxDeg) : factionColor(communities.get(name) ?? 0)} />
                {showLabel && (
                  <text
                    x={p.x}
                    y={p.y - r - 5}
                    textAnchor="middle"
                    fontSize={isHovered ? 14 : deg >= 6 ? 13 : 11}
                    fill="var(--color-ink)"
                    fontWeight={isHovered ? 700 : 400}
                    style={{ fontFamily: "var(--font-display)", pointerEvents: "none" }}
                  >
                    {name}
                  </text>
                )}
              </g>
            </g>
          );
        })}
        </g>
      </svg>

      {/* 阵营名册：把上面按颜色分的群用文字列清楚（作者要的）。点名字在图上高亮他。 */}
      {unit === "person" && factions.length >= 2 && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <div className="text-xs text-[var(--color-ink-muted)] mb-2">
            阵营名册 · 按关系亲疏自动分的群（未必是书里的正式阵营）。点名字在图上高亮他。
          </div>
          <div className="space-y-2.5">
            {factions.map((g) => (
              <div key={g.id} className="flex items-start gap-2">
                <span
                  className="inline-block w-3 h-3 rounded-full mt-1 shrink-0"
                  style={{ background: factionColor(g.id) }}
                  aria-hidden
                />
                <div className="min-w-0">
                  <span
                    className="text-sm font-bold text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {g.members[0]}
                  </span>
                  <span className="text-xs text-[var(--color-ink-muted)] ml-1">
                    等 {g.members.length} 人
                  </span>
                  <div className="flex flex-wrap gap-x-1 gap-y-0.5 mt-1">
                    {g.members.map((name) => (
                      <button
                        key={name}
                        type="button"
                        onClick={() =>
                          setFocus(
                            focus?.kind === "person" && focus.id === name
                              ? null
                              : { kind: "person", id: name, label: name, bookSessionId: sessionId },
                          )
                        }
                        className="text-xs px-1.5 py-0.5 rounded hover:bg-[var(--color-seal-soft)] transition-colors"
                        style={{
                          fontFamily: "var(--font-display)",
                          color: focusedName === name ? "var(--color-seal)" : "var(--color-ink)",
                        }}
                      >
                        {name}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {sel && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            {sel.source} — {sel.relation} — {sel.target}
            <span className="ml-2 text-xs font-normal text-[var(--color-seal)]">
              {sel.strength >= 4 ? "紧密" : sel.strength >= 2 ? "一般" : "疏离"}
              <span className="text-[var(--color-ink-muted)]">（模型判读）</span>
            </span>
            {/* 证据强度:这条关系原文撑得硬不硬。现取中先不摆态,等取完再显(免得闪一下待核)。 */}
            {selStrength && !selEv?.loading && (
              <EvidenceBadge strength={selStrength} className="ml-2" />
            )}
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
