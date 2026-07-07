// ---------------------------------------------------------------------------
// SealButton — 钤印触发按钮（1.8.x 交互 primitive）
//
// 点击时像盖下一枚朱砂印：下压（scale 收一点）+ 手不正的轻微旋转偏移 + 弹回落定
// （seal-press 关键帧在 index.css）。呼应全站「印章 = 证据核验的视觉语言」（见 SealMark），
// 把公文分析的触发动作也做成「盖一章」。
//
// 触发那 1-2 分钟的分析时按住 loading 态：禁用 + 朱砂扫光（复用 run-sweep，不伪造百分比、
// 只表示「在跑」）。CPU 动画（只动 transform / opacity），无 GPU；reduced-motion 由 index.css
// 的全局 @media 兜底（动画时长归零、按钮照常可用），本组件不必单独判。
//
// 用在公文分析的触发按钮（生成办事清单 / 公文结构 …）。纯触发按钮，不留持久印记——
// 留印记那类核验位仍用 SealMark。
// ---------------------------------------------------------------------------

import { useState } from "react";

interface SealButtonProps {
  /** 点击触发（loading / disabled 时不触发） */
  onClick: () => void;
  /** 异步进行中：禁用 + 朱砂扫光 + 显 loadingLabel */
  loading?: boolean;
  /** 别的原因禁用（如没填 API key） */
  disabled?: boolean;
  /** 常态文字 */
  label: string;
  /** loading 时的文字（默认「钤印中…」） */
  loadingLabel?: string;
  /** 尺寸：md（默认）= 入口主按钮；sm = 结果区「重新生成」这类次级动作 */
  size?: "sm" | "md";
  className?: string;
  title?: string;
}

export function SealButton({
  onClick,
  loading = false,
  disabled = false,
  label,
  loadingLabel,
  size = "md",
  className = "",
  title,
}: SealButtonProps) {
  // 点击瞬间打上「正在盖章」类跑一次 seal-press；动画结束（onAnimationEnd）自动卸掉，
  // 下次点还能再触发（同一 class 反复加需靠动画结束清掉重置）。
  const [stamping, setStamping] = useState(false);
  const inactive = loading || disabled;

  return (
    <button
      type="button"
      title={title}
      disabled={inactive}
      onClick={() => {
        if (inactive) return;
        setStamping(true);
        onClick();
      }}
      onAnimationEnd={() => setStamping(false)}
      className={[
        `seal-button relative overflow-hidden rounded border font-medium ${
          size === "sm" ? "text-xs px-3 py-1.5" : "text-sm px-4 py-2"
        }`,
        "transition-colors hover:brightness-105 disabled:opacity-60 disabled:cursor-default",
        stamping ? "seal-button--stamping" : "",
        className,
      ].join(" ")}
      style={{
        borderColor: "var(--color-seal)",
        color: "var(--color-seal)",
        background: "var(--color-seal-soft)",
      }}
    >
      {/* loading 朱砂扫光（复用 run-sweep，只表示在跑、不伪造进度） */}
      {loading && <span className="seal-button__sweep" aria-hidden="true" />}
      <span className="relative z-[1]">
        {loading ? (loadingLabel ?? "钤印中…") : label}
      </span>
    </button>
  );
}
