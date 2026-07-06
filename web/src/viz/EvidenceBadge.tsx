// ---------------------------------------------------------------------------
// EvidenceBadge — 证据强度四态统一标记(可视化 Phase 0 地基,§方案概要 ④)
//
// 把"这条结论的原文靠不靠得住"画成一个一眼可分的小印记,所有镜头 + 文本输出共用一套,
// 不再各写各的。上接 evidence-first 命根子:别让强锚和待核看起来一样硬——把可信度画出来
// (memory feedback_viz_algorithm_rigor),缺证据显式标别藏(008 调研 ShapeofAI)。
//
// 四态视觉(靠"填充程度"递减,一眼看出证据由实到虚):
//   strong     强锚 —— 实心朱砂钤印感(填满),逐字核验过、原文贴切
//   weak       弱锚 —— 朱砂描边不填,有原文但贴合度弱
//   partial    部分 —— 半填 + 虚线边,只覆盖了一部分(呼应后端 partial_evidence 兜底)
//   unverified 待核 —— 灰 italic,没核 / 暂无贴切原文,老实标出来
//
// 小号 inline badge,能贴在图元 / 列表项 / 结论文字旁。颜色全走 CSS 变量,随主题走。
// ---------------------------------------------------------------------------

export type EvidenceStrength = "strong" | "weak" | "partial" | "unverified";

interface EvidenceBadgeProps {
  strength: EvidenceStrength;
  /** 覆盖默认汉字标签(默认:强锚 / 弱锚 / 部分 / 待核) */
  label?: string;
  className?: string;
}

// 每态默认的短汉字标签(说人话、不用洋词)。
const DEFAULT_LABEL: Record<EvidenceStrength, string> = {
  strong: "强锚",
  weak: "弱锚",
  partial: "部分",
  unverified: "待核",
};

// 每态的视觉:填充由实到虚。三个有证据的态用朱砂(--color-seal),待核退成灰(--color-ink-muted)。
// 用内联 style 走 CSS 变量,比 Tailwind 任意 color-mix 稳、也随主题切换。
function styleFor(strength: EvidenceStrength): React.CSSProperties {
  switch (strength) {
    // 强锚:实心朱砂,像盖满的钤印——最硬的证据。
    case "strong":
      return {
        color: "var(--color-paper)",
        background: "var(--color-seal)",
        border: "1px solid var(--color-seal)",
      };
    // 弱锚:朱砂描边、不填——有原文但贴合弱,骨架在、分量轻。
    case "weak":
      return {
        color: "var(--color-seal)",
        background: "transparent",
        border: "1px solid var(--color-seal)",
      };
    // 部分:半填(朱砂淡底)+ 虚线边——只覆盖了一部分,边界虚着提示"没盖全"。
    case "partial":
      return {
        color: "var(--color-seal)",
        background: "var(--color-seal-soft)",
        border: "1px dashed var(--color-seal)",
      };
    // 待核:灰 italic,不用朱砂——没核就不摆出证据的样子。
    case "unverified":
      return {
        color: "var(--color-ink-muted)",
        background: "transparent",
        border: "1px dashed var(--color-rule)",
        fontStyle: "italic",
      };
  }
}

export function EvidenceBadge({ strength, label, className = "" }: EvidenceBadgeProps) {
  const text = label ?? DEFAULT_LABEL[strength];
  return (
    <span
      className={`inline-flex items-center justify-center select-none shrink-0 align-middle ${className}`}
      style={{
        fontFamily: "var(--font-display)",
        fontSize: "0.6875rem", // 11px,贴文字/图元不喧宾夺主
        lineHeight: 1,
        letterSpacing: "0.05em",
        padding: "0.15em 0.4em",
        borderRadius: "3px",
        ...styleFor(strength),
      }}
      // 无障碍:徽记本身带完整语义(哪一态),读屏不必再去猜颜色。
      role="img"
      aria-label={`证据强度:${text}`}
      title={text}
    >
      {text}
    </span>
  );
}
