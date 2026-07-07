// ---------------------------------------------------------------------------
// ShanshuiCurve — 转折落点长卷（NarrativeCurve 的品读视图）
//
// 这张图只答一个问题:全书的转折 / 伏笔回收砸在哪几章。重心从"数量密度"挪到"转折在哪"。
//
// 主角是转折章(is_turning):朱砂大点钉在山脊上、竖一道醒目的引线到脚、把章号直接标在点边上,
// 让人一眼看出转折落在哪几章、密还是疏;一章回收多处伏笔的点更大。事件密度(每章 event+转折数)
// 退成一层淡墨山形,只给个节奏感垫底,绝不喧宾夺主。tension 不进这张图(模型眼估的标量不可信),
// 只在选中章明细里附带标"模型判读"。
//
// 还是水墨长卷的底子:淡墨面积铺出节奏 + 平滑山脊(Catmull-Rom) + 朱砂转折点(前景) + 钤印。
// 动画:纯 CSS clip-path 扫场,默认态完全可见、动画只增强。绝不用 rAF 当显示开关(headless/后台
// 标签会暂停 rAF,那样画面会卡成空白)。鼠标移到哪吸附到最近那章,点选钉住看那章的转折和原文。
// ---------------------------------------------------------------------------

import { useMemo, useRef, useState } from "react";

import { smoothLine } from "./vizCurve";
import { usePanZoom } from "./usePanZoom";

export interface CurveEvent {
  text: string;
  evidence: string;
  verified: boolean;
}

export interface CurveTurning {
  hook: string;
  kind: string;
  evidence: string;
  verified: boolean;
}

export interface CurveChapter {
  chapter: number;
  event_count: number;
  turning_count: number;
  height: number; // event_count + turning_count，纵轴
  is_turning: boolean;
  events: CurveEvent[];
  turning_points: CurveTurning[];
  // 以下只进选中章明细，标"模型判读"，不当纵轴：
  tension: number;
  sentiment: number;
  pov: string;
  mainline: boolean;
  evidence: string; // 章代表句兜底
  verified: boolean;
  match_score: number;
}

interface ShanshuiCurveProps {
  chapters: CurveChapter[];
  selected: number | null;
  onSelect: (chapter: number) => void;
}

const W = 760;
const PAD_L = 30;
const PAD_R = 18;
const TOP = 22;
const RANGE = 150; // 高度映射到的山高
const BASE = TOP + RANGE; // 山脚基线
const H = BASE + 30;

