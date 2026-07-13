// ---------------------------------------------------------------------------
// ScholarStanceSpectrum — 学者立场谱（理论书专属镜头，纯展示）
//
// 立场格局是叙事镜头（阵营 + 命运起落），套理论书别扭：被引的学者没有处境、没有二元
// 阵营。这个镜头给理论书量身做：把书里真正在对话的思想家，按**本书自己的核心争论**
// 摆到一条发散轴上——一边一极，谁偏哪头、偏多深，一眼看清。
//
// 依托（exp033 probe 验过、非拍脑袋）：
//   · Stance detection（SemEval-2016 T6）的 favor / against / **none** 三分——none 类
//     专治"只提了名字、没讲立场"，绝不硬给站位。
//   · 引文功能（Teufel）+ Toulmin：每位有立场的学者都配一句**书里刻画他的原句**，
//     核验过盖「鉴」印，没核到标「待核」。没原文不摆上轴。
//
// 只认后端给的 { axis, scholars }，跟具体书无关：
//   · 颜色只编阵营（pole_a 侧墨蓝＝冷，pole_b 侧朱），位置远近编偏得多深，两者不重复。
//   · stance_stated=true 的摆上轴、beeswarm 分道错位防重叠、可点看取证；
//     stance_stated=false 的收进下面"只提到没表态"区，素色 chip，不上轴。
// 纯 CSS 动画（capsule 依次浮现），无 rAF、无 emoji。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { SealMark } from "./SealMark";

export interface SpectrumScholar {
  name: string;
  /** 本书有没有明说 / 刻画他的立场 */
  stance_stated: boolean;
  /** 偏哪极：a=pole_a 侧 / b=pole_b 侧 / 中=居中 / 空=只提名没表态 */
  pole: "a" | "b" | "中" | "";
  /** -5（pole_a 侧）..+5（pole_b 侧），0=居中或只提名 */
  position: number;
  /** 书里刻画他立场的原句（逐字） */
  quote: string;
  /** 这句原文过没过逐字核验 */
  quote_verified: boolean;
  brief: string;
}
export interface SpectrumAxis {
  pole_a: string;
  pole_b: string;
  /** 这条轴的依据，用本书原话概括 */
  from_book: string;
}

interface Props {
  axis: SpectrumAxis;
  scholars: SpectrumScholar[];
}

// 阵营色只编两极 + 居中；偏得多深靠 x 落位表达，不再用颜色深浅重复编码。
const POLE_A_COLOR = "#2E6B82"; // 墨蓝（冷）——pole_a 一侧
const POLE_B_COLOR = "var(--color-seal)"; // 朱——pole_b 一侧
const MID_COLOR = "var(--color-ink-muted)"; // 居中 / 没明显偏向

function campColor(pole: string): string {
  if (pole === "a") return POLE_A_COLOR;
  if (pole === "b") return POLE_B_COLOR;
  return MID_COLOR;
}

// SVG 用固定 viewBox（随宽度缩放，绕开响应式测宽问题，同 StanceQuadrant）。
const VB_W = 720;
const PAD = { t: 10, l: 26, r: 26 };
const PW = VB_W - PAD.l - PAD.r;
const CAP_H = 26; // 胶囊高
const CHAR_W = 15; // 每个字估宽（viewBox 单位）
const CAP_PAD_X = 11;
const ROW_H = 34; // 分道行高
const AXIS_GAP = 12; // 最低一道胶囊底到轴线的距离
const LANE_GAP = 10; // 同道两胶囊间距

const clampPos = (p: number) => Math.max(-5, Math.min(5, Number.isFinite(p) ? p : 0));
const sx = (p: number) => PAD.l + ((clampPos(p) + 5) / 10) * PW;
const capW = (name: string) => Math.max(40, name.length * CHAR_W + CAP_PAD_X * 2);

