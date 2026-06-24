// ---------------------------------------------------------------------------
// ScaleBanner —— 大书提醒条:第一次跑全书结构类分析要把整本读一遍(慢+按量计费),之后缓存住秒出
//
// 书桌(App)和阅读器里的「鉴」(AnalysisOverlay)两个入口都跑全书结构类分析,共用这一条。
// 文案据 bookScale 的档位变,数字(万字 / 章 / 段)都从 TOC 实算,不是糊的。朱砂淡底,克制。
// 核心要传达的:贵只贵第一次(读一遍书的固有成本,实测前缀缓存热了 100% 命中),读完缓存秒出。
// ---------------------------------------------------------------------------

import type { BookScale } from "./bookScale";

export function ScaleBanner({ scale }: { scale: BookScale }) {
  if (scale.tier === "ok") return null;
  const head = `这本书约 ${scale.wan} 万字 · ${scale.chapters} 章`;
  const body =
    scale.tier === "huge"
      ? `非常大。第一次跑全书结构类分析（关系 / 叙事流 / 逐章曲线 / 伏笔 / 支线 / 时间线 / 论点）要把整本读一遍、分约 ${scale.segments} 段，慢且按量计费，个别超长章节可能被截断只抽到一部分。但这是一次性的：读完就缓存住，之后再看这些图都秒出、几乎不再花钱。第一次嫌等，可先用「问这一章」「前情回顾」，或挑最在意的几章单独看。`
      : `体量不小。第一次跑全书结构类分析（关系 / 叙事流 / 逐章曲线 / 伏笔 / 支线 / 时间线 / 论点）要把整本读一遍、分约 ${scale.segments} 段，得等一阵、按量计费。但只贵这一次：读完缓存住，之后再看这些图都秒出、几乎不再花钱。「问这一章」「前情回顾」「实体 / 母题 / 概念」只看局部，不受影响。`;
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
