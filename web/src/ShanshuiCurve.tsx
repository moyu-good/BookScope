// ---------------------------------------------------------------------------
// ShanshuiCurve — 叙事节奏弧线（NarrativeCurve 的品读视图）
//
// 重做二（2026-07-09，按作者反馈）：上一版删密度山后矫枉过正——只在转折/伏笔章立朱砂,
// 正常章空着,看着像"没分析",还跟「伏笔回收」撞脸。这一版改回**每章都有值**的节奏弧线:
//   · 横轴 = 章;纵轴 = 张力的**相对起伏**（铺垫低、高潮高），逐章一个点连成一条线 =
//     全书节奏的形状（升-顶-落）。每章都在线上,不再有空章。
//   · 点色 = 这章的情感冷暖（喜胜聚偏朱、悲败散偏墨蓝、平稳灰）——第二个有意义的维度。
//   · 转折 / 伏笔回收章 = 线上加一枚朱砂环 + 章号,当**点缀**（保留"高潮压在哪几章"的信息,
//     但不再是整张图的主体）。这样跟「伏笔回收」分工清楚:这里看**节奏形状**,那里看**埋→收配对**。
//   · 点开某章 = 看那章原文（跟旧版共用下面的明细面板）。
//
// evidence-first / 不堆艺术（尺子 + feedback_viz_algorithm_rigor）：张力/情感是模型逐章判读、
// 绝对值会抖,所以**只画相对形状、明说"模型判读·看形状不看绝对值"**,每点锚得回原文;
// 不在不可信的数上堆花活。史书/论说文张力平 → 线就平,如实,不硬造起伏。
//
// 动画纯 CSS（线从左描出一次 + 点淡入），默认态完全可见;绝不用 rAF 当显示开关。
// ---------------------------------------------------------------------------

import { useMemo, useRef, useState } from "react";

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
  height: number; // 旧纵轴（event+turning），现在不用
  is_turning: boolean;
  events: CurveEvent[];
  turning_points: CurveTurning[];
  tension: number; // 0-10，模型逐章判读
  sentiment: number; // -5..5，情感方向
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
const TOP = 26; // 张力最高点不超过这里
const BASE = 104; // 墨尺基线（张力最低）
const H = 128;

// 情感冷暖：喜/胜/聚 偏朱，悲/败/散 偏墨蓝，平稳中性灰。跟关系编年色温同一套色。
function sentimentColor(s: number): string {
  if (s > 0) return "var(--color-seal)"; // 朱砂（暖）
  if (s < 0) return "#2E6B82"; // 墨蓝（冷）
  return "var(--color-ink-muted)"; // 平
}

