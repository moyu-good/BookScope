// ---------------------------------------------------------------------------
// FateLineArc — 人物命运线（CharacterArc 的品读视图）
//
// 换掉旧的「工笔花鸟枝条」。旧图好看但读不出这个人到底变没变、何时变。命运线只答一件事：
// 这个主角变没变、何时变、往上走还是往下沉。
//
// 形态 = 小多图：每个主要角色一格 mini 折线，一排下来一眼比谁起谁落。
//   · 横轴 = 章节推进；纵轴 = 这个人的处境高低（得势升 / 落难沉）。
//   · 转折点 = 命运方向拐弯的章，用朱砂点钉在线上，旁边标章号——这是锚原文的硬信息。
//   · 每人一个分类色（取 vizTokens.categoricalPalette，跟关系图 / 在场图同一套浅底盘）。
//
// 诚实呈现（接 probe 结论 + memory feedback_viz_algorithm_rigor）：fortune 是模型逐章判读、
// 绝对值会抖，所以纵轴只画相对形状、不标精确刻度；只有转折点（锚原文）才是硬信息。
// evidence-first：点没核验上画空心朱砂圈、标待核，核过的在详情里盖钤印。
//
// 动画：线条自左向右描画（纯 CSS stroke-dasharray draw-in，一次性），默认完全可见、
// 动画只是增强，绝不靠 rAF 当显示开关（headless 会卡、也别永动）。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";

import { smoothLine } from "./vizCurve";
import { vizTokens } from "./viz/vizTokens";

export interface ArcPoint {
  chapter: number;
  presence: number; // 0-10
  fortune: number; // -5..+5
  evidence: string;
  verified: boolean;
  match_score: number;
}

export interface ArcCharacter {
  name: string;
  points: ArcPoint[];
}

interface FateLineArcProps {
  characters: ArcCharacter[];
  charColor: Map<string, string>;
  focusChar: string | null;
  selected: { name: string; chapter: number } | null;
  onSelect: (name: string, chapter: number) => void;
}

// 单格 mini 命运线的画布尺寸（viewBox 内部坐标，外层用 CSS 自适应宽度）
const CELL_W = 260;
const CELL_H = 132;
const PAD_L = 12;
const PAD_R = 12;
const PAD_T = 26; // 顶上留给角色名
const PAD_B = 20; // 底下留给章号刻度
const PLOT_W = CELL_W - PAD_L - PAD_R;
const PLOT_H = CELL_H - PAD_T - PAD_B;

// 看全部时只画命运起伏最值得看的前 N 个（跟选择器 MAIN_COUNT 呼应），免得一屏几十格糊成一片
const MAX_CELLS = 8;

// 找命运转折点：fortune 相对前一章的方向发生明显反转（升转降 / 降转升）且跨度够大。
// 只标锚原文的硬拐点，不把每个小抖动都标上——转折才是这张图的命根子。
function findTurns(points: ArcPoint[]): Set<number> {
  const turns = new Set<number>();
  if (points.length < 3) return turns;
  // 差分方向：+1 升 / -1 降 / 0 平
  const dir = (d: number) => (d > 0.6 ? 1 : d < -0.6 ? -1 : 0);
  let prevDir = 0;
  for (let i = 1; i < points.length; i++) {
    const d = points[i].fortune - points[i - 1].fortune;
    const cur = dir(d);
    if (cur !== 0 && prevDir !== 0 && cur !== prevDir) {
      // 方向反转 → 上一个点是拐点（波峰 / 波谷）
      turns.add(points[i - 1].chapter);
    }
    if (cur !== 0) prevDir = cur;
  }
  return turns;
}

function fortuneWord(f: number): string {
  if (f > 1) return "得势";
  if (f < -1) return "落难";
  return "处境平";
}

