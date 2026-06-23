// ---------------------------------------------------------------------------
// HuaniaoArc — 人物弧线的工笔花鸟（CharacterArc 的品读视图）
//
// 每个主要角色一枝：枝条上扬下垂 = 处境起落（fortune，得势升/落难沉），着花疏密 = 戏份
// （presence，戏重处花繁、戏淡处零落）。梅花着枝、纸底设色，跟山水长卷同一套数字善本调性。
// 点一朵花看那章原文。evidence-first：核不过的点画成空心花苞、不当确定结论。
//
// 诚实呈现（接 probe 结论 + memory feedback_viz_algorithm_rigor）：presence/fortune 是模型
// 逐章判读、绝对值会抖，所以只画相对形状（枝的起伏 + 花的疏密），不印"presence 8/10"那种假精确。
// 动画：枝条自左向右生发——纯 CSS clip-path 扫场，默认完全可见、动画只是增强，绝不靠 rAF。
// ---------------------------------------------------------------------------

import { useMemo, useRef, useState } from "react";

import { smoothLine } from "./vizCurve";

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

interface HuaniaoArcProps {
  characters: ArcCharacter[];
  charColor: Map<string, string>;
  focusChar: string | null;
  selected: { name: string; chapter: number } | null;
  onSelect: (name: string, chapter: number) => void;
}

const W = 760;
const PAD_L = 66; // 左边给枝名留位
const PAD_R = 20;
const BAND_H = 70; // 单枝纵向占高
const TOP = 16;
const MAX_BRANCHES = 6; // 看全部时只画戏份最重的几枝，免得糊

// 一朵梅花：中心 + 五瓣（绕中心 72° 一瓣）。核不过画空心花苞。
function Bloom(props: {
  x: number;
  y: number;
  r: number;
  color: string;
  verified: boolean;
  active: boolean;
}) {
  const { x, y, r, color, verified, active } = props;
  const petalR = r * 0.62;
  const off = r * 0.92;
  const petals = [0, 1, 2, 3, 4].map((k) => {
    const a = (k * 72 - 90) * (Math.PI / 180);
    return [x + Math.cos(a) * off, y + Math.sin(a) * off] as [number, number];
  });
  return (
    <g>
      {petals.map(([px, py], k) => (
        <circle
          key={k}
          cx={px}
          cy={py}
          r={petalR}
          fill={verified ? color : "none"}
          stroke={color}
          strokeWidth={verified ? 0 : 1}
          opacity={verified ? 0.85 : 0.45}
        />
      ))}
      <circle cx={x} cy={y} r={r * 0.5} fill={active ? "var(--color-seal)" : verified ? color : "var(--color-paper)"} stroke={color} strokeWidth={verified ? 0 : 1} />
    </g>
  );
}

