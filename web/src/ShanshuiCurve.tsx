// ---------------------------------------------------------------------------
// ShanshuiCurve — 事件密度曲线（NarrativeCurve 的品读视图）
//
// 1.5.x 重做(作者拍板):旧版纵轴画的是 tension(模型一句话糊的标量,跨次抖、不可信),还跟节奏曲线
// 画同一个东西、重复。新版纵轴换成"能数的事":每章高度 = 事件数 + 转折数(伏笔回收),全是从章脉
// events/foreshadow 数出来、每条能回原文核验的。山势起落=哪几章戏多、哪几章平铺过渡;朱砂点=有
// 转折的章(伏笔在这章收掉)。tension 不再进这张图,只在选中章明细里附带标"模型判读"。
//
// 还是水墨长卷的底子:墨色面积铺出戏分布 + 平滑山脊(Catmull-Rom) + 朱砂点标转折 + 钤印。
// 动画:纯 CSS clip-path 扫场,默认态完全可见、动画只增强。绝不用 rAF 当显示开关(headless/后台
// 标签会暂停 rAF,那样画面会卡成空白)。鼠标移到哪吸附到最近那章,点选钉住看那章发生的几件事。
// ---------------------------------------------------------------------------

import { useMemo, useRef, useState } from "react";

import { smoothLine } from "./vizCurve";

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
    // 转折章 = 有伏笔回收的章 → 朱砂点钉在它的脊高上
    const turns = chapters
      .map((c, i) => ({ c, i, x: xAt(i), y: yAt(c.height) }))
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
      className="w-full border border-[var(--color-rule)] rounded"
      style={{ background: "var(--color-paper)", touchAction: "none" }}
    >
      {/* 入场扫场：纯 CSS（不跑也完全可见，动画只增强；绝不用 rAF 当显示开关） */}
      <style>{`@keyframes ss-sweep{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}`}</style>

      {/* 事件数横向参考刻度 */}
      {ticks.map((v) => {
        const y = yAt(v);
        return (
          <g key={`tick-${v}`}>
            <line x1={PAD_L} y1={y} x2={W - PAD_R} y2={y} stroke="var(--color-rule)" strokeWidth={0.5} opacity={0.55} />
            <text x={PAD_L - 4} y={y + 3} textAnchor="end" fontSize={8} fill="var(--color-ink-muted)">
              {v}
            </text>
          </g>
        );
      })}

      <g style={{ animation: "ss-sweep .85s ease-out" }}>
        {/* 远景脊：淡墨垫底给纵深 */}
        <path d={farPath} fill="var(--color-ink)" opacity={0.1} />
        {/* 近景面积：戏分布主体 */}
        <path d={nearPath} fill="var(--color-ink)" opacity={0.28} />
        {/* 脊主线 */}
        <path d={ridgePath} fill="none" stroke="var(--color-ink)" strokeWidth={1.1} strokeLinejoin="round" opacity={0.55} />
        {/* 基线 */}
        <line x1={PAD_L} y1={BASE} x2={W - PAD_R} y2={BASE} stroke="var(--color-ink-muted)" strokeWidth={0.8} opacity={0.5} />

        {/* 朱砂题点：有伏笔回收的转折章。竖一道淡引线 + 圈点，让转折章在面上跳出来 */}
        {turns.map((p) => (
          <g key={`tp-${p.i}`}>
            <line x1={p.x} y1={p.y} x2={p.x} y2={BASE} stroke="var(--color-seal)" strokeWidth={0.7} opacity={0.32} />
            <circle
              cx={p.x}
              cy={p.y}
              r={selected === p.c.chapter ? 5 : 3.4}
              fill="var(--color-seal)"
              opacity={0.92}
            />
          </g>
        ))}

        {/* 章号刻度 */}
        {chapters.map((c, i) =>
          n <= 20 || i % 5 === 0 ? (
            <text key={`ax-${i}`} x={xAt(i)} y={H - 8} textAnchor="middle" fontSize={9} fill="var(--color-ink-muted)">
              {c.chapter}
            </text>
          ) : null,
        )}
      </g>

      {/* 悬停吸附：竖向引导 + 脊上的圈 + 浮动标注（事件数/转折数） */}
      {hoverC && hover !== selected && (
        <g style={{ pointerEvents: "none" }}>
          <line x1={xAt(idxOf(hover!))} y1={yAt(hoverC.height)} x2={xAt(idxOf(hover!))} y2={BASE} stroke="var(--color-ink-muted)" strokeWidth={0.7} strokeDasharray="2 2" opacity={0.55} />
          <circle cx={xAt(idxOf(hover!))} cy={yAt(hoverC.height)} r={3.6} fill="none" stroke="var(--color-seal)" strokeWidth={1.4} opacity={0.85} />
          <text x={Math.min(W - PAD_R - 4, Math.max(PAD_L + 4, xAt(idxOf(hover!))))} y={Math.max(TOP, yAt(hoverC.height) - 8)} textAnchor="middle" fontSize={11} fill="var(--color-ink)" style={{ fontFamily: "var(--font-display)" }}>
            第{hoverC.chapter}章 · {hoverC.event_count}事{hoverC.turning_count > 0 ? ` · ${hoverC.turning_count}转` : ""}
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

      {/* 透明覆盖层：吸附 hover + 点选 */}
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
