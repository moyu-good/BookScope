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
  // 聚焦单人时点「← 看全部」退回小多图（由 CharacterArc 清 focusChar / selected）
  onClearFocus?: () => void;
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

// 把一条命运线切成"实线段 / 虚线段"。
// 角色只在部分章活跃是正常的：后端只给出场章的点，presence=0 的点是模型明说的"这章隐没/一笔带过"。
// 规则：相邻两点里只要有一头 presence=0，这一段就当"离场期"画虚线跨过去；两头都在场（presence>0）画实线。
// 这样残缺跨度读起来是"离场又回来"，不是线莫名断了。返回一串 { d, dashed }，每段各画一条 path。
//
// 只认 presence=0 这个模型明说的离场信号，不拿"两点章号跳得大"猜离场——点本就是稀疏采样的
// （模型宁可少而准、每人最多约 40 点），章号密度又各书不同，按章距硬猜会把正常稀疏当成离场
// （凭空造一个原文没有的"离场"，破 evidence-first）。登场/退场两端已标清"活跃于第 X–Y 章"。
function splitFateSegments(
  linePts: [number, number][],
  pts: ArcPoint[],
): { d: string; dashed: boolean }[] {
  if (linePts.length < 2) return [];
  const segs: { d: string; dashed: boolean }[] = [];
  for (let i = 0; i < linePts.length - 1; i++) {
    const dashed = pts[i].presence === 0 || pts[i + 1].presence === 0;
    // 单段就两点，直接连直线（smoothLine 两点即直线），dash 样式再叠上去
    segs.push({ d: smoothLine([linePts[i], linePts[i + 1]]), dashed });
  }
  return segs;
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
  const zeroY = yAt(0);
  // hooks 一律在任何 return 之前无条件调用（SubplotWeave 踩过 hooks-after-return 白屏）
  const turns = useMemo(() => findTurns(pts), [pts]);
  // 命运线切段：在场段实线、离场期虚线（分段各画一条 path，见 splitFateSegments）。
  // 依赖钉在稳定输入（pts + 横轴范围）上，不钉每次新建的 linePts 数组，免得白 memo。
  const segments = useMemo(
    () => splitFateSegments(pts.map((p) => [xAt(p.chapter), yAt(p.fortune)] as [number, number]), pts),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pts, globalMin, globalSpan],
  );

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

        {/* 命运线本体：分段画。
            · 在场段（两头都在）= 实线，纯 CSS 描画（dash 从满到零，一次性，forwards 收尾默认全可见）。
            · 离场期段（有一头 presence=0）= 淡虚线跨过去，读成"这人这段离场了"，不是线断了。 */}
        {segments.map((seg, si) =>
          seg.dashed ? (
            <path
              key={`seg-${c.name}-${si}`}
              d={seg.d}
              fill="none"
              stroke={color}
              strokeWidth={vizTokens.strokeWidth.hairline}
              strokeLinecap="round"
              strokeDasharray="3 4"
              opacity={0.4}
            />
          ) : (
            <path
              key={`seg-${c.name}-${si}`}
              d={seg.d}
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
          ),
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

        {/* 登场 / 退场端点：角色只活跃在第 first–last 章，两端画清楚是"入场 / 退场"，
            读成"这人活跃于第 X–Y 章"，不是线断了。空心小环 + 入/退小字（只在多于一点时分标）。 */}
        {first && (
          <g style={{ animation: `fate-fade 500ms ease-out ${delayMs + 600}ms both` }}>
            <circle
              cx={xAt(first.chapter)}
              cy={yAt(first.fortune)}
              r={3.6}
              fill="var(--color-paper)"
              stroke={color}
              strokeWidth={1.4}
            />
            <text
              x={xAt(first.chapter)}
              y={yAt(first.fortune) + 13}
              textAnchor="middle"
              fontSize={vizTokens.fontSize.footnote}
              fill="var(--color-ink-muted)"
              style={{ fontFamily: vizTokens.fontFamily.display, pointerEvents: "none" }}
            >
              入
            </text>
          </g>
        )}
        {last && last.chapter !== first?.chapter && (
          <g style={{ animation: `fate-fade 500ms ease-out ${delayMs + 600}ms both` }}>
            <circle
              cx={xAt(last.chapter)}
              cy={yAt(last.fortune)}
              r={3.6}
              fill="var(--color-paper)"
              stroke={color}
              strokeWidth={1.4}
            />
            <text
              x={xAt(last.chapter)}
              y={yAt(last.fortune) + 13}
              textAnchor="middle"
              fontSize={vizTokens.fontSize.footnote}
              fill="var(--color-ink-muted)"
              style={{ fontFamily: vizTokens.fontFamily.display, pointerEvents: "none" }}
            >
              退
            </text>
          </g>
        )}

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
  onClearFocus,
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

      {/* 聚焦单人时给一个明显的「← 看全部」，退回小多图 */}
      {focusChar && onClearFocus && (
        <button
          type="button"
          onClick={onClearFocus}
          className="mb-2 inline-flex items-center gap-1 text-sm text-[var(--color-seal)] hover:opacity-80 transition-opacity"
          style={{ fontFamily: "var(--font-display)" }}
        >
          <span aria-hidden>←</span> 看全部
        </button>
      )}

      {focusChar ? (
        // 聚焦单人：一格居中、适中尺寸（≈640×324，跟 viewBox 260:132 同比），不撑满一屏。
        // 从小多图切过来只是这一格放大到适中，不突然铺满，过渡舒服。
        <div className="mx-auto w-full" style={{ maxWidth: 640 }}>
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
              delayMs={0}
            />
          ))}
        </div>
      ) : (
        // 看全部：一排多格小多图，窄屏自动落单列。
        <div
          className="grid gap-3"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}
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
      )}

      {characters.length > shown.length && !focusChar && (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
          画了命运起落最大的 {shown.length} 人 / 全书 {characters.length} 个角色（点上面的角色名只看一条）。
        </p>
      )}
      <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
        朱砂点是命运转折的章（旁标章号）；两端「入 / 退」是这人登场 / 退场的章（活跃于这一段）；虚线是离场期跨过去；线只画相对起落、不标精确刻度（模型判读，抖）；点任一点看那章原文。
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