export function HuaniaoArc({
  characters,
  charColor,
  focusChar,
  selected,
  onSelect,
}: HuaniaoArcProps) {
  const [hover, setHover] = useState<{ name: string; chapter: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  const layout = useMemo(() => {
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
    const inner = W - PAD_L - PAD_R;
    const xAt = (ch: number) => PAD_L + ((ch - min) / span) * inner;
    // 看全部时取戏份最重的前 N 枝；聚焦时只这一枝
    const byPresence = [...characters].sort(
      (a, b) =>
        b.points.reduce((s, p) => s + p.presence, 0) -
        a.points.reduce((s, p) => s + p.presence, 0),
    );
    const shown = focusChar
      ? characters.filter((c) => c.name === focusChar)
      : byPresence.slice(0, MAX_BRANCHES);
    return { min, max, inner, xAt, shown, total: characters.length };
  }, [characters, focusChar]);

  const { min, max, xAt, shown, total } = layout;
  const H = TOP + shown.length * BAND_H + 22;

  return (
    <div ref={wrapRef}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full border border-[var(--color-rule)] rounded"
        style={{ background: "var(--color-paper)" }}
      >
        <style>{`@keyframes hn-sweep{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}`}</style>

        <g style={{ animation: "hn-sweep .9s ease-out" }}>
          {shown.map((c, row) => {
            const color = charColor.get(c.name) ?? "var(--color-ink)";
            const laneY = TOP + row * BAND_H + BAND_H / 2;
            const dim = focusChar != null && focusChar !== c.name;
            const pts = c.points.map(
              (p) => [xAt(p.chapter), laneY - (p.fortune / 5) * (BAND_H * 0.32)] as [number, number],
            );
            return (
              <g key={`br-${c.name}`} opacity={dim ? 0.2 : 1}>
                {/* 枝名 */}
                <text
                  x={PAD_L - 8}
                  y={laneY + 3}
                  textAnchor="end"
                  fontSize={11}
                  fill="var(--color-ink)"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {c.name.length > 4 ? c.name.slice(0, 4) + "…" : c.name}
                </text>
                {/* 淡淡的零位虚线（处境平的基准） */}
                <line x1={PAD_L} y1={laneY} x2={W - PAD_R} y2={laneY} stroke="var(--color-rule)" strokeWidth={0.5} strokeDasharray="2 3" opacity={0.4} />
                {/* 枝条 */}
                {pts.length >= 2 && (
                  <path
                    d={smoothLine(pts)}
                    fill="none"
                    stroke={color}
                    strokeWidth={1.6}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    opacity={0.7}
                  />
                )}
                {/* 着花：戏份越重花越大 */}
                {c.points.map((p, pi) => {
                  const r = 2.4 + (Math.max(0, Math.min(10, p.presence)) / 10) * 5;
                  const active = selected?.name === c.name && selected.chapter === p.chapter;
                  return (
                    <Bloom
                      key={`bl-${c.name}-${pi}`}
                      x={xAt(p.chapter)}
                      y={laneY - (p.fortune / 5) * (BAND_H * 0.32)}
                      r={r}
                      color={color}
                      verified={p.verified}
                      active={active}
                    />
                  );
                })}
              </g>
            );
          })}
        </g>

        {/* 章号刻度 */}
        {Array.from({ length: max - min + 1 }, (_, k) => {
          const ch = min + k;
          const cnt = max - min + 1;
          if (!(cnt <= 20 || k % 5 === 0)) return null;
          return (
            <text key={`x-${ch}`} x={xAt(ch)} y={H - 6} textAnchor="middle" fontSize={9} fill="var(--color-ink-muted)">
              {ch}
            </text>
          );
        })}

        {/* 点选 / 悬停热区：每枝每花一个透明大圈,好点 */}
        {shown.map((c) => {
          const laneY = TOP + shown.indexOf(c) * BAND_H + BAND_H / 2;
          return c.points.map((p, pi) => (
            <circle
              key={`hit-${c.name}-${pi}`}
              cx={xAt(p.chapter)}
              cy={laneY - (p.fortune / 5) * (BAND_H * 0.32)}
              r={10}
              fill="transparent"
              style={{ cursor: "pointer" }}
              onPointerEnter={() => setHover({ name: c.name, chapter: p.chapter })}
              onPointerLeave={() => setHover(null)}
              onClick={() => onSelect(c.name, p.chapter)}
            />
          ));
        })}

        {/* 悬停浮签：第X章·相对档（不印精确分） */}
        {hover &&
          (() => {
            const c = characters.find((x) => x.name === hover.name);
            const p = c?.points.find((q) => q.chapter === hover.chapter);
            if (!c || !p) return null;
            const row = shown.indexOf(c);
            if (row < 0) return null;
            const laneY = TOP + row * BAND_H + BAND_H / 2;
            const fy = laneY - (p.fortune / 5) * (BAND_H * 0.32);
            const band = p.presence >= 7 ? "戏重" : p.presence >= 3 ? "有戏" : "少戏";
            const fortune = p.fortune > 1 ? "得势" : p.fortune < -1 ? "落难" : "平";
            return (
              <text
                x={Math.min(W - PAD_R - 4, Math.max(PAD_L + 4, xAt(hover.chapter)))}
                y={Math.max(TOP + 8, fy - 9)}
                textAnchor="middle"
                fontSize={10}
                fill="var(--color-ink)"
                style={{ fontFamily: "var(--font-display)", pointerEvents: "none" }}
              >
                第{p.chapter}章 · {band} · {fortune}
              </text>
            );
          })()}
      </svg>
      {total > shown.length && !focusChar && (
        <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
          画了戏份最重的 {shown.length} 枝 / 全书 {total} 个角色（点上面的角色名只看一枝）。
        </p>
      )}
    </div>
  );
}