// 单格：一个角色的 mini 命运线
function FateCell({
  c,
  color,
  uid,
  globalMin,
  globalSpan,
  selected,
  hover,
  onSelect,
  setHover,
  delayMs,
}: {
  c: ArcCharacter;
  color: string;
  uid: number; // 稳定数字键——给渐变 <defs> id 用，避免人名里的空格 / CJK 进 url(#id) 出岔
  globalMin: number;
  globalSpan: number;
  selected: { name: string; chapter: number } | null;
  hover: { name: string; chapter: number } | null;
  onSelect: (name: string, chapter: number) => void;
  setHover: (h: { name: string; chapter: number } | null) => void;
  delayMs: number;
}) {
  const pts = c.points;
  const xAt = (ch: number) => PAD_L + ((ch - globalMin) / globalSpan) * PLOT_W;
  // 纵轴：fortune -5..+5 映到画布高低。得势在上、落难在下。只画相对形状，不标刻度。
  const yAt = (f: number) => {
    const t = (Math.max(-5, Math.min(5, f)) + 5) / 10; // 0..1
    return PAD_T + (1 - t) * PLOT_H;
  };

  const linePts = pts.map((p) => [xAt(p.chapter), yAt(p.fortune)] as [number, number]);
  const d = smoothLine(linePts);
  const zeroY = yAt(0);
  const turns = useMemo(() => findTurns(pts), [pts]);

  // 描画动画：给足够长的 dash 让整条线"抽"出来。长度取包围盒对角线的粗估，够用。
  const pathLen = Math.max(PLOT_W, 1) * 1.6;

  const first = pts[0];
  const last = pts[pts.length - 1];
  const trend =
    first && last
      ? last.fortune - first.fortune > 1
        ? "整体上行"
        : last.fortune - first.fortune < -1
          ? "整体下沉"
          : "起落归平"
      : "";

  return (
    <div className="rounded-lg border border-[var(--color-rule)] bg-[var(--color-paper-raised)] overflow-hidden">
      <svg
        viewBox={`0 0 ${CELL_W} ${CELL_H}`}
        className="w-full block"
        style={{ background: "var(--color-paper)" }}
      >
        {/* 角色名 + 一句走势 */}
        <text
          x={PAD_L}
          y={16}
          fontSize={vizTokens.fontSize.dataLabel}
          fill="var(--color-ink)"
          style={{ fontFamily: vizTokens.fontFamily.display, fontWeight: 700 }}
        >
          {c.name.length > 6 ? c.name.slice(0, 6) + "…" : c.name}
        </text>
        <text
          x={CELL_W - PAD_R}
          y={16}
          textAnchor="end"
          fontSize={vizTokens.fontSize.footnote}
          fill="var(--color-ink-muted)"
        >
          {trend}
        </text>

        {/* 处境高低的软背景：上半得势、下半落难，极淡，给纵轴一个"上顺下逆"的方向感（不标刻度） */}
        <defs>
          <linearGradient id={`fate-bg-${uid}`} x1="0" y1={PAD_T} x2="0" y2={PAD_T + PLOT_H} gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor={color} stopOpacity={0.1} />
            <stop offset="50%" stopColor={color} stopOpacity={0.02} />
            <stop offset="100%" stopColor="var(--color-ink)" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <rect x={PAD_L} y={PAD_T} width={PLOT_W} height={PLOT_H} fill={`url(#fate-bg-${uid})`} rx={4} />

        {/* 处境平的基准虚线（零位） */}
        <line
          x1={PAD_L}
          y1={zeroY}
          x2={CELL_W - PAD_R}
          y2={zeroY}
          stroke="var(--color-rule)"
          strokeWidth={vizTokens.axis.tickWidth}
          strokeDasharray="2 3"
          opacity={0.6}
        />

        {/* 命运线本体：纯 CSS 描画（dash 从满到零，一次性；默认完全可见靠 forwards 收尾） */}
        {linePts.length >= 2 && (
          <path
            d={d}
            fill="none"
            stroke={color}
            strokeWidth={vizTokens.strokeWidth.base}
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{
              strokeDasharray: pathLen,
              strokeDashoffset: pathLen,
              animation: `fate-draw 900ms ${vizTokens.motion.easing} ${delayMs}ms forwards`,
            }}
          />
        )}
        {/* 单点角色兜底：只有一章时画不出线，落一个点 */}
        {linePts.length === 1 && (
          <circle cx={linePts[0][0]} cy={linePts[0][1]} r={3} fill={color} />
        )}

        {/* 命运点：普通章位实心小点；转折章加大 + 朱砂描；核不过画空心 */}
        {pts.map((p, pi) => {
          const cx = xAt(p.chapter);
          const cy = yAt(p.fortune);
          const isTurn = turns.has(p.chapter);
          const active = selected?.name === c.name && selected.chapter === p.chapter;
          const r = isTurn ? 4.5 : 2.6;
          return (
            <g key={`pt-${c.name}-${pi}`} style={{ animation: `fate-fade 500ms ease-out ${delayMs + 500}ms both` }}>
              <circle
                cx={cx}
                cy={cy}
                r={r}
                fill={
                  active
                    ? "var(--color-seal)"
                    : !p.verified
                      ? "var(--color-paper)"
                      : isTurn
                        ? "var(--color-seal)"
                        : color
                }
                stroke={isTurn || active ? "var(--color-seal)" : color}
                strokeWidth={isTurn ? 1.5 : p.verified ? 0 : 1}
              />
              {/* 转折点标章号 */}
              {isTurn && (
                <text
                  x={cx}
                  y={cy - 8}
                  textAnchor="middle"
                  fontSize={vizTokens.fontSize.footnote}
                  fill="var(--color-seal)"
                  style={{ fontFamily: vizTokens.fontFamily.display, pointerEvents: "none" }}
                >
                  {p.chapter}
                </text>
              )}
            </g>
          );
        })}

        {/* 首尾章号刻度（只标两端，格子小不堆） */}
        {first && (
          <text x={PAD_L} y={CELL_H - 6} textAnchor="start" fontSize={vizTokens.fontSize.footnote} fill="var(--color-ink-muted)">
            {first.chapter}
          </text>
        )}
        {last && last.chapter !== first?.chapter && (
          <text x={CELL_W - PAD_R} y={CELL_H - 6} textAnchor="end" fontSize={vizTokens.fontSize.footnote} fill="var(--color-ink-muted)">
            {last.chapter}
          </text>
        )}

        {/* 点选 / 悬停热区：每个命运点一个透明大圈，好点 */}
        {pts.map((p, pi) => (
          <circle
            key={`hit-${c.name}-${pi}`}
            cx={xAt(p.chapter)}
            cy={yAt(p.fortune)}
            r={9}
            fill="transparent"
            style={{ cursor: "pointer" }}
            onPointerEnter={() => setHover({ name: c.name, chapter: p.chapter })}
            onPointerLeave={() => setHover(null)}
            onClick={() => onSelect(c.name, p.chapter)}
          />
        ))}

        {/* 悬停浮标：第X章 · 谁 · 处境一句 */}
        {hover &&
          hover.name === c.name &&
          (() => {
            const p = pts.find((q) => q.chapter === hover.chapter);
            if (!p) return null;
            const cx = xAt(p.chapter);
            const label = `第${p.chapter}章 · ${fortuneWord(p.fortune)}`;
            // 靠边时把浮标往里收，不出画布
            const tx = Math.min(CELL_W - PAD_R - 2, Math.max(PAD_L + 2, cx));
            const anchor = cx > CELL_W - 60 ? "end" : cx < 60 ? "start" : "middle";
            return (
              <text
                x={tx}
                y={Math.max(PAD_T + 2, yAt(p.fortune) - 12)}
                textAnchor={anchor as "start" | "middle" | "end"}
                fontSize={vizTokens.fontSize.footnote}
                fill="var(--color-ink)"
                style={{ fontFamily: vizTokens.fontFamily.display, pointerEvents: "none", fontWeight: 700 }}
              >
                {label}
              </text>
            );
          })()}
      </svg>
    </div>
  );
}

