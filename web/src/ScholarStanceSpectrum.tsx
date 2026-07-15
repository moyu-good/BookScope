// ---------------------------------------------------------------------------
// ScholarStanceSpectrum — 学者立场谱（理论书专属镜头，纯展示）
//
// 立场格局是叙事镜头（阵营 + 命运起落），套理论书别扭：被引的学者没有处境、没有二元阵营。
// 这个镜头给理论书量身做：把书里真正在对话的思想家，摆到**十字轴**上看格局——
//   · 纵轴 = 立场（本书核心争论两极：pole_a ↔ pole_b），据 position。
//   · 横轴 = 被本书讨论的分量（边缘提及 ↔ 核心对话），据 mentions（数名/姓出现次数，可数、grounded）。
// 作者反馈:1D 散点谱遇上"学者全挤两极、中间没人"就叠成一团；十字轴多一根横轴把他们摊开就不挤了
// （跟人物「立场格局」同一个 StanceQuadrant 象限，一致）。
//
// 依托（exp033/exp035 probe 验过、非拍脑袋）：Stance detection 的 none 类治"只提名没讲立场"；
// 引文功能 + Toulmin：每位有立场的学者配一句书里刻画他的原句，核过盖「鉴」印、没核标「待核」。
// 学者是单引文（不是人物那种正反 Toulmin），所以象限只画点（showDetail=false），选中后在下面
// 单引文面板看取证；只提名的收进"没表态"区，不上象限。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { SealMark } from "./SealMark";
import { StanceQuadrant, type QuadPoint } from "./StanceQuadrant";

export interface SpectrumScholar {
  name: string;
  /** 本书有没有明说 / 刻画他的立场 */
  stance_stated: boolean;
  /** 偏哪极：a=pole_a 侧 / b=pole_b 侧 / 中=居中 / 空=只提名没表态 */
  pole: "a" | "b" | "中" | "";
  /** -5（pole_a 侧）..+5（pole_b 侧），0=居中或只提名 —— 十字轴纵轴 */
  position: number;
  /** 书里刻画他立场的原句（逐字） */
  quote: string;
  /** 这句原文过没过逐字核验 */
  quote_verified: boolean;
  brief: string;
  /** 被本书提及次数（名/姓取大者）—— 十字轴横轴＝被讨论分量 */
  mentions?: number;
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

const POLE_A_COLOR = "#2E6B82"; // 墨蓝（冷）——pole_a 一侧

export function ScholarStanceSpectrum({ axis, scholars }: Props) {
  const [sel, setSel] = useState<string | null>(null);

  const stated = useMemo(() => scholars.filter((s) => s.stance_stated), [scholars]);
  const onlyMentioned = useMemo(
    () => scholars.filter((s) => !s.stance_stated),
    [scholars],
  );

  // 十字轴象限点：纵轴=立场（position），横轴=被讨论分量（mentions）。学者是单引文、无正反 Toulmin，
  // 故 dispute=0、pro/con 空（象限只画点，取证走下面单引文面板）。size 用 mentions，核心学者点更大。
  const quadPoints = useMemo<QuadPoint[]>(
    () =>
      stated.map((s) => {
        const m = Math.max(1, s.mentions ?? 1);
        return {
          name: s.name,
          x: m,
          y: s.position,
          group: "学者",
          size: m,
          dispute: 0,
          pro: [],
          con: [],
        };
      }),
    [stated],
  );

  const selScholar = sel ? scholars.find((s) => s.name === sel) ?? null : null;

  return (
    <div className="rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-3">
      {/* 本书核心争论 + 依据（象限自带纵轴两极标签，这里给全称 + 出处） */}
      <div className="flex items-start justify-between gap-3">
        <div
          className="text-sm font-bold leading-snug max-w-[42%]"
          style={{ color: POLE_A_COLOR, fontFamily: "var(--font-display)" }}
        >
          {axis.pole_a}
        </div>
        <div className="text-xs text-[var(--color-ink-muted)] self-center shrink-0">本书核心争论</div>
        <div
          className="text-sm font-bold leading-snug max-w-[42%] text-right text-[var(--color-seal)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {axis.pole_b}
        </div>
      </div>
      {axis.from_book && (
        <p className="mt-1 mb-2 text-xs text-[var(--color-ink-muted)] leading-relaxed">
          依据本书原文：{axis.from_book}
        </p>
      )}

      {quadPoints.length === 0 ? (
        <p className="text-sm text-[var(--color-ink-muted)] py-6 text-center">
          书里提到了这些学者，但没有明确摆出谁站哪一极。
        </p>
      ) : (
        <StanceQuadrant
          points={quadPoints}
          axisX={{ label: "被讨论分量", low: "边缘提及", high: "核心对话" }}
          axisY={{ label: "立场", low: axis.pole_a, high: axis.pole_b }}
          groupColor={{ 学者: "var(--color-seal)" }}
          selected={sel}
          onSelect={setSel}
          showDetail={false}
        />
      )}

      {/* 选中学者：单引文详情（偏哪极 + brief + 书里刻画他的原句 + 鉴印） */}
      {selScholar && selScholar.stance_stated ? (
        <div className="mt-3 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] px-3 py-2.5">
          <div className="flex items-baseline gap-2 flex-wrap mb-1">
            <span
              className="text-base font-bold text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {selScholar.name}
            </span>
            <span
              className="text-sm"
              style={{
                color:
                  selScholar.pole === "a"
                    ? POLE_A_COLOR
                    : selScholar.pole === "b"
                      ? "var(--color-seal)"
                      : "var(--color-ink-muted)",
              }}
            >
              {selScholar.pole === "a"
                ? `偏「${axis.pole_a}」`
                : selScholar.pole === "b"
                  ? `偏「${axis.pole_b}」`
                  : "居中"}
            </span>
          </div>
          {selScholar.brief && (
            <p className="text-sm text-[var(--color-ink)] leading-relaxed mb-2">{selScholar.brief}</p>
          )}
          {selScholar.quote ? (
            <div
              className="border-l-2 pl-3 py-1"
              style={{ borderColor: "color-mix(in oklch, var(--color-seal) 40%, transparent)" }}
            >
              <div className="text-xs text-[var(--color-ink-muted)] mb-1 flex items-center gap-1.5">
                <span>书里怎么写他</span>
                {selScholar.quote_verified ? (
                  <SealMark size={17} title="原文已核验" />
                ) : (
                  <span className="text-[10px] px-1 rounded border border-[var(--color-rule)]">待核</span>
                )}
              </div>
              <blockquote
                className="text-body-sm leading-relaxed text-[var(--color-ink)]"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {selScholar.quote}
              </blockquote>
            </div>
          ) : (
            <p className="text-xs text-[var(--color-ink-muted)]">这位没留下可引的原句，不硬给站位。</p>
          )}
        </div>
      ) : quadPoints.length > 0 ? (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)]">点象限里某位学者，看书里怎么刻画他的立场。</p>
      ) : null}

      {/* 只提到没表态区：素色 chip，不上象限、不给站位 */}
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
        十字轴：纵看立场偏哪一极、横看被本书讨论的分量（核心 ↔ 边缘），点越大＝被谈得越多。每位的立场都
        贴着原文，核过盖「鉴」印。只提到名字、没讲立场的放在下面，不硬给站位。
      </p>
    </div>
  );
}
