// ---------------------------------------------------------------------------
// CharacterFlow — 人物在场长条 / presence strip（WP-character-narrative-flow，probe GO）
//
// 点生成 → 调 /api/agent/character-flow（整本进上下文逐章抽同场结构）→ 自写 SVG 网格：
//   行 = 角色，列 = 章号（左→右）。角色在某章在场，就在「这行 × 这列」画一个该角色色的实心
//   小竖条；戏份越重条越浓（拿不到就统一浓度）；不在场就留白。
// 一眼能看的两件事：
//   · 每行 = 这角色的在场轨迹——连续填满 = 一直在台，中间断白 = 离场了几章。
//   · 某列填得满 = 那一章上台的人多，是群戏；稀稀拉拉几格 = 独角戏 / 小场面。
//
// 换掉了旧的泳道 storyline（每人一条横线穿全书 + 同场竖束）：人一多、同场一多，横线交叉、
// 竖束糊成团，读着累。同场关系不再画竖束，改由「同一列里多个格子一起亮」体现，点列看那章
// 在场名单 + 原文依据。
//
// 进场动画纯 CSS（格子淡入 + 轻微升起），一次性、不空转，绝不用 rAF 当显示开关（headless 会卡）。
// 不引重图库（CPU-only）。evidence-first：点列时复用点同场束那套 /agent/spine-evidence 现取原文。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { usePanZoom } from "./usePanZoom";
import { categoricalPalette } from "./viz/vizTokens";
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

// 点开某一章时按需取那一段原文(/agent/spine-evidence,纯检索,不要 key)。
interface ChapterEvidence {
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
const H_MIN = 360;
const ROW_H = 22; // 每个角色一行的纵向占高（行多就把画布撑高，不挤成发丝）
const PAD_LEFT = 96; // 左边给人名留位
const PAD_RIGHT = 24;
const PAD_TOP = 24;
const PAD_BOTTOM = 30; // 底部留给章号刻度
const CELL_GAP_X = 1.5; // 相邻列格子间留的横向缝，让每列分得开
const CELL_MAX_W = 16; // 单格最大宽——章少时别把格子拉得太胖

// storyline 一多就糊，presence strip 也一样：角色几十号人时全画会挤。默认只画戏份最高的 8 个人，
// 顶部给个控件一键展开到全部。戏份排序键 = 出现章数（这人在多少章的 present 里），从后端数据里
// 数出来、不是拍脑袋定的；群戏不会虚高谁的排名（那是「同场对数」的毛病），出现章数更能代表分量。
const DEFAULT_TOP = 8; // 默认只画主要 8 人

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
  // 选中的列 = 一个章号（点格子 / 点列头都落到章号）
  const [selChapter, setSelChapter] = useState<number | null>(null);
  const [selEv, setSelEv] = useState<ChapterEvidence | null>(null);
  const [hoverChar, setHoverChar] = useState<string | null>(null);
  // hover 到某个格子：{章 index, 角色名}——出浮标用
  const [hoverCell, setHoverCell] = useState<{ i: number; name: string } | null>(null);
  // 只看主要 DEFAULT_TOP 人（默认），还是看全部。控件在顶部，默认收着。
  const [showAll, setShowAll] = useState(false);
  // 进场动画：load 成功后 key 变 → 重新触发格子淡入；不用 rAF。
  const [animKey, setAnimKey] = useState(0);

