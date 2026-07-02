// ---------------------------------------------------------------------------
// RedheadDependencyGraph — 依据链网（1.6 红头文件垂直·跨文件首炮）
//
// 一卷宗里好几份公文不是孤立的：下位文件「依据」上位文件、上位文件「落实」要下位去办、
// 新文件「废止 / 修改」旧文件、机关之间「上下级」、谁「发文」给谁。这块把这些**文件间
// 的关联**画成一张有向关联网——一眼看清这卷宗里谁是根、谁挂在谁下面、哪份废了哪份。
//
// 意象 = 案卷关联 / 层级有向图（公文世界本就是层级依据关系），不套人物星图那套重力学：
//   节点少（一卷宗 3-20 份），分层排——机关一行、文件按关系深度分层往下，有向边带箭头。
//   层级依据关系适合分层 + 有向布局，不适合 348 节点的力导向重力球。
//   文件节点走「案卷签」形态（朱砂描边方牌摆字号 / 文种），机关节点走「关防印」形态
//   （圆角章戳摆机关名）——两类一眼分得开。边按 kind 分线型 + 一句话标注（依据 / 落实 /
//   废止 …），点边看 note + 来源条款。
//
// evidence-first（全站一个规矩）：关系是后端从原文锚出来的（编不出来的丢）。后端推不出
// 任何关系 / 不足两份相关文件 → scanned=false，优雅退场不硬画空网。点边能看后端给的 note
// 与来源条款序号（chapter_anchor），不替用户脑补关系。
//
// 设计语言（数字善本案头，参 docs/design/WP-ui-design-language.md）：朱墨双色（朱砂 =
// var(--color-seal) 文件签描边 / 边线 / 箭头，墨 = var(--color-ink) 字号文种，淡墨 =
// 元信息），宋体 var(--font-display)，留白克制——不堆古风、无 emoji、不做成通用流程图。
// ---------------------------------------------------------------------------

import { useMemo, useRef, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { usePanZoom } from "./usePanZoom";

// ---- 后端契约（对着 /api/agent/redhead/dependency-graph 写，别改后端） ----

interface GraphNode {
  id: string;
  kind: "文件" | "机关";
  label: string;
  文种: string;
  机关: string;
  成文日期: string;
}

// 博弈姿态（研判口径，区别于核验事实）：后端只在「依据 / 落实」边判得出时才挂，下位对上位
// 是 忠实落实 / 层层加码 / 打折扣 / 创新先行。引发它的原文对照（下位 from_snippet vs 上位
// to_snippet）后端已锚到位，label 本身是推断——FE 用「研判」小标 + 弧括号点出，不盖核验印。
interface EdgePosture {
  label: string; // 忠实落实 / 层层加码 / 打折扣 / 创新先行
  basis: string;
  from_clause: number | null;
  to_clause: number | null;
  from_snippet: string; // 下位那条原话（已核）
  to_snippet: string; // 上位那条原话（已核）
}

interface GraphEdge {
  source: string;
  target: string;
  kind: string; // 依据 / 落实 / 废止 / 修改 / 上下级 / 发文
  chapter_anchor: number | null;
  note: string;
  posture?: EdgePosture | null; // 可选研判维；后端没判出就没有这个字段
}

interface DependencyGraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  scanned: boolean;
  trace?: RunTrace;
}

