// ---------------------------------------------------------------------------
// ScaleBanner —— 大书提醒条:全书结构类分析会慢 / 贵 / 可能截断
//
// 书桌(App)和阅读器里的「鉴」(AnalysisOverlay)两个入口都跑全书结构类分析,共用这一条。
// 文案据 bookScale 的档位变,数字(万字 / 章 / 段)都从 TOC 实算,不是糊的。朱砂淡底,克制。
// ---------------------------------------------------------------------------

import type { BookScale } from "./bookScale";

export function ScaleBanner({ scale }: { scale: BookScale }) {
  if (scale.tier === "ok") return null;
  const head = `这本书约 ${scale.wan} 万字 · ${scale.chapters} 章`;
  const body =
    scale.tier === "huge"
      ? `非常大。全书结构类分析（关系 / 叙事流 / 逐章曲线 / 伏笔 / 支线 / 时间线 / 论点）要分约 ${scale.segments} 段逐段读完整本——除了慢、按段计费，个别超长章节会把单次输出撑爆被截断、只抽到其中一部分。建议先用「问这一章」「前情回顾」，或挑你最在意的几章单独看。`
      : `体量不小。全书结构类分析（关系 / 叙事流 / 逐章曲线 / 伏笔 / 支线 / 时间线 / 论点）要分约 ${scale.segments} 段逐段读完整本，头一次跑得等上一阵、按段计费。「问这一章」「前情回顾」「实体 / 母题 / 概念」只看局部，不受影响。`;
  return (
    <div
      className="mb-4 rounded-md px-3.5 py-2.5 text-xs leading-relaxed border"
      style={{
        background: "var(--color-seal-soft)",
        borderColor: "color-mix(in oklch, var(--color-seal) 30%, transparent)",
      }}
    >
      <span className="font-bold text-[var(--color-seal)]">{head}</span>
      <span className="text-[var(--color-ink-muted)]"> —— {body}</span>
    </div>
  );
}