  async function load() {
    setLoading(true);
    setError(null);
    setSelChapter(null);
    setHoverChar(null);
    setHoverCell(null);
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
        setAnimKey((k) => k + 1);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 全书出场总人数（给说明用——图里默认只画戏份最高的前 DEFAULT_TOP 个）
  const totalCast = useMemo(() => {
    if (!chapters) return 0;
    const all = new Set<string>();
    for (const c of chapters) for (const name of c.present) all.add(name);
    return all.size;
  }, [chapters]);

  // 画图用的视图：默认只留戏份最高的前 DEFAULT_TOP 个角色（点了「看全部」就全留）。
  // 戏份 = 出现的章数（数这个人在多少章的 present 里），从后端数据里数出来。
  const view = useMemo(() => {
    if (!chapters) return null;
    const chapterCount = new Map<string, number>();
    for (const c of chapters)
      for (const name of c.present)
        chapterCount.set(name, (chapterCount.get(name) ?? 0) + 1);
    const ranked = [...chapterCount.entries()].sort((a, b) => b[1] - a[1]);
    const limit = showAll ? ranked.length : DEFAULT_TOP;
    const kept = new Set(ranked.slice(0, limit).map(([name]) => name));
    return chapters.map((c) => ({
      chapter: c.chapter,
      present: c.present.filter((n) => kept.has(n)),
      pairs: c.pairs.filter((p) => kept.has(p.a) && kept.has(p.b)),
    }));
  }, [chapters, showAll]);

  // ----- 布局派生量：角色行顺序 + 行 y、各章列 x + 列宽、每章每人戏份、画布高 -----
  const layout = useMemo(() => {
    if (!view) return null;

    // 角色行顺序：按出现章数降序（戏最多的排最上），并列再按登场早晚。
    // 这样最主要的角色在顶部，一眼先看到；行顺序稳定不跳。
    const chapterCount = new Map<string, number>();
    const firstIdx = new Map<string, number>();
    view.forEach((c, i) => {
      for (const name of c.present) {
        chapterCount.set(name, (chapterCount.get(name) ?? 0) + 1);
        if (!firstIdx.has(name)) firstIdx.set(name, i);
      }
    });
    const names = [...chapterCount.keys()].sort((a, b) => {
      const ca = chapterCount.get(a)!;
      const cb = chapterCount.get(b)!;
      if (ca !== cb) return cb - ca; // 戏多的靠上
      return (firstIdx.get(a)! - firstIdx.get(b)!); // 并列按登场早晚
    });

    // 画布高随行数长：人少用 H_MIN，人多每行留 ROW_H（免得几十行挤成发丝，viewBox 按容器缩放）
    const plotTop = PAD_TOP;
    const H = Math.max(H_MIN, names.length * ROW_H + plotTop + PAD_BOTTOM);

    // 行中心 y：从 plotTop 起，每行 ROW_H
    const rowY = new Map<string, number>();
    names.forEach((name, r) => {
      rowY.set(name, plotTop + ROW_H * (r + 0.5));
    });

    // 各章列 x + 列宽：章数把内宽均分，格子略窄于列距（留 CELL_GAP_X 缝），且不超过 CELL_MAX_W
    const n = view.length;
    const innerW = W - PAD_LEFT - PAD_RIGHT;
    const colW = innerW / Math.max(1, n);
    const cellW = Math.min(CELL_MAX_W, Math.max(2, colW - CELL_GAP_X));
    // 列中心 x（格子画成以列中心对齐的竖条）
    const xCenter = (i: number) => PAD_LEFT + colW * (i + 0.5);

    // 每人每章戏份（出场=1 + 同场对数）→ 格子浓淡 / 高度。拿不到就统一（=1）。
    const screen = new Map<string, number>(); // key = name|idx
    let maxScreen = 1;
    view.forEach((c, i) => {
      const pairCount = new Map<string, number>();
      for (const pr of c.pairs) {
        pairCount.set(pr.a, (pairCount.get(pr.a) ?? 0) + 1);
        pairCount.set(pr.b, (pairCount.get(pr.b) ?? 0) + 1);
      }
      for (const name of c.present) {
        const s = 1 + (pairCount.get(name) ?? 0);
        screen.set(`${name}|${i}`, s);
        maxScreen = Math.max(maxScreen, s);
      }
    });

    // 每人的行号（配色索引用，跟着 names 顺序走，稳定）
    const rowOf = new Map<string, number>();
    names.forEach((name, r) => rowOf.set(name, r));

    return { names, rowY, rowOf, xCenter, colW, cellW, n, screen, maxScreen, H };
  }, [view]);

  // 动态画布高（行多就高）；layout 未就绪时退 H_MIN。viewBox 和 pan/zoom 都用这个。
  const H = layout?.H ?? H_MIN;

  // ⚠ hooks 必须在任何 early return 之前无条件调用（React Hooks 规则）。SubplotWeave 踩过这个坑：
  // svgRef / usePanZoom 写在空态 return 之后，生成出数据后 hook 数变化 → React 直接崩白屏。
  // 所以 svgRef + usePanZoom 全提到 early return 之前；H 用 layout?.H 兜底，空态也算得出。
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

  // 选中某一章 → 按需调 /agent/spine-evidence 取那一章的原文依据（纯检索,不要 key）。
  // spine-evidence 只认 pair / event 两种 kind；这里复用点同场束那套 pair 逻辑：拿这章在场里
  // 戏份最高的两个人当 pair 取证。只有 1 人在场（没成对）时不硬取——诚实显在场名单、不编原文。
  useEffect(() => {
    if (selChapter == null || !view || !layout) {
      setSelEv(null);
      return;
    }
    const col = view.find((c) => c.chapter === selChapter);
    if (!col || col.present.length < 2) {
      // 少于两人：拿不到 pair 证据，清掉旧证据、只在面板显在场名单
      setSelEv(null);
      return;
    }
    // 这章在场里按戏份取前两名当 pair
    const ranked = [...col.present].sort(
      (a, b) =>
        (layout.screen.get(`${b}|${view.indexOf(col)}`) ?? 0) -
        (layout.screen.get(`${a}|${view.indexOf(col)}`) ?? 0),
    );
    const a = ranked[0];
    const b = ranked[1];
    let cancelled = false;
    setSelEv({ loading: true, text: "", found: false });
    (async () => {
      try {
        const resp = await fetch("/api/agent/spine-evidence", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            book_session_id: sessionId,
            chapter: selChapter,
            kind: "pair",
            a,
            b,
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
  }, [selChapter, sessionId, view, layout]);

  if (!view || !layout) {
    // 空态（还没生成）：统一入口卡（视觉表现根治 · FeatureEntryCard）
    return (
      <FeatureEntryCard
        title="人物在场"
        lead="一张干净的网格：每行一个角色，横轴是章节。角色在某章上台就在那一格亮起，戏越重越浓、离场就留白。每行看这人从头到尾何时在台，每列看这一章上了多少人——填满的列就是群戏。"
        actionLabel="生成人物在场图"
        loadingLabel="读全书抽在场结构中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书抽逐章在场，约 1 分钟；命中缓存秒出"
        error={error}
      >
        {loading && (
          <RunningProcess
            label="读全书抽人物在场"
            hint="整本书喂进模型逐章抽在场结构，每章在场判定都回原文核验，约 1 分钟。"
          />
        )}
      </FeatureEntryCard>
    );
  }

  const { names, rowY, rowOf, xCenter, cellW, n, screen, maxScreen } = layout;

  // 每人一个分类色（跟关系图节点 / 旧泳道同一套浅底盘），行索引取色，稳定不乱。
  const colorOf = (name: string) =>
    categoricalPalette[(rowOf.get(name) ?? 0) % categoricalPalette.length];

  // 戏份 → 格子浓淡：最低 0.42（在场就看得清）、最重铺满到 1，线性映射。拿不到戏份就给中档。
  const opacityOf = (s: number | undefined) => {
    if (s == null) return 0.7;
    const t = maxScreen > 1 ? (s - 1) / (maxScreen - 1) : 1;
    return 0.42 + t * 0.58;
  };

  // 选中列的在场名单（点列看这章上了谁）
  const selCol = selChapter != null ? view.find((c) => c.chapter === selChapter) : null;
  const selPresent = selCol?.present ?? [];

  // 说明句里用的：全书群戏最盛的那一章（在场人数最多的列），点出来当读图引导。
  const totalPresenceCells = view.reduce((acc, c) => acc + c.present.length, 0);

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          人物在场
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
        、{n} 章。每行一个角色、横轴是章节：亮格 = 这章在场（越浓戏越重），留白 = 离场。一行看这人的在场轨迹，一列看这章上了多少人——填满的列就是群戏。点某一列看那章在场名单 + 原文出处（点开现取）。
      </p>

      {/* 主要 N 人 / 全部 的切换：默认收在主要 DEFAULT_TOP 人，人多全画会挤。
          只有当全书人数确实多于当前画的（有得可展）时才出这个控件，克制不喧宾夺主。 */}
      {totalCast > DEFAULT_TOP && (
        <div className="mb-2 flex items-center gap-3 text-xs">
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="px-2 py-0.5 rounded border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] transition-colors"
          >
            {showAll ? `只看主要 ${DEFAULT_TOP} 人` : `看全部 ${totalCast} 人`}
          </button>
          {!showAll && (
            <span className="text-[var(--color-ink-muted)]">
              只画了戏份最高的 {DEFAULT_TOP} 人（按出现章数）
            </span>
          )}
        </div>
      )}

      <svg
        ref={svgRef}
        key={animKey}
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
        {/* 格子进场动画：纯 CSS 淡入 + 轻微升起，一次性；绝不用 rAF 当显示开关（headless 会卡）。
            用 animation-delay 按列递进，从左往右像卷轴铺开，但总时长封顶、不永动。 */}
        <style>{`
          @keyframes cf-cell-in {
            from { opacity: 0; transform: translateY(3px); }
            to   { opacity: 1; transform: translateY(0); }
          }
          .cf-cell { animation: cf-cell-in 0.34s ease-out both; }
        `}</style>

        {/* 缩放平移层：刻度 + 行标 + 格子都在这个 <g> 里，整图能缩能拖、双指捏合看细节 */}
        <g transform={`translate(${zoomView.tx} ${zoomView.ty}) scale(${zoomView.k})`}>
          {/* 选中列的高亮竖带（衬在格子底下，点了哪列一眼看出） */}
          {selChapter != null &&
            (() => {
              const i = view.findIndex((c) => c.chapter === selChapter);
              if (i < 0) return null;
              const x = xCenter(i);
              return (
                <rect
                  x={x - cellW / 2 - 2}
                  y={PAD_TOP - 4}
                  width={cellW + 4}
                  height={H - PAD_TOP - PAD_BOTTOM + 8}
                  fill="var(--color-seal)"
                  opacity={0.08}
                  rx={2}
                />
              );
            })()}

          {/* 章号刻度（章多就每隔几章标一个，避免拥挤） */}
          {view.map((c, i) =>
            n <= 24 || i % Math.ceil(n / 20) === 0 ? (
              <text
                key={`x-${c.chapter}`}
                x={xCenter(i)}
                y={H - 10}
                textAnchor="middle"
                fontSize={9}
                fill="var(--color-ink-muted)"
              >
                {c.chapter}
              </text>
            ) : null,
          )}

          {/* 每行一个角色：左侧行标 + 一整行的在场格子 */}
          {names.map((name) => {
            const y = rowY.get(name)!;
            const color = colorOf(name);
            const dimmed = hoverChar != null && hoverChar !== name;
            return (
              <g
                key={`row-${name}`}
                onPointerEnter={() => setHoverChar(name)}
                onPointerLeave={() => setHoverChar(null)}
                opacity={dimmed ? 0.28 : 1}
              >
                {/* 行标（点行标高亮该行、淡其余；复用 hoverChar，点一下钉住方便看单行轨迹） */}
                <text
                  x={PAD_LEFT - 8}
                  y={y + 3}
                  textAnchor="end"
                  fontSize={11}
                  fill={dimmed ? "var(--color-ink-muted)" : "var(--color-ink)"}
                  style={{ fontFamily: "var(--font-display)", cursor: "pointer" }}
                  onClick={() => setHoverChar(hoverChar === name ? null : name)}
                >
                  {name.length > 6 ? name.slice(0, 6) + "…" : name}
                  <title>{name}</title>
                </text>

                {/* 这一行的在场格子：只在 present 含这名的列画竖条，其余留白 */}
                {view.map((c, i) => {
                  if (!c.present.includes(name)) return null;
                  const s = screen.get(`${name}|${i}`);
                  const op = opacityOf(s);
                  const x = xCenter(i);
                  // 竖条高度：占满行高一大半；戏重的略高一点（在浓淡之外再给一层可读线索）
                  const t = maxScreen > 1 ? ((s ?? 1) - 1) / (maxScreen - 1) : 1;
                  const barH = ROW_H * (0.5 + t * 0.34);
                  const isHov =
                    hoverCell != null && hoverCell.i === i && hoverCell.name === name;
                  return (
                    <rect
                      key={`cell-${name}-${i}`}
                      className="cf-cell"
                      style={{
                        cursor: "pointer",
                        animationDelay: `${Math.min(i * 12, 400)}ms`,
                      }}
                      x={x - cellW / 2}
                      y={y - barH / 2}
                      width={cellW}
                      height={barH}
                      rx={1.5}
                      fill={color}
                      opacity={isHov ? 1 : op}
                      stroke={isHov ? "var(--color-ink)" : "none"}
                      strokeWidth={isHov ? 1 : 0}
                      onPointerEnter={() => setHoverCell({ i, name })}
                      onPointerLeave={() => setHoverCell(null)}
                      onClick={() => setSelChapter(c.chapter)}
                    />
                  );
                })}
              </g>
            );
          })}

          {/* 列点击热区：每列一条透明竖带，点空白处也能选中整章（不用非得点到某个格子） */}
          {view.map((c, i) => {
            const x = xCenter(i);
            return (
              <rect
                key={`colhit-${c.chapter}`}
                x={x - cellW / 2 - CELL_GAP_X / 2}
                y={PAD_TOP - 4}
                width={cellW + CELL_GAP_X}
                height={H - PAD_TOP - PAD_BOTTOM + 8}
                fill="transparent"
                style={{ cursor: "pointer" }}
                onClick={() => setSelChapter(c.chapter)}
              >
                <title>第 {c.chapter} 章 · 在场 {c.present.length} 人</title>
              </rect>
            );
          })}
        </g>
      </svg>

      {/* hover 浮标：第 X 章 · 角色名（有戏份带上）。放 SVG 下方一行，避免 headless 里定位漂移。 */}
      <div className="mt-1 h-4 text-xs text-[var(--color-ink-muted)]">
        {hoverCell && view[hoverCell.i]
          ? (() => {
              const s = screen.get(`${hoverCell.name}|${hoverCell.i}`);
              return `第 ${view[hoverCell.i].chapter} 章 · ${hoverCell.name}${
                s != null && s > 1 ? `（这章戏份 ${s}）` : ""
              }`;
            })()
          : " "}
      </div>

      <div className="mt-1 flex items-center gap-4">
        <button
          type="button"
          onClick={resetView}
          className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
        >
          重置视角
        </button>
        {hoverChar && (
          <button
            type="button"
            onClick={() => setHoverChar(null)}
            className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
          >
            取消高亮「{hoverChar}」
          </button>
        )}
      </div>

      {/* 选中列详情：这一章在场名单 + 原文出处（复用点同场束那套 spine-evidence 现取） */}
      {selChapter != null && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            第 {selChapter} 章 · 在场 {selPresent.length} 人
          </p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {selPresent.length > 0 ? (
              selPresent.map((name) => (
                <span
                  key={`chip-${name}`}
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs"
                  style={{
                    color: "var(--color-ink)",
                    border: `1px solid ${colorOf(name)}`,
                  }}
                >
                  <span
                    className="inline-block w-2 h-2 rounded-sm"
                    style={{ background: colorOf(name) }}
                  />
                  {name}
                </span>
              ))
            ) : (
              <span className="text-xs text-[var(--color-ink-muted)]">
                这一章没有主要角色在场。
              </span>
            )}
          </div>
          {selPresent.length >= 2 && (
            <>
              <p className="mt-2 text-sm text-[var(--color-ink)] leading-relaxed">
                {selEv?.loading
                  ? "正在从这一章原文里找出处…"
                  : selEv?.found
                    ? selEv.text
                    : "这一章原文里没比对到能坐实同场的句子。"}
              </p>
              {selEv && !selEv.loading && selEv.found && (
                <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
                  原文出处 · 第 {selChapter} 章（点开现取）
                </p>
              )}
            </>
          )}
        </div>
      )}

      {loading ? (
        <RunningProcess label="重出人物在场图" />
      ) : (
        <RunStats trace={trace} note={`${totalPresenceCells} 处在场`} />
      )}
    </div>
  );
}