interface RedheadDependencyGraphProps {
  bookSessionIds: string[];
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 边类型各配一个克制的线型 + 色（数据语义，不跟主题走，写死 hex；未知 kind 走墨色虚线兜底）。
// 依据 / 落实 是核心层级关系 → 朱砂实线；废止 → 灰实线（这份没了）；修改 → 木褐虚线；
// 上下级（机关之间）→ 墨青点线；发文 → 暖绿虚线。
const EDGE_STYLE: Record<
  string,
  { color: string; dash: string; label: string }
> = {
  依据: { color: "#9a3a2e", dash: "", label: "依据" },
  落实: { color: "#b5573f", dash: "", label: "落实" },
  废止: { color: "#8a8077", dash: "", label: "废止" },
  修改: { color: "#8a6b3f", dash: "5 4", label: "修改" },
  上下级: { color: "#3a6378", dash: "2 3", label: "上下级" },
  发文: { color: "#4f7a52", dash: "5 4", label: "发文" },
};

function edgeStyle(kind: string): { color: string; dash: string; label: string } {
  return EDGE_STYLE[kind] ?? { color: "#6b6359", dash: "3 3", label: kind || "关联" };
}

// 博弈姿态四类各配克制的色（数据语义，写死 hex；未知走墨色兜底）。研判维不打分、纯分类。
// 忠实落实 = 中性墨青；层层加码 = 木褐（加压）；打折扣 = 朱砂（架空，最该警觉）；创新先行 = 暖绿。
const POSTURE_STYLE: Record<string, { fg: string; bg: string }> = {
  忠实落实: { fg: "#3a6378", bg: "rgba(58, 99, 120, 0.10)" },
  层层加码: { fg: "#8a6b3f", bg: "rgba(138, 107, 63, 0.10)" },
  打折扣: { fg: "#9a3a2e", bg: "rgba(154, 58, 46, 0.10)" },
  创新先行: { fg: "#4f7a52", bg: "rgba(79, 122, 82, 0.10)" },
};

function postureStyle(label: string): { fg: string; bg: string } {
  return (
    POSTURE_STYLE[label] ?? {
      fg: "var(--color-ink-muted)",
      bg: "var(--color-seal-soft)",
    }
  );
}

function hasText(v: string | null | undefined): boolean {
  return !!v && v.trim().length > 0;
}

// ---- 分层布局：纯计算，把 nodes 排成「机关一带 + 文件按依据深度分层往下」 ----
//
// 思路（层级依据更适合分层，不是力导向）：
//   1) 机关节点单独放最上面一行（它们是发文主体，是关系的源头侧）。
//   2) 文件节点按「被依据深度」分层：没有指向别的文件的（最底层落实件）排深处，
//      被别人依据的根件排浅处。用 source→target 有向边算每个文件的层级（最长依赖链）。
//   3) 同层文件横向均布。算不出层级（无文件间边）的全排一层。
// 坐标是相对单位（0..1 的 col、整数 row），渲染时映射到 viewBox 像素。

interface Placed {
  node: GraphNode;
  row: number; // 第几层（0 在上）
  col: number; // 该层内第几个（0..count-1）
  rowCount: number; // 该层一共几个，用来横向均布
}

function layoutNodes(nodes: GraphNode[], edges: GraphEdge[]): Placed[] {
  const orgs = nodes.filter((n) => n.kind === "机关");
  const docs = nodes.filter((n) => n.kind === "文件");
  const docIds = new Set(docs.map((d) => d.id));

  // 文件间有向边：source 依据/落实/废止/修改 target。算每个文件的「层级 = 它指向的
  // 文件里最深层 + 1」。指向越多越往下（落实件在深处）。
  const docEdges = edges.filter(
    (e) => docIds.has(e.source) && docIds.has(e.target),
  );
  const outMap = new Map<string, string[]>();
  for (const e of docEdges) {
    const arr = outMap.get(e.source) ?? [];
    arr.push(e.target);
    outMap.set(e.source, arr);
  }

  // 最长出边链 = 该文件的层级。带环保护（visited 防死循环），取深度。
  const depthCache = new Map<string, number>();
  function depthOf(id: string, stack: Set<string>): number {
    if (depthCache.has(id)) return depthCache.get(id)!;
    if (stack.has(id)) return 0; // 环：当前层兜底
    stack.add(id);
    const outs = outMap.get(id) ?? [];
    let d = 0;
    for (const t of outs) d = Math.max(d, depthOf(t, stack) + 1);
    stack.delete(id);
    depthCache.set(id, d);
    return d;
  }

  // 文件按层级分组（机关占 row 0，文件从 row 1 起）
  const docDepth = new Map<string, number>();
  let maxDepth = 0;
  for (const d of docs) {
    const dep = docEdges.length > 0 ? depthOf(d.id, new Set()) : 0;
    docDepth.set(d.id, dep);
    maxDepth = Math.max(maxDepth, dep);
  }
  // 浅层（被依据的根件）排上面 → row 越小越浅。我们要根件在上、落实件在下，
  // 所以 row = (maxDepth - dep)。机关在最上 row 0，文件从 row 1 起。
  const byRow = new Map<number, GraphNode[]>();
  const hasOrgs = orgs.length > 0;
  if (hasOrgs) byRow.set(0, orgs);
  for (const d of docs) {
    const dep = docDepth.get(d.id) ?? 0;
    const row = (hasOrgs ? 1 : 0) + (maxDepth - dep);
    const arr = byRow.get(row) ?? [];
    arr.push(d);
    byRow.set(row, arr);
  }

  const placed: Placed[] = [];
  const rows = [...byRow.keys()].sort((a, b) => a - b);
  // 把 row 重新压成连续 0..N（万一中间有空层）
  rows.forEach((r, normRow) => {
    const group = byRow.get(r)!;
    group.forEach((node, col) => {
      placed.push({ node, row: normRow, col, rowCount: group.length });
    });
  });
  return placed;
}

export function RedheadDependencyGraph({
  bookSessionIds,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadDependencyGraphProps) {
  const [result, setResult] = useState<DependencyGraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 选中的边（看 note + 来源条款）；选中的节点（高亮它牵连的边）
  const [activeEdge, setActiveEdge] = useState<number | null>(null);
  const [activeNode, setActiveNode] = useState<string | null>(null);

  const canRun = bookSessionIds.length >= 2 && !!apiKey;

  async function load() {
    if (bookSessionIds.length < 2) return;
    setLoading(true);
    setError(null);
    setActiveEdge(null);
    setActiveNode(null);
    try {
      const body: Record<string, unknown> = {
        book_session_ids: bookSessionIds,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/dependency-graph", {
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
      const data = (await resp.json()) as DependencyGraphResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const nodes = result?.nodes ?? [];
  const edges = result?.edges ?? [];
  const scanned = !!result && result.scanned;
  const gotSomething = scanned && nodes.length >= 2;

  // 布局：分层坐标（纯计算）
  const placed = useMemo(() => layoutNodes(nodes, edges), [nodes, edges]);
  const posById = useMemo(() => {
    const m = new Map<string, { x: number; y: number; p: Placed }>();
    const rowCount = placed.reduce((mx, p) => Math.max(mx, p.row), 0) + 1;
    for (const p of placed) {
      // viewBox 1000 x 高度按层数算。每层一行，层内横向均布。
      const x = ((p.col + 1) / (p.rowCount + 1)) * 1000;
      const y = ROW_PAD + (p.row + 0.5) * ((GRAPH_H_BASE * rowsToH(rowCount)) - ROW_PAD * 2) / rowCount;
      m.set(p.node.id, { x, y, p });
    }
    return m;
  }, [placed]);

  const rowCount = placed.reduce((mx, p) => Math.max(mx, p.row), 0) + 1;
  const viewH = GRAPH_H_BASE * rowsToH(rowCount);

  // pan/zoom + 双指 pinch（移动端）：公文依据网节点小、文字密，手机上不捏合看不清。
  const svgRef = useRef<SVGSVGElement | null>(null);
  const { view, onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onWheel, resetView } =
    usePanZoom(svgRef, { width: 1000, height: viewH });

  // ---- 未生成：入口卡片 ----
  if (!result) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1 flex items-center gap-2"
          style={{ fontFamily: "var(--font-display)" }}
        >
          <span
            className="h-4 w-[3px] rounded-full bg-[var(--color-seal)]"
            aria-hidden="true"
          />
          依据链网
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          把一卷宗里好几份公文的关系画成一张网——谁依据谁、谁落实谁、新文件废了哪份旧的、机关之间谁管谁。一眼看清这卷宗里哪份是根、哪份挂在它下面、哪份已经废止。文件间的关系全是从原文锚出来的，编不出来的不画。适合一组相关的党政公文 / 红头文件。
        </p>
        <DossierHint count={bookSessionIds.length} />
        <button
          type="button"
          onClick={load}
          disabled={loading || !canRun}
          className="mt-3 text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读这卷宗推关系网中（约 1-2 分钟）…" : "生成依据链网"}
        </button>
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {loading && (
          <RunningProcess
            label="读这卷宗推关系网"
            hint="卷宗里每份公文各建一份文脉，再一次性推出文件间的关系（依据 / 落实 / 废止 …），每条关系都锚回真实字号，约 1-2 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没推出：优雅退场，不硬画空网 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        <ViewHeader title="依据链网" loading={loading} onReload={load} />
        {loading ? (
          <RunningProcess label="读这卷宗推关系网" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            没推出文件间的关系——这卷宗里的公文可能彼此不相干，或者不足两份能挂上关系的文件。挑一组真有依据
            / 落实关系的公文（比如一份上位规定 + 几份配套实施办法），再试一次。
          </p>
        )}
      </div>
    );
  }

  // 高亮：选中节点时，跟它直接相连的边亮、其余暗
  const isEdgeLit = (e: GraphEdge): boolean => {
    if (activeNode === null) return true;
    return e.source === activeNode || e.target === activeNode;
  };
  const isNodeLit = (id: string): boolean => {
    if (activeNode === null) return true;
    if (id === activeNode) return true;
    return edges.some(
      (e) =>
        (e.source === activeNode && e.target === id) ||
        (e.target === activeNode && e.source === id),
    );
  };

  const docCount = nodes.filter((n) => n.kind === "文件").length;
  const orgCount = nodes.filter((n) => n.kind === "机关").length;

  return (
    <div className="pt-4">
      <ViewHeader title="依据链网" loading={loading} onReload={load} />

      {/* 题署：几份文件 · 几个机关 · 几条关联 */}
      <div className="mb-3 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{ color: "var(--color-seal)", border: "0.5px solid var(--color-seal)" }}
        >
          案卷关联 · {docCount} 份文件{orgCount > 0 ? ` · ${orgCount} 个机关` : ""}
        </span>
        <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
          {edges.length} 条关联
        </span>
        <button
          type="button"
          onClick={resetView}
          className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
        >
          重置视角
        </button>
        {activeNode && (
          <button
            type="button"
            onClick={() => setActiveNode(null)}
            className="ml-auto text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
          >
            清除高亮
          </button>
        )}
      </div>

      {/* ── 有向关联网 SVG ── */}
      <div className="rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] overflow-hidden">
        <svg
          ref={svgRef}
          viewBox={`0 0 1000 ${viewH}`}
          className="w-full touch-none"
          style={{ display: "block" }}
          role="img"
          aria-label="公文依据关联网"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerCancel}
          onPointerLeave={onPointerUp}
          onWheel={onWheel}
        >
          <defs>
            {/* 每个边色一个箭头 marker（同色箭头才不串色） */}
            {Object.entries(EDGE_STYLE).map(([k, s]) => (
              <marker
                key={k}
                id={`arrow-${k}`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M0 0 L10 5 L0 10 z" fill={s.color} />
              </marker>
            ))}
            <marker
              id="arrow-fallback"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M0 0 L10 5 L0 10 z" fill="#6b6359" />
            </marker>
          </defs>
          {/* 缩放平移层：边和节点都在这个 <g> 里，整图能缩能拖、双指捏合看清小字 */}
          <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>

          {/* 边：先画线再画节点（节点压在线上）。曲一点（贝塞尔）避免直线穿过节点。 */}
          {edges.map((e, i) => {
            const a = posById.get(e.source);
            const b = posById.get(e.target);
            if (!a || !b) return null;
            const st = edgeStyle(e.kind);
            const lit = isEdgeLit(e);
            const sel = activeEdge === i;
            const markerId = EDGE_STYLE[e.kind] ? `arrow-${e.kind}` : "arrow-fallback";
            // 控制点：往两点中线偏一点，给条柔和弧
            const mx = (a.x + b.x) / 2;
            const my = (a.y + b.y) / 2;
            const dx = b.x - a.x;
            const cx = mx + (Math.abs(dx) < 40 ? 60 : 0); // 同列上下时往右拱一下
            const d = `M ${a.x} ${a.y} Q ${cx} ${my} ${b.x} ${b.y}`;
            return (
              <g key={i} opacity={lit ? 1 : 0.16}>
                <path
                  d={d}
                  fill="none"
                  stroke={st.color}
                  strokeWidth={sel ? 2.6 : 1.6}
                  strokeDasharray={st.dash || undefined}
                  markerEnd={`url(#${markerId})`}
                  style={{ cursor: "pointer" }}
                  onClick={() => setActiveEdge((cur) => (cur === i ? null : i))}
                />
                {/* 边上的关系标签：一枚小牌摆在中点（依据 / 落实 …） */}
                {lit && (
                  <g
                    style={{ cursor: "pointer" }}
                    onClick={() => setActiveEdge((cur) => (cur === i ? null : i))}
                  >
                    <rect
                      x={cx / 2 + mx / 2 - 16}
                      y={my - 9}
                      width={32}
                      height={16}
                      rx={3}
                      fill="var(--color-paper)"
                      stroke={st.color}
                      strokeWidth={0.6}
                    />
                    <text
                      x={cx / 2 + mx / 2}
                      y={my + 2.5}
                      textAnchor="middle"
                      fontSize="10"
                      fill={st.color}
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {st.label}
                    </text>
                    {/* 博弈姿态小标（研判口径）：摆在关系牌下方，弧括号点出是「研判」非核验事实 */}
                    {e.posture?.label && (
                      <text
                        x={cx / 2 + mx / 2}
                        y={my + 17}
                        textAnchor="middle"
                        fontSize="9"
                        fill={postureStyle(e.posture.label).fg}
                        style={{ fontFamily: "var(--font-display)" }}
                      >
                        〈{e.posture.label}〉
                      </text>
                    )}
                  </g>
                )}
              </g>
            );
          })}

          {/* 节点：文件 = 案卷签（方牌），机关 = 关防印（圆角章戳） */}
          {placed.map(({ node }) => {
            const pos = posById.get(node.id);
            if (!pos) return null;
            const lit = isNodeLit(node.id);
            const active = activeNode === node.id;
            const isOrg = node.kind === "机关";
            const w = isOrg ? 150 : 170;
            const h = isOrg ? 36 : 52;
            return (
              <g
                key={node.id}
                transform={`translate(${pos.x - w / 2}, ${pos.y - h / 2})`}
                opacity={lit ? 1 : 0.22}
                style={{ cursor: "pointer" }}
                onClick={() =>
                  setActiveNode((cur) => (cur === node.id ? null : node.id))
                }
              >
                <rect
                  width={w}
                  height={h}
                  rx={isOrg ? 18 : 4}
                  fill={isOrg ? "var(--color-seal-soft)" : "var(--color-paper)"}
                  stroke="var(--color-seal)"
                  strokeWidth={active ? 2 : isOrg ? 1 : 1.2}
                />
                {isOrg ? (
                  <text
                    x={w / 2}
                    y={h / 2 + 4}
                    textAnchor="middle"
                    fontSize="12.5"
                    fill="var(--color-seal)"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {clip(node.label || node.机关, 11)}
                  </text>
                ) : (
                  <>
                    <text
                      x={w / 2}
                      y={20}
                      textAnchor="middle"
                      fontSize="12"
                      fontWeight="600"
                      fill="var(--color-ink)"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {clip(node.label, 13)}
                    </text>
                    <text
                      x={w / 2}
                      y={37}
                      textAnchor="middle"
                      fontSize="10.5"
                      fill="var(--color-ink-muted)"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {[node.文种, node.成文日期].filter(Boolean).join(" · ") || "公文"}
                    </text>
                  </>
                )}
              </g>
            );
          })}
          </g>
        </svg>
      </div>

      {/* 图例 + 提示 */}
      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-[var(--color-ink-muted)]">
        <span>
          点节点看牵连的关系 · 点边看依据原文
          {edges.some((e) => e.posture?.label)
            ? " · 〈…〉是博弈姿态（研判，点边看依据）"
            : ""}
        </span>
        <span className="flex items-center gap-3 flex-wrap">
          {usedEdgeKinds(edges).map((k) => {
            const s = edgeStyle(k);
            return (
              <span key={k} className="inline-flex items-center gap-1">
                <svg width="22" height="8" aria-hidden>
                  <line
                    x1="1"
                    y1="4"
                    x2="21"
                    y2="4"
                    stroke={s.color}
                    strokeWidth="1.6"
                    strokeDasharray={s.dash || undefined}
                  />
                </svg>
                {s.label}
              </span>
            );
          })}
        </span>
      </div>

      {/* 选中边的明细：note + 来源条款 */}
      {activeEdge !== null && edges[activeEdge] && (
        <EdgeDetail
          edge={edges[activeEdge]}
          nodes={nodes}
          onClose={() => setActiveEdge(null)}
        />
      )}

      {!loading && (
        <RunStats
          trace={trace}
          note={`${docCount} 份文件 · ${edges.length} 条关联`}
        />
      )}
    </div>
  );
}

// 选中某条边后的明细卡：从哪份指向哪份、什么关系、后端给的 note、来源条款序号。
function EdgeDetail({
  edge,
  nodes,
  onClose,
}: {
  edge: GraphEdge;
  nodes: GraphNode[];
  onClose: () => void;
}) {
  const st = edgeStyle(edge.kind);
  const src = nodes.find((n) => n.id === edge.source);
  const tgt = nodes.find((n) => n.id === edge.target);
  return (
    <div className="mt-3 rounded border border-[var(--color-rule)] bg-white p-3 pl-4 relative">
      <span
        className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full"
        style={{ background: st.color }}
        aria-hidden="true"
      />
      <div className="flex items-start justify-between gap-2">
        <p
          className="text-sm text-[var(--color-ink)] leading-snug"
          style={{ fontFamily: "var(--font-display)" }}
        >
          <span className="font-bold">{src?.label ?? edge.source}</span>
          <span className="mx-1.5" style={{ color: st.color }}>
            ——{st.label}→
          </span>
          <span className="font-bold">{tgt?.label ?? edge.target}</span>
        </p>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] shrink-0"
        >
          收起
        </button>
      </div>
      {hasText(edge.note) && (
        <p className="mt-1.5 text-body-sm leading-relaxed text-[var(--color-ink)]">
          {edge.note}
        </p>
      )}
      {typeof edge.chapter_anchor === "number" && (
        <p className="mt-1.5 text-xs text-[var(--color-ink-muted)] tabular-nums">
          锚自 第 {edge.chapter_anchor} 条
        </p>
      )}
      {edge.posture?.label && <PostureBlock posture={edge.posture} />}
    </div>
  );
}

// 博弈姿态明细块（研判口径）：下位对上位是什么姿态 + 凭什么判 + 引发它的上下位原文对照。
// 视觉上和「核验事实」分开——明确标「研判」，不盖鉴印；两侧原话是后端已锚的对照证据。
function PostureBlock({ posture }: { posture: EdgePosture }) {
  const ps = postureStyle(posture.label);
  return (
    <div
      className="mt-2.5 rounded p-2.5"
      style={{ background: ps.bg, border: `0.5px solid ${ps.fg}` }}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className="text-caption px-1.5 py-0.5 rounded-full"
          style={{ color: ps.fg, border: `0.5px solid ${ps.fg}` }}
        >
          研判·博弈姿态
        </span>
        <span
          className="text-sm font-bold"
          style={{ color: ps.fg, fontFamily: "var(--font-display)" }}
        >
          {posture.label}
        </span>
      </div>
      {hasText(posture.basis) && (
        <p className="mt-1.5 text-body-sm leading-relaxed text-[var(--color-ink)]">
          {posture.basis}
        </p>
      )}
      {/* 引发姿态的上下位原文对照（后端已锚的证据，区别于上面的研判结论） */}
      {(hasText(posture.from_snippet) || hasText(posture.to_snippet)) && (
        <div className="mt-2 space-y-1.5">
          {hasText(posture.to_snippet) && (
            <PostureQuote rank="上位" snippet={posture.to_snippet} accent={ps.fg} />
          )}
          {hasText(posture.from_snippet) && (
            <PostureQuote rank="下位" snippet={posture.from_snippet} accent={ps.fg} />
          )}
        </div>
      )}
    </div>
  );
}

function PostureQuote({
  rank,
  snippet,
  accent,
}: {
  rank: "上位" | "下位";
  snippet: string;
  accent: string;
}) {
  return (
    <div className="flex items-start gap-2">
      <span
        className="text-caption px-1 py-0.5 rounded shrink-0 mt-0.5"
        style={{ color: accent, border: `0.5px solid ${accent}`, fontFamily: "var(--font-display)" }}
      >
        {rank}
      </span>
      <p
        className="text-caption leading-relaxed text-[var(--color-ink-muted)] border-l-2 pl-2"
        style={{
          borderColor: "color-mix(in oklch, var(--color-seal) 35%, transparent)",
          fontFamily: "var(--font-display)",
        }}
      >
        {snippet}
      </p>
    </div>
  );
}

// 顶部标题 + 重新生成
function ViewHeader({
  title,
  loading,
  onReload,
}: {
  title: string;
  loading: boolean;
  onReload: () => void;
}) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h3
        className="text-base font-bold text-[var(--color-ink)]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        {title}
      </h3>
      <button
        type="button"
        onClick={onReload}
        disabled={loading}
        className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
      >
        {loading ? "重出中…" : "重新生成"}
      </button>
    </div>
  );
}

// 卷宗份数提示：跨文件视图至少要选 2 份。复用在三个视图入口。
export function DossierHint({ count }: { count: number }) {
  if (count >= 2) {
    return (
      <p className="text-xs text-[var(--color-ink-muted)]">
        当前卷宗 {count} 份公文。
      </p>
    );
  }
  return (
    <p className="text-xs" style={{ color: "var(--color-seal)" }}>
      跨文件视图至少要 2 份公文——先去「卷宗」把相关的几份选进来。
      {count === 1 ? "（现在只选了 1 份）" : ""}
    </p>
  );
}

// 文字过长截断（节点签牌放不下整名）
function clip(s: string, max: number): string {
  if (!s) return "";
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function usedEdgeKinds(edges: GraphEdge[]): string[] {
  const seen = new Set<string>();
  for (const e of edges) if (e.kind) seen.add(e.kind);
  return [...seen];
}

// 布局常量
const GRAPH_H_BASE = 320;
const ROW_PAD = 50;
function rowsToH(rows: number): number {
  // 层数越多越高，给每层留够竖向空间
  return Math.max(1, rows / 2.2);
}