export function ScholarStanceSpectrum({ axis, scholars }: Props) {
  const [sel, setSel] = useState<string | null>(null);

  const onlyMentioned = useMemo(
    () => scholars.filter((s) => !s.stance_stated),
    [scholars],
  );

  // beeswarm 分道：按落位 x 升序，贪心塞进第一条放得下的道，放不下就新开一道。
  const { placed, laneCount } = useMemo(() => {
    const items = scholars
      .filter((s) => s.stance_stated)
      .map((s) => {
        const w = capW(s.name);
        const dotX = sx(s.position);
        // 胶囊中心夹在画布内（别出血）；轴上的点仍落在真实位置，中间靠细线连。
        const cxDraw = Math.max(PAD.l + w / 2, Math.min(VB_W - PAD.r - w / 2, dotX));
        return { s, w, dotX, cxDraw };
      })
      .sort((a, b) => a.cxDraw - b.cxDraw);

    const laneRight: number[] = [];
    const out = items.map((it) => {
      const left = it.cxDraw - it.w / 2;
      let lane = 0;
      while (lane < laneRight.length && left < laneRight[lane] + LANE_GAP) lane += 1;
      if (lane === laneRight.length) laneRight.push(0);
      laneRight[lane] = it.cxDraw + it.w / 2;
      return { ...it, lane };
    });
    return { placed: out, laneCount: Math.max(1, laneRight.length) };
  }, [scholars]);

  const axisY = PAD.t + (laneCount - 1) * ROW_H + CAP_H + AXIS_GAP;
  const VB_H = axisY + 26; // 轴线下留出"中"刻度标注的地方
  const midX = sx(0);
  const selScholar = sel ? scholars.find((s) => s.name === sel) ?? null : null;

  return (
    <div className="rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-3">
      {/* 两极标签：pole_a 在左（墨蓝）、pole_b 在右（朱），中间点出这是本书自己的争论 */}
      <div className="flex items-start justify-between gap-3">
        <div
          className="text-sm font-bold leading-snug max-w-[42%]"
          style={{ color: POLE_A_COLOR, fontFamily: "var(--font-display)" }}
        >
          {axis.pole_a}
        </div>
        <div className="text-xs text-[var(--color-ink-muted)] self-center shrink-0">
          本书核心争论
        </div>
        <div
          className="text-sm font-bold leading-snug max-w-[42%] text-right text-[var(--color-seal)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {axis.pole_b}
        </div>
      </div>
      {axis.from_book && (
        <p className="mt-1 text-xs text-[var(--color-ink-muted)] leading-relaxed">
          依据本书原文：{axis.from_book}
        </p>
      )}

      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="w-full mt-2" style={{ overflow: "visible" }}>
        <style>{`
          @keyframes scholar-rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
          .scholar-cap{animation:scholar-rise .45s cubic-bezier(.2,.7,.2,1) both;transform-origin:center;transform-box:fill-box}
        `}</style>

        {/* 冷暖两半的极淡底：左半墨蓝、右半朱，只作阵营方位提示，不跟胶囊抢色 */}
        <rect x={PAD.l} y={PAD.t} width={midX - PAD.l} height={axisY - PAD.t} fill={POLE_A_COLOR} opacity={0.05} />
        <rect x={midX} y={PAD.t} width={VB_W - PAD.r - midX} height={axisY - PAD.t} fill="var(--color-seal)" opacity={0.05} />

        {/* 轴线 + 中间"中"刻度 */}
        <line x1={PAD.l} y1={axisY} x2={VB_W - PAD.r} y2={axisY} stroke="var(--color-rule)" strokeWidth={1.5} />
        <line x1={midX} y1={axisY - 5} x2={midX} y2={axisY + 5} stroke="var(--color-ink-muted)" strokeWidth={1.2} />
        <text x={midX} y={axisY + 18} fontSize={11.5} textAnchor="middle" fill="var(--color-ink-muted)">中</text>

        {placed.length === 0 ? (
          <text x={VB_W / 2} y={PAD.t + 20} fontSize={13} textAnchor="middle" fill="var(--color-ink-muted)">
            书里提到了这些学者，但没有明确摆出谁站哪一极。
          </text>
        ) : (
          placed.map(({ s, cxDraw, dotX, w, lane }, i) => {
            const c = campColor(s.pole);
            const top = PAD.t + (laneCount - 1 - lane) * ROW_H;
            const bottom = top + CAP_H;
            const on = sel === s.name;
            return (
              <g
                key={s.name}
                className="scholar-cap"
                style={{ cursor: "pointer", animationDelay: `${Math.min(i, 16) * 40}ms` }}
                onClick={() => setSel(on ? null : s.name)}
              >
                {/* 细线把胶囊连回它在轴上的真实位置（beeswarm 错位后仍读得准） */}
                <line x1={cxDraw} y1={bottom} x2={dotX} y2={axisY} stroke={c} strokeWidth={1} opacity={0.45} />
                <circle cx={dotX} cy={axisY} r={on ? 4 : 3} fill={c} />
                <rect
                  x={cxDraw - w / 2}
                  y={top}
                  width={w}
                  height={CAP_H}
                  rx={CAP_H / 2}
                  fill={on ? c : `color-mix(in oklch, ${c} 13%, var(--color-paper-raised))`}
                  stroke={c}
                  strokeWidth={on ? 1.6 : 1.3}
                />
                <text
                  x={cxDraw}
                  y={top + CAP_H / 2}
                  fontSize={13.5}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fill={on ? "var(--color-paper)" : "var(--color-ink)"}
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {s.name}
                </text>
              </g>
            );
          })
        )}
      </svg>

      {/* 图例：颜色只分阵营 */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-xs text-[var(--color-ink-muted)]">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-full" style={{ background: POLE_A_COLOR }} />
          偏「{axis.pole_a}」
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-full bg-[var(--color-seal)]" />
          偏「{axis.pole_b}」
        </span>
        <span>颜色分阵营，左右远近看偏得多深</span>
      </div>

      {/* 选中学者的详情：偏哪极 + brief + 书里刻画他的原文（每条锚原文） */}
      {selScholar ? (
        <div className="mt-3 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] px-3 py-2.5">
          <div className="flex items-baseline gap-2 flex-wrap mb-1">
            <span className="text-base font-bold text-[var(--color-ink)]" style={{ fontFamily: "var(--font-display)" }}>
              {selScholar.name}
            </span>
            <span className="text-sm" style={{ color: campColor(selScholar.pole) }}>
              {sideSentence(selScholar, axis)}
            </span>
          </div>
          {selScholar.brief && (
            <p className="text-sm text-[var(--color-ink)] leading-relaxed mb-2">{selScholar.brief}</p>
          )}
          {selScholar.quote ? (
            <div className="border-l-2 pl-3 py-1" style={{ borderColor: `color-mix(in oklch, ${campColor(selScholar.pole)} 45%, transparent)` }}>
              <div className="text-xs text-[var(--color-ink-muted)] mb-1 flex items-center gap-1.5">
                <span>书里怎么写他</span>
                {selScholar.quote_verified ? (
                  <SealMark size={17} title="原文已核验" />
                ) : (
                  <span className="text-[10px] px-1 rounded border border-[var(--color-rule)]">待核</span>
                )}
              </div>
              <blockquote className="text-body-sm leading-relaxed text-[var(--color-ink)]" style={{ fontFamily: "var(--font-display)" }}>
                {selScholar.quote}
              </blockquote>
            </div>
          ) : (
            <p className="text-xs text-[var(--color-ink-muted)]">这位没留下可引的原句，不硬给站位。</p>
          )}
        </div>
      ) : placed.length > 0 ? (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)]">点上面某位学者，看书里怎么刻画他的立场。</p>
      ) : null}

      {/* 只提到没表态区：素色 chip，不上轴、不给站位 */}
      {onlyMentioned.length > 0 && (
        <div className="mt-4 pt-3 border-t border-[var(--color-rule)]">
          <div className="text-xs text-[var(--color-ink-muted)] mb-2">
            只提到，没表态
            <span className="ml-1">（书里引了名字，没讲立场，不硬给站位）</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {onlyMentioned.map((s) => (
              <span
                key={s.name}
                className="text-sm px-2.5 py-1 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink-muted)]"
                title={s.brief || undefined}
                style={{ fontFamily: "var(--font-display)" }}
              >
                {s.name}
              </span>
            ))}
          </div>
        </div>
      )}

      <p className="mt-3 text-xs text-[var(--color-ink-muted)] leading-relaxed">
        横轴是这本书自己的核心争论，学者按书里的原文摆到某一极；每位的立场都贴着原文，核验过盖「鉴」印，没核到标「待核」。只提到名字、没讲立场的，放在下面不硬给站位。
      </p>
    </div>
  );
}

// "偏哪极的一句"：据 pole 说人话，居中就老实说没明显偏向。
function sideSentence(s: SpectrumScholar, axis: SpectrumAxis): string {
  if (s.pole === "a") return `偏「${axis.pole_a}」这一极`;
  if (s.pole === "b") return `偏「${axis.pole_b}」这一极`;
  return "居中，书里没把他明显归到哪一极";
}
