// ---------------------------------------------------------------------------
// ShanshuiCurve — 叙事张力的山水长卷（NarrativeCurve 的品读视图）
//
// 把逐章张力数据画成水墨山水：山势=张力起落，平缓处留白成江水，朱砂点=核验过的高潮章。
// 不是装饰画——山的形状就是真数据（probe 实测张力相对形状跨次稳，σ≈0.5），点任一章回原文。
//
// 细节化：远/中/近三层墨色叠出纵深 + 烟霭留白带 + 平滑山脊（Catmull-Rom）+ 皴笔回脊 + 江水涟漪 + 钤印。
// 动画：长卷自左向右徐徐展开——**纯 CSS clip-path 扫场**，默认态完全可见、动画只是增强。绝不用
//   requestAnimationFrame 当显示开关（headless / 后台标签会暂停 rAF，那样画面会卡成空白）。
// 找节点：鼠标移到哪就吸附到最近那一章，浮出标注（不必精准点中），点选则钉住看原文。
// 张力诚实呈现：只给相对档（平缓/起伏/紧张/高潮），不印"9/10"那种假精确（绝对分跨次会抖）。
// ---------------------------------------------------------------------------

import { useMemo, useRef, useState } from "react";

export interface CurveChapter {
  chapter: number;
  tension: number;
  sentiment: number;
  pov: string;
  mainline: boolean;
  evidence: string;
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
const TOP = 20;
const RANGE = 132; // 张力 0-10 映射到的山高
const BASE = TOP + RANGE; // 山脚 / 水岸基线
const WATER = 22;
const H = BASE + WATER + 26;

export function tensionBand(t: number): string {
  if (t >= 8) return "高潮";
  if (t >= 6) return "紧张";
  if (t >= 4) return "起伏";
  return "平缓";
}

// 一串点连成平滑曲线（Catmull-Rom 转三次贝塞尔）——山脊要流动，不要折线的硬棱角。
function smoothLine(pts: [number, number][]): string {
  if (pts.length < 2) return pts.length ? `M${pts[0][0]},${pts[0][1]}` : "";
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? pts[i + 1];
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

export function ShanshuiCurve({ chapters, selected, onSelect }: ShanshuiCurveProps) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const layout = useMemo(() => {
    const n = chapters.length;
    const inner = W - PAD_L - PAD_R;
    const xAt = (i: number) => PAD_L + (n <= 1 ? inner / 2 : (i / (n - 1)) * inner);
    const ridgeY = (t: number) =>
      BASE - (Math.max(0, Math.min(10, t)) / 10) * RANGE;
    const sm = (i: number) => {
      const a = chapters[Math.max(0, i - 1)].tension;
      const b = chapters[Math.min(n - 1, i + 1)].tension;
      return (a + chapters[i].tension + b) / 3;
    };
    const near: [number, number][] = chapters.map((c, i) => [xAt(i), ridgeY(c.tension)]);
    const mid: [number, number][] = chapters.map((_, i) => [
      xAt(i),
      BASE - (sm(i) / 10) * RANGE * 0.78 - 18,
    ]);
    const far: [number, number][] = chapters.map((_, i) => [
      xAt(i),
      BASE - (sm(i) / 10) * RANGE * 0.5 - 34,
    ]);
    const peaks = chapters
      .map((c, i) => ({ c, i, x: xAt(i), y: ridgeY(c.tension) }))
      .filter((p) => p.c.verified && p.c.tension >= 6)
      .sort((a, b) => b.c.tension - a.c.tension)
      .slice(0, 8);
    return { n, inner, xAt, ridgeY, near, mid, far, peaks };
  }, [chapters]);

  const { n, inner, xAt, ridgeY, near, mid, far, peaks } = layout;

  const baseR = `L${W - PAD_R},${BASE} L${PAD_L},${BASE} Z`;
  const nearPath = smoothLine(near) + ` ${baseR}`;
  const midPath = smoothLine(mid) + ` ${baseR}`;
  const farPath = smoothLine(far) + ` ${baseR}`;
  const ridgePath = smoothLine(near);
  const innerRidge = (drop: number) =>
    smoothLine(near.map(([x, y]) => [x, Math.min(BASE, y + drop)] as [number, number]));

  const idxOf = (chapter: number) => chapters.findIndex((c) => c.chapter === chapter);
  const hoverC = hover != null ? chapters[idxOf(hover)] : null;
  const selC = selected != null ? chapters[idxOf(selected)] : null;

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
      {/* 入场扫场：纯 CSS（不跑也是完全可见，动画只是增强；绝不用 rAF 当显示开关） */}
      <style>{`@keyframes ss-sweep{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}`}</style>

      {/* 静态山水（随长卷展开） */}
      <g style={{ animation: "ss-sweep .85s ease-out" }}>
        <path d={farPath} fill="var(--color-ink)" opacity={0.08} />
        {/* 烟霭留白带：纸色压一层，把远山推远 */}
        <rect x={PAD_L} y={TOP + 6} width={inner} height={42} fill="var(--color-paper)" opacity={0.42} />
        <path d={midPath} fill="var(--color-ink)" opacity={0.16} />
        <path d={nearPath} fill="var(--color-ink)" opacity={0.3} />
        {/* 皴笔：近山内两条更淡的回脊纹理 */}
        <path d={innerRidge(10)} fill="none" stroke="var(--color-ink)" strokeWidth={0.5} opacity={0.16} />
        <path d={innerRidge(22)} fill="none" stroke="var(--color-ink)" strokeWidth={0.5} opacity={0.1} />
        {/* 山脊主线 */}
        <path d={ridgePath} fill="none" stroke="var(--color-ink)" strokeWidth={1.1} strokeLinejoin="round" opacity={0.5} />
        {/* 江水 + 涟漪 */}
        <rect x={PAD_L} y={BASE} width={inner} height={WATER} fill="var(--color-paper-raised)" opacity={0.65} />
        <line x1={PAD_L + 16} y1={BASE + 7} x2={PAD_L + inner * 0.42} y2={BASE + 7} stroke="var(--color-rule)" strokeWidth={0.6} opacity={0.8} />
        <line x1={PAD_L + inner * 0.52} y1={BASE + 13} x2={W - PAD_R - 22} y2={BASE + 13} stroke="var(--color-rule)" strokeWidth={0.6} opacity={0.7} />
        <line x1={PAD_L + inner * 0.2} y1={BASE + 17} x2={PAD_L + inner * 0.62} y2={BASE + 17} stroke="var(--color-rule)" strokeWidth={0.5} opacity={0.55} />
        {/* 朱砂题点：核验过的高潮章 */}
        {peaks.map((p) => (
          <circle
            key={`pk-${p.i}`}
            cx={p.x}
            cy={p.y}
            r={selected === p.c.chapter ? 5 : 3.2}
            fill="var(--color-seal)"
            opacity={0.9}
          />
        ))}
        {/* 章号刻度 */}
        {chapters.map((c, i) =>
          n <= 20 || i % 5 === 0 ? (
            <text key={`ax-${i}`} x={xAt(i)} y={H - 7} textAnchor="middle" fontSize={9} fill="var(--color-ink-muted)">
              {c.chapter}
            </text>
          ) : null,
        )}
      </g>

      {/* 悬停吸附：竖向引导 + 山脊上的圈 + 浮动标注（相对档，不印精确分） */}
      {hoverC && hover !== selected && (
        <g style={{ pointerEvents: "none" }}>
          <line x1={xAt(idxOf(hover!))} y1={ridgeY(hoverC.tension)} x2={xAt(idxOf(hover!))} y2={BASE + WATER} stroke="var(--color-ink-muted)" strokeWidth={0.7} strokeDasharray="2 2" opacity={0.55} />
          <circle cx={xAt(idxOf(hover!))} cy={ridgeY(hoverC.tension)} r={3.6} fill="none" stroke="var(--color-seal)" strokeWidth={1.4} opacity={0.85} />
          <text x={Math.min(W - PAD_R - 4, Math.max(PAD_L + 4, xAt(idxOf(hover!))))} y={Math.max(TOP, ridgeY(hoverC.tension) - 8)} textAnchor="middle" fontSize={11} fill="var(--color-ink)" style={{ fontFamily: "var(--font-display)" }}>
            第{hoverC.chapter}章 · {tensionBand(hoverC.tension)}
          </text>
        </g>
      )}

      {/* 选中章：钉住的竖向朱砂线 + 山脊大点 */}
      {selC && (
        <g style={{ pointerEvents: "none" }}>
          <line x1={xAt(idxOf(selected!))} y1={TOP} x2={xAt(idxOf(selected!))} y2={BASE + WATER} stroke="var(--color-seal)" strokeWidth={1} opacity={0.5} />
          <circle cx={xAt(idxOf(selected!))} cy={ridgeY(selC.tension)} r={5} fill="var(--color-seal)" />
        </g>
      )}

      {/* 钤印（数字善本签名） */}
      <rect x={W - PAD_R - 30} y={TOP - 4} width={26} height={26} rx={3} fill="var(--color-seal)" opacity={0.92} />
      <text x={W - PAD_R - 17} y={TOP + 4} textAnchor="middle" fontSize={10} fill="var(--color-paper)" style={{ fontFamily: "var(--font-display)" }}>书</text>
      <text x={W - PAD_R - 17} y={TOP + 15} textAnchor="middle" fontSize={10} fill="var(--color-paper)" style={{ fontFamily: "var(--font-display)" }}>鉴</text>

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