export function FateLineArc({
  characters,
  charColor,
  focusChar,
  selected,
  onSelect,
}: FateLineArcProps) {
  const [hover, setHover] = useState<{ name: string; chapter: number } | null>(null);

  // 全书章号范围：所有格子共用同一条横轴刻度，这样谁在第几章起落一眼可比（小多图的价值就在这）。
  const { globalMin, globalSpan, shown } = useMemo(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const c of characters) {
      for (const p of c.points) {
        if (p.chapter < min) min = p.chapter;
        if (p.chapter > max) max = p.chapter;
      }
    }
    if (!isFinite(min)) {
      min = 1;
      max = 1;
    }
    const span = Math.max(1, max - min);
    // 聚焦某人只画那一格；看全部按命运起伏幅度取前 N（起落越大越值得看）
    const byRange = [...characters].sort((a, b) => fortuneRange(b) - fortuneRange(a));
    const picked = focusChar
      ? characters.filter((c) => c.name === focusChar)
      : byRange.slice(0, MAX_CELLS);
    return { globalMin: min, globalSpan: span, shown: picked };
  }, [characters, focusChar]);

  return (
    <div>
      {/* 描画 + 淡入的关键帧（纯 CSS，一次性，绝不 rAF） */}
      <style>{`
        @keyframes fate-draw { to { stroke-dashoffset: 0; } }
        @keyframes fate-fade { from { opacity: 0; } to { opacity: 1; } }
      `}</style>

      {/* 小多图网格：聚焦时单列大格，看全部时一排多格。窄屏自动落成单列。 */}
      <div
        className="grid gap-3"
        style={{
          gridTemplateColumns: focusChar
            ? "1fr"
            : "repeat(auto-fill, minmax(220px, 1fr))",
        }}
      >
        {shown.map((c, i) => (
          <FateCell
            key={c.name}
            c={c}
            color={charColor.get(c.name) ?? "var(--color-ink)"}
            uid={i}
            globalMin={globalMin}
            globalSpan={globalSpan}
            selected={selected}
            hover={hover}
            onSelect={onSelect}
            setHover={setHover}
            delayMs={Math.min(i, 8) * 90}
          />
        ))}
      </div>

      {characters.length > shown.length && !focusChar && (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
          画了命运起落最大的 {shown.length} 人 / 全书 {characters.length} 个角色（点上面的角色名只看一条）。
        </p>
      )}
      <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
        朱砂点是命运转折的章（旁标章号）；线只画相对起落、不标精确刻度（模型判读，抖）；点转折看那章原文。
      </p>
    </div>
  );
}

// 一个角色全书 fortune 的极差（max-min）——起落越大越"有故事"，看全部时优先显示
function fortuneRange(c: ArcCharacter): number {
  if (c.points.length === 0) return 0;
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of c.points) {
    if (p.fortune < lo) lo = p.fortune;
    if (p.fortune > hi) hi = p.fortune;
  }
  return hi - lo;
}
