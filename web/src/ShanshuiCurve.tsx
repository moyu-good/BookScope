// ---------------------------------------------------------------------------
// ShanshuiCurve — 转折落点条（NarrativeCurve 的品读视图）
//
// 重做（2026-07-08，按 viz 质量尺子）：删掉原来那座「每章事件多少」的淡墨密度山——
// 它编码的是机械计数，没意义，还占满画面喧宾夺主（尺子第 1 条）。现在只画一件有意义、
// 有依据的事：**全书的转折 / 伏笔回收落在哪几章、每处收了几条**。
//   · 横轴 = 章（一条素净的墨尺）。
//   · 每个转折章竖一道朱砂，高度 = 这章收掉的伏笔 / 转折数（真数，逐条能翻回原文），
//     顶上一个朱砂点、把章号印在边上。密处高、疏处矮，一眼看出高潮压在哪几章。
//   · 没有转折的章只在尺上留个极淡的刻度，不抢戏。
//   · 史书这类没有「伏笔回收」的文本，转折本就少甚至没有——那就如实留白、明说一句，
//     绝不拿密度山硬凑（尺子第 7 条：题材不合就退场）。
//
// 动画纯 CSS（朱砂竖线从脚往上长一次），默认态完全可见；绝不用 rAF 当显示开关。
// ---------------------------------------------------------------------------

import { useRef, useState } from "react";

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
  height: number; // event_count + turning_count（旧纵轴，现在不用来画高度）
  is_turning: boolean;
  events: CurveEvent[];
  turning_points: CurveTurning[];
  // 以下只进选中章明细，标「模型判读」，不当纵轴：
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
const PAD_R = 22;
const TOP = 24; // 竖线最高不超过这里
const BASE = 104; // 墨尺基线
const H = 128;
const STEM_MIN = 18; // 单处回收的最矮竖线，保证看得见
const STEM_MAX = BASE - TOP; // 最多回收的最高竖线