export function ShanshuiCurve({ chapters, selected, onSelect }: ShanshuiCurveProps) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  // pan/zoom + 双指 pinch（移动端）：大书章多时山势挤，手机上捏合才看得清转折点。
  // 本图有全画布覆盖层 rect 做 hover 吸附 + 点击选章，pinch/pan 进行中（pointersCount>0）
  // 不吸附 hover，避免平移时 hover 乱跳；click 选章在 tap（无 move）时照常。
  const {
    view,
    pointersCount,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
    onWheel,
  } = usePanZoom(svgRef, { width: W, height: H });

  const layout = useMemo(() => {
    const n = chapters.length;
    const inner = W - PAD_L - PAD_R;
    // 纵轴按全书最高那章归一(至少留 1,免得全 0 时除零);留头部余量不顶到天。
    const maxH = Math.max(1, ...chapters.map((c) => c.height));
    const xAt = (i: number) => PAD_L + (n <= 1 ? inner / 2 : (i / (n - 1)) * inner);
    const yAt = (h: number) => BASE - (Math.max(0, h) / maxH) * RANGE;
    // 三章滑动平均出一条柔和的远景脊，叠在实测脊后面给纵深
    const sm = (i: number) => {
      const a = chapters[Math.max(0, i - 1)].height;
      const b = chapters[Math.min(n - 1, i + 1)].height;
      return (a + chapters[i].height + b) / 3;
    };
    const near: [number, number][] = chapters.map((c, i) => [xAt(i), yAt(c.height)]);
    const far: [number, number][] = chapters.map((_, i) => [xAt(i), yAt(sm(i) * 0.62)]);
    // 转折章 = 有伏笔回收的章 → 朱砂点钉在它的脊高上。回收几处就把点画多大（1 处起，越多越大）。
    const maxT = Math.max(1, ...chapters.map((c) => c.turning_count));
    const turns = chapters
      .map((c, i) => ({
        c,
        i,
        x: xAt(i),
        y: yAt(c.height),
        // 3.6 起步，按回收处数放大到 6.4，让"密处"的转折章更抢眼
        r: 3.6 + (Math.max(1, c.turning_count) - 1) / Math.max(1, maxT - 1) * 2.8,
      }))
      .filter((p) => p.c.is_turning);
    return { n, inner, maxH, xAt, yAt, near, far, turns };
  }, [chapters]);

  const { n, inner, maxH, xAt, yAt, near, far, turns } = layout;

  const baseR = `L${W - PAD_R},${BASE} L${PAD_L},${BASE} Z`;
  const nearPath = smoothLine(near) + ` ${baseR}`;
  const farPath = smoothLine(far) + ` ${baseR}`;
  const ridgePath = smoothLine(near);

  const idxOf = (chapter: number) => chapters.findIndex((c) => c.chapter === chapter);
  const hoverC = hover != null ? chapters[idxOf(hover)] : null;
  const selC = selected != null ? chapters[idxOf(selected)] : null;

  // 横向参考刻度（事件数标尺）：把 maxH 分 3~4 档画淡线，让"几件事"读得出绝对量
  const ticks = useMemo(() => {
    const step = maxH <= 4 ? 1 : Math.ceil(maxH / 4);
    const out: number[] = [];
    for (let v = step; v <= maxH; v += step) out.push(v);
    return out;
  }, [maxH]);

  function handleMove(e: React.PointerEvent<SVGRectElement>) {
    // pinch/pan 进行中不吸附 hover（pointersCount>0 = 有指按在画布上拖/捏），否则平移时 hover 乱跳。
    if (pointersCount > 0) return;
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.max(0, Math.min(n - 1, Math.round(((x - PAD_L) / inner) * (n - 1))));
    setHover(chapters[i].chapter);
  }

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${W} ${H}`}
      className="w-full border border-[var(--color-rule)] rounded touch-none"
      style={{ background: "var(--color-paper)" }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onPointerLeave={onPointerUp}
      onWheel={onWheel}
    >
      {/* 入场扫场：纯 CSS（不跑也完全可见，动画只增强；绝不用 rAF 当显示开关） */}
      <style>{`@keyframes ss-sweep{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}`}</style>
      {/* 缩放平移层：刻度 + 山势 + 转折点 + 钤印都在这个 <g> 里；覆盖层 rect 留在 g 外负责收事件 */}
      <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>

      {/* 事件数横向参考刻度：现在只是背景山形的淡标尺，压更淡，别跟前景转折点抢注意力 */}
      {ticks.map((v) => {
        const y = yAt(v);
        return (
          <g key={`tick-${v}`}>
            <line x1={PAD_L} y1={y} x2={W - PAD_R} y2={y} stroke="var(--color-rule)" strokeWidth={0.5} opacity={0.32} />
            <text x={PAD_L - 4} y={y + 3} textAnchor="end" fontSize={7.5} fill="var(--color-ink-muted)" opacity={0.6}>
              {v}
            </text>
          </g>
        );
      })}

      <g style={{ animation: "ss-sweep .85s ease-out" }}>
        {/* ── 背景层：事件密度山形，退成淡墨只给节奏感，不抢转折点的戏 ── */}
        {/* 远景脊：极淡墨垫底给纵深 */}
        <path d={farPath} fill="var(--color-ink)" opacity={0.05} />
        {/* 近景面积：节奏分布，压暗到很淡 */}
        <path d={nearPath} fill="var(--color-ink)" opacity={0.12} />
        {/* 脊主线：细一道淡墨勾出山势 */}
        <path d={ridgePath} fill="none" stroke="var(--color-ink)" strokeWidth={0.8} strokeLinejoin="round" opacity={0.28} />
        {/* 基线 */}
        <line x1={PAD_L} y1={BASE} x2={W - PAD_R} y2={BASE} stroke="var(--color-ink-muted)" strokeWidth={0.8} opacity={0.45} />

        {/* ── 前景层（主角）：转折 / 伏笔回收落在哪几章 ── */}
        {/* 有伏笔回收的转折章：醒目竖引线 + 朱砂大点 + 章号直接标在点边，一眼看清落点疏密 */}
        {turns.map((p) => {
          const on = selected === p.c.chapter;
          const r = on ? p.r + 1.6 : p.r;
          // 章号标签避开顶边；点高处朝下标、低处朝上标，尽量不压到脊线
          const labelY = p.y < TOP + 16 ? p.y + 14 : p.y - r - 5;
          return (
            <g key={`tp-${p.i}`}>
              {/* 引线：从脚拉到脊，让转折章像一根根钉子立在长卷上 */}
              <line x1={p.x} y1={p.y} x2={p.x} y2={BASE} stroke="var(--color-seal)" strokeWidth={on ? 1.3 : 0.9} opacity={on ? 0.6 : 0.42} />
              {/* 朱砂晕：一圈淡朱砂让点更跳，回收多处的更大 */}
              <circle cx={p.x} cy={p.y} r={r + 3} fill="var(--color-seal)" opacity={0.14} />
              {/* 朱砂点本体 */}
              <circle cx={p.x} cy={p.y} r={r} fill="var(--color-seal)" opacity={0.95} stroke="var(--color-paper)" strokeWidth={0.8} />
              {/* 回收多处（>1）在点上标个白数字，看出这章收了几条伏笔 */}
              {p.c.turning_count > 1 && (
                <text x={p.x} y={p.y + 2.6} textAnchor="middle" fontSize={7.5} fontWeight={700} fill="var(--color-paper)" style={{ pointerEvents: "none" }}>
                  {p.c.turning_count}
                </text>
              )}
              {/* 章号标签：直接印在图上，答"转折落在哪几章" */}
              <text
                x={p.x}
                y={labelY}
                textAnchor="middle"
                fontSize={on ? 11 : 9.5}
                fontWeight={on ? 700 : 600}
                fill="var(--color-seal)"
                style={{ fontFamily: "var(--font-display)", pointerEvents: "none" }}
              >
                {p.c.chapter}
              </text>
            </g>
          );
        })}

        {/* 底部章号刻度：只做稀疏定位标尺，转折章的章号已标在朱砂点边上，这里淡处理不抢戏 */}
        {chapters.map((c, i) =>
          (n <= 20 || i % 5 === 0) && !c.is_turning ? (
            <text key={`ax-${i}`} x={xAt(i)} y={H - 8} textAnchor="middle" fontSize={8.5} fill="var(--color-ink-muted)" opacity={0.7}>
              {c.chapter}
            </text>
          ) : null,
        )}
      </g>

      {/* 悬停吸附：竖向引导 + 脊上的圈 + 浮动标注。转折章先报"N处转折/伏笔回收"，事件数退成附注 */}
      {hoverC && hover !== selected && (
        <g style={{ pointerEvents: "none" }}>
          <line x1={xAt(idxOf(hover!))} y1={yAt(hoverC.height)} x2={xAt(idxOf(hover!))} y2={BASE} stroke="var(--color-ink-muted)" strokeWidth={0.7} strokeDasharray="2 2" opacity={0.55} />
          <circle cx={xAt(idxOf(hover!))} cy={yAt(hoverC.height)} r={hoverC.is_turning ? 4.4 : 3.6} fill="none" stroke="var(--color-seal)" strokeWidth={1.4} opacity={0.85} />
          <text x={Math.min(W - PAD_R - 4, Math.max(PAD_L + 4, xAt(idxOf(hover!))))} y={Math.max(TOP, yAt(hoverC.height) - 8)} textAnchor="middle" fontSize={11} fill={hoverC.is_turning ? "var(--color-seal)" : "var(--color-ink)"} style={{ fontFamily: "var(--font-display)" }}>
            第{hoverC.chapter}章{hoverC.is_turning ? ` · ${hoverC.turning_count}处转折` : ` · ${hoverC.event_count}事`}
          </text>
        </g>
      )}

      {/* 选中章：钉住的竖向朱砂线 + 脊上大点 */}
      {selC && (
        <g style={{ pointerEvents: "none" }}>
          <line x1={xAt(idxOf(selected!))} y1={TOP} x2={xAt(idxOf(selected!))} y2={BASE} stroke="var(--color-seal)" strokeWidth={1} opacity={0.5} />
          <circle cx={xAt(idxOf(selected!))} cy={yAt(selC.height)} r={5} fill="var(--color-seal)" />
        </g>
      )}

      {/* 钤印（数字善本签名） */}
      <rect x={W - PAD_R - 30} y={TOP - 6} width={26} height={26} rx={3} fill="var(--color-seal)" opacity={0.92} />
      <text x={W - PAD_R - 17} y={TOP + 2} textAnchor="middle" fontSize={10} fill="var(--color-paper)" style={{ fontFamily: "var(--font-display)" }}>书</text>
      <text x={W - PAD_R - 17} y={TOP + 13} textAnchor="middle" fontSize={10} fill="var(--color-paper)" style={{ fontFamily: "var(--font-display)" }}>鉴</text>

      </g>

      {/* 透明覆盖层：吸附 hover + 点选。留在 transform g 外——它用 viewBox 坐标做 hit-test，不能被缩放变换。 */}
      <rect
        x={0}
        y={0}
        width={W}
        height={H}
        fill="transparent"
        style={{ cursor: "pointer" }}
        onPointerMove={handleMove}
        onPointerLeave={() => setHover(null)}
        onClick={() => hover != null && onSelect(hover)}
      />
    </svg>
  );
}