export function ShanshuiCurve({ chapters, selected, onSelect }: ShanshuiCurveProps) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const n = chapters.length;
  const inner = W - PAD_L - PAD_R;
  const xAt = (i: number) => PAD_L + (n <= 1 ? inner / 2 : (i / (n - 1)) * inner);
  const idxOf = (chapter: number) => chapters.findIndex((c) => c.chapter === chapter);

  // 张力归一到本书自己的 [min,max]，画的是**相对**起伏形状（不是绝对分）。全平 → 落中线。
  const { pts, areaPath, linePath } = useMemo(() => {
    const ts = chapters.map((c) => (typeof c.tension === "number" ? c.tension : 0));
    const lo = Math.min(...ts, 0);
    const hi = Math.max(...ts, 1);
    const span = hi - lo;
    const yAt = (t: number) =>
      span <= 0 ? (BASE + TOP) / 2 : BASE - ((t - lo) / span) * (BASE - TOP);
    const p = chapters.map((c, i) => ({ x: xAt(i), y: yAt(c.tension || 0), c, i }));
    const line = p.map((q, i) => `${i === 0 ? "M" : "L"}${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(" ");
    const area =
      p.length > 0
        ? `M${p[0].x.toFixed(1)},${BASE} ` +
          p.map((q) => `L${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(" ") +
          ` L${p[p.length - 1].x.toFixed(1)},${BASE} Z`
        : "";
    return { pts: p, areaPath: area, linePath: line };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapters]);

  const hoverC = hover != null ? chapters[idxOf(hover)] : null;

  function nearestChapter(clientX: number): number | null {
    const svg = svgRef.current;
    if (!svg || n === 0) return null;
    const rect = svg.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * W;
    const i = Math.max(0, Math.min(n - 1, Math.round(((x - PAD_L) / inner) * (n - 1))));
    return chapters[i].chapter;
  }

  if (n === 0) {
    return (
      <div className="text-sm text-[var(--color-ink-muted)] px-2 py-6 text-center">
        还没读出逐章节奏。
      </div>
    );
  }

  return (
    <div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full border border-[var(--color-rule)] rounded"
        style={{ background: "var(--color-paper)", cursor: "pointer" }}
        onPointerMove={(e) => setHover(nearestChapter(e.clientX))}
        onPointerLeave={() => setHover(null)}
        onClick={(e) => {
          const ch = nearestChapter(e.clientX);
          if (ch != null) onSelect(ch);
        }}
      >
        <style>{`
          @keyframes ss-draw { from { stroke-dashoffset: var(--len); } to { stroke-dashoffset: 0; } }
          @keyframes ss-dot { from { opacity: 0; transform: scale(0); } to { opacity: 1; transform: none; } }
        `}</style>

        {/* 墨尺基线 */}
        <line x1={PAD_L} y1={BASE} x2={W - PAD_R} y2={BASE} stroke="var(--color-ink)" strokeWidth={1} opacity={0.45} />

        {/* 张力起伏：面 + 线（线从左描出一次） */}
        {areaPath && <path d={areaPath} fill="var(--color-seal)" opacity={0.06} />}
        {linePath && (
          <path
            d={linePath}
            fill="none"
            stroke="var(--color-ink)"
            strokeWidth={1.4}
            opacity={0.7}
            strokeLinejoin="round"
            style={{
              ["--len" as string]: "2000",
              strokeDasharray: 2000,
              animation: "ss-draw 1s ease-out both",
            }}
          />
        )}

        {/* 每章一个点：色 = 情感冷暖；转折章加朱砂环 + 章号 */}
        {pts.map((q) => {
          const on = selected === q.c.chapter;
          const turning = q.c.is_turning && q.c.turning_count > 0;
          const r = on ? 3.6 : 2.6;
          return (
            <g key={`pt-${q.i}`} style={{ transformOrigin: `${q.x}px ${q.y}px`, animation: "ss-dot .4s ease-out both", animationDelay: `${Math.min(q.i * 6, 500)}ms` }}>
              {turning && (
                <circle cx={q.x} cy={q.y} r={r + 3.4} fill="none" stroke="var(--color-seal)" strokeWidth={on ? 1.8 : 1.2} opacity={on ? 0.95 : 0.7} />
              )}
              <circle cx={q.x} cy={q.y} r={r} fill={sentimentColor(q.c.sentiment)} opacity={0.95} stroke="var(--color-paper)" strokeWidth={0.6} />
              {turning && (
                <text x={q.x} y={q.y - r - 6} textAnchor="middle" fontSize={on ? 10 : 8.5} fontWeight={on ? 700 : 600} fill="var(--color-seal)" style={{ fontFamily: "var(--font-display)", pointerEvents: "none" }}>
                  {q.c.chapter}
                </text>
              )}
            </g>
          );
        })}

        {/* 稀疏章号刻度（首、尾、每 ~1/5），转折章的章号已在点上标 */}
        {chapters.map((c, i) =>
          i === 0 || i === n - 1 || (n > 6 && i % Math.ceil(n / 6) === 0 && !c.is_turning) ? (
            <text key={`ax-${i}`} x={xAt(i)} y={BASE + 14} textAnchor="middle" fontSize={8.5} fill="var(--color-ink-muted)" opacity={0.6}>
              {c.chapter}
            </text>
          ) : null,
        )}

        {/* 悬停：竖引导 + 章标（张力相对 + 情感 + 是否转折） */}
        {hoverC && (
          <g style={{ pointerEvents: "none" }}>
            <line x1={xAt(idxOf(hover!))} y1={TOP} x2={xAt(idxOf(hover!))} y2={BASE} stroke="var(--color-ink-muted)" strokeWidth={0.7} strokeDasharray="2 2" opacity={0.5} />
            <text x={Math.min(W - PAD_R - 40, Math.max(PAD_L + 40, xAt(idxOf(hover!))))} y={TOP - 10} textAnchor="middle" fontSize={10.5} fill="var(--color-ink)" style={{ fontFamily: "var(--font-display)" }}>
              第{hoverC.chapter}章 · 张力{hoverC.tension}
              {hoverC.sentiment > 0 ? " · 情绪偏暖" : hoverC.sentiment < 0 ? " · 情绪偏冷" : ""}
              {hoverC.is_turning ? ` · 收${hoverC.turning_count}条伏笔` : ""}
            </text>
          </g>
        )}

        {/* 钤印 */}
        <rect x={W - PAD_R - 26} y={6} width={24} height={24} rx={3} fill="var(--color-seal)" opacity={0.92} />
        <text x={W - PAD_R - 14} y={15} textAnchor="middle" fontSize={9.5} fill="var(--color-paper)" style={{ fontFamily: "var(--font-display)" }}>书</text>
        <text x={W - PAD_R - 14} y={25} textAnchor="middle" fontSize={9.5} fill="var(--color-paper)" style={{ fontFamily: "var(--font-display)" }}>鉴</text>
      </svg>

      {/* 读图说明：说清纵轴是相对张力、点色是情感、朱砂环是转折,且是模型判读 */}
      <p className="mt-1.5 text-xs text-[var(--color-ink-muted)] leading-relaxed">
        纵轴 = 张力的<b>相对</b>起伏（铺垫低 / 高潮高，看形状不看绝对值）· 点色 = 情感冷暖（
        <span style={{ color: "var(--color-seal)" }}>暖</span> /
        <span style={{ color: "#2E6B82" }}> 冷</span>）· <span style={{ color: "var(--color-seal)" }}>朱砂环</span> = 转折 / 伏笔回收落点。
        张力情感是模型逐章判读,点一章看原文。
      </p>
    </div>
  );
}
