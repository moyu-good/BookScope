// ---------------------------------------------------------------------------
// SealMark — 钤印核验
//
// 核验过的原文角上盖一枚朱砂「鉴」小印。印章 = 证据核验的视觉语言（"逐字核验过，
// 盖章为证"），不是装饰——这是 BookScope 立身之本（结论钉原文）的界面动作。
// 哪里有"过了原文核验的引文"就盖它：问书答案的引证卡 / 时间线事件 / 一致性对照。
// ---------------------------------------------------------------------------

export function SealMark({
  label = "鉴",
  title,
  className = "",
  size = 26,
}: {
  label?: string;
  title?: string;
  className?: string;
  size?: number;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center justify-center select-none shrink-0 ${className}`}
      style={{
        width: `${size}px`,
        height: `${size}px`,
        color: "var(--color-seal)",
        border: "1.5px solid var(--color-seal)",
        background: "var(--color-seal-soft)",
        borderRadius: "3px",
        fontFamily: "var(--font-display)",
        fontSize: `${size * 0.037}rem`,
        lineHeight: 1,
        transform: "rotate(-7deg)",
      }}
      aria-hidden="true"
    >
      {label}
    </span>
  );
}