export function ShanshuiCurve({ chapters, selected, onSelect }: ShanshuiCurveProps) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const n = chapters.length;
  const inner = W - PAD_L - PAD_R;
  const xAt = (i: number) => PAD_L + (n <= 1 ? inner / 2 : (i / (n - 1)) * inner);
  const idxOf = (chapter: number) => chapters.findIndex((c) => c.chapter === chapter);

  const maxTurn = Math.max(1, ...chapters.map((c) => c.turning_count));
  const stemH = (tc: number) =>
    STEM_MIN + (Math.max(1, tc) - 1) / Math.max(1, maxTurn - 1) * (STEM_MAX - STEM_MIN);
  const turns = chapters
    .map((c, i) => ({ c, i, x: xAt(i), h: stemH(c.turning_count) }))
    .filter((p) => p.c.is_turning);

  const hoverC = hover != null ? chapters[idxOf(hover)] : null;

  function nearestChapter(clientX: number): number | null {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * W;
    const i = Math.max(0, Math.min(n - 1, Math.round(((x - PAD_L) / inner) * (n - 1))));
    return chapters[i].chapter;
  }

  // 史书 / 论说文这类没有伏笔回收 → 转折条为空。如实留白，不硬画。
  const empty = turns.length === 0;

  return (
    <div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full border border-[var(--color-rule)] rounded"
        style={{ background: "var(--color-paper)", cursor: empty ? "default" : "pointer" }}
        onPointerMove={(e) => !empty && setHover(nearestChapter(e.clientX))}
        onPointerLeave={() => setHover(null)}
        onClick={(e) => {
          if (empty) return;
          const ch = nearestChapter(e.clientX);
          if (ch != null) onSelect(ch);
        }}
      >
        <style>{`@keyframes ss-grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}`}</style>

        {/* 墨尺基线 */}
        <line
          x1={PAD_L}
          y1={BASE}
          x2={W - PAD_R}
          y2={BASE}
          stroke="var(--color-ink)"
          strokeWidth={1}
          opacity={0.5}
        />

        {/* 每章一个极淡刻度，给横轴一点密度感，不抢戏 */}
        {chapters.map((_, i) => (
          <line
            key={`t-${i}`}
            x1={xAt(i)}
            y1={BASE}
            x2={xAt(i)}
            y2={BASE + 3}
            stroke="var(--color-ink-muted)"
            strokeWidth={0.75}
            opacity={0.35}
          />
        ))}

        {/* 稀疏章号刻度（首、尾、每 5 章），转折章的章号另标在朱砂点边 */}
        {chapters.map((c, i) =>
          i === 0 || i === n - 1 || (i % 5 === 0 && !c.is_turning) ? (
            <text
              key={`ax-${i}`}
              x={xAt(i)}
              y={BASE + 15}
              textAnchor="middle"
              fontSize={8.5}
              fill="var(--color-ink-muted)"
              opacity={0.65}
            >
              {c.chapter}
            </text>
          ) : null,
        )}

        {/* 转折落点：朱砂竖线（高 = 收几条伏笔）+ 顶点 + 章号 */}
        {turns.map((p) => {
          const on = selected === p.c.chapter;
          const top = BASE - p.h;
          const r = (on ? 4.6 : 3.6) + Math.min(2.4, (p.c.turning_count - 1) * 0.9);
          const labelY = Math.max(TOP - 6, top - r - 5);
          return (
            <g key={`tp-${p.i}`}>
              {/* 竖线：脚在基线，纯 CSS 从脚往上长 */}
              <line
                x1={p.x}
                y1={BASE}
                x2={p.x}
                y2={top}
                stroke="var(--color-seal)"
                strokeWidth={on ? 2 : 1.3}
                opacity={on ? 0.9 : 0.62}
                style={{ transformOrigin: `${p.x}px ${BASE}px`, animation: "ss-grow .5s ease-out both" }}
              />
              {/* 朱砂晕 + 点 */}
              <circle cx={p.x} cy={top} r={r + 3} fill="var(--color-seal)" opacity={0.14} />
              <circle
                cx={p.x}
                cy={top}
                r={r}
                fill="var(--color-seal)"
                opacity={0.95}
                stroke="var(--color-paper)"
                strokeWidth={0.8}
              />
              {p.c.turning_count > 1 && (
                <text
                  x={p.x}
                  y={top + 2.6}
                  textAnchor="middle"
                  fontSize={7.5}
                  fontWeight={700}
                  fill="var(--color-paper)"
                  style={{ pointerEvents: "none" }}
                >
                  {p.c.turning_count}
                </text>
              )}
              {/* 章号：直接印在图上，答「转折落在哪几章」 */}
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

        {/* 悬停：极淡竖引导 + 章标 */}
        {hoverC && hover !== selected && (
          <g style={{ pointerEvents: "none" }}>
            <line
              x1={xAt(idxOf(hover!))}
              y1={TOP}
              x2={xAt(idxOf(hover!))}
              y2={BASE}
              stroke="var(--color-ink-muted)"
              strokeWidth={0.7}
              strokeDasharray="2 2"
              opacity={0.5}
            />
            <text
              x={Math.min(W - PAD_R - 4, Math.max(PAD_L + 4, xAt(idxOf(hover!))))}
              y={TOP - 8}
              textAnchor="middle"
              fontSize={10.5}
              fill={hoverC.is_turning ? "var(--color-seal)" : "var(--color-ink)"}
              style={{ fontFamily: "var(--font-display)" }}
            >
              第{hoverC.chapter}章
              {hoverC.is_turning ? ` · 收 ${hoverC.turning_count} 条` : ""}
            </text>
          </g>
        )}

        {/* 钤印 */}
        <rect x={W - PAD_R - 26} y={6} width={24} height={24} rx={3} fill="var(--color-seal)" opacity={0.92} />
        <text x={W - PAD_R - 14} y={15} textAnchor="middle" fontSize={9.5} fill="var(--color-paper)" style={{ fontFamily: "var(--font-display)" }}>书</text>
        <text x={W - PAD_R - 14} y={25} textAnchor="middle" fontSize={9.5} fill="var(--color-paper)" style={{ fontFamily: "var(--font-display)" }}>鉴</text>

        {/* 空态：史书这类没有伏笔回收，如实留白 */}
        {empty && (
          <text
            x={W / 2}
            y={BASE - 28}
            textAnchor="middle"
            fontSize={12}
            fill="var(--color-ink-muted)"
            style={{ fontFamily: "var(--font-display)" }}
          >
            这本书没有明显的转折 / 伏笔回收落点（史书、论说文常如此）
          </text>
        )}
      </svg>
    </div>
  );
}
