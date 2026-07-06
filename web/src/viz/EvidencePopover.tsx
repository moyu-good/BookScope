// ---------------------------------------------------------------------------
// EvidencePopover — 共享证据浮层(可视化 Phase 0 地基,§方案概要 ②)
//
// 任何镜头 hover / focus 一个元素(图上一条边、一个节点、一段结论文字),浮出锚定原文。
// 所有镜头都弹这同一个组件,不再各写各的 tooltip。上接 evidence-first 命根子:
// 有原文就显原文 + 第 N 章 + 核验态;没有就老实显"待核",绝不编(008 调研:缺证据显式标)。
//
// 依托:Observable Plot tip mark(hover 出信息)+ ShapeofAI hover 引用(hover 浮原话)。
//
// 两个关键工程点:
//   1. 浮层是绝对定位的 HTML 层,不画进 SVG——SVG 有 overflow 裁剪,画进去会被切掉;
//      HTML 层浮在上面,还能用宋体正常排引文。
//   2. 既 hover 出、也 focus 出——键盘走到触发区(Tab)也能看到证据,无障碍可达。
//
// 触发区(children)包住图元 / 文字;鼠标移入或键盘聚焦 → 浮层出,移开 / 失焦 → 收。
// ---------------------------------------------------------------------------

import { useRef, useState, type ReactNode } from "react";
import { EvidenceBadge, type EvidenceStrength } from "./EvidenceBadge";

interface EvidencePopoverProps {
  /** 锚定的原文引文。没有 = 暂无贴切原文,显"待核"不编。 */
  quote?: string;
  /** 原文所在章(有就显"第 N 章")。 */
  chapter?: number;
  /** 是否逐字核验通过。 */
  verified?: boolean;
  /** 原文匹配度 0-1(可选,有就用来区分强锚 / 弱锚)。 */
  matchScore?: number;
  /** 触发区:包住要 hover / focus 的图元或文字。 */
  children: ReactNode;
  className?: string;
}

// 由 verified + matchScore 定证据强度四态。规则跟全站一致:
// 没原文 → 待核;核验没过 → 部分(有内容但没盖章);核验过看贴合度 → 强锚 / 弱锚。
// matchScore 缺省时把"核验过"当强锚(核验本身已是最硬的信号)。
function deriveStrength(
  quote: string | undefined,
  verified: boolean | undefined,
  matchScore: number | undefined,
): EvidenceStrength {
  if (!quote || !quote.trim()) return "unverified";
  if (!verified) return "partial";
  if (matchScore != null && matchScore < 0.6) return "weak";
  return "strong";
}

export function EvidencePopover({
  quote,
  chapter,
  verified,
  matchScore,
  children,
  className = "",
}: EvidencePopoverProps) {
  const [open, setOpen] = useState(false);
  // hover 与 focus 两条触发线各记一份,任一为真就显——避免"移开鼠标但还聚焦着"时误收。
  const hovering = useRef(false);
  const focusing = useRef(false);

  const sync = () => setOpen(hovering.current || focusing.current);

  const hasQuote = !!quote && !!quote.trim();
  const strength = deriveStrength(quote, verified, matchScore);

  return (
    <span
      className={`relative inline-flex ${className}`}
      onMouseEnter={() => {
        hovering.current = true;
        sync();
      }}
      onMouseLeave={() => {
        hovering.current = false;
        sync();
      }}
      // focusin / focusout 冒泡:触发区内任何可聚焦子元素得/失焦都算(键盘可达)。
      onFocus={() => {
        focusing.current = true;
        sync();
      }}
      onBlur={() => {
        focusing.current = false;
        sync();
      }}
    >
      {children}

      {open && (
        <span
          // 浮在触发区正上方居中的 HTML 层(不进 SVG,不被裁);role=tooltip 供读屏识别。
          role="tooltip"
          className="absolute left-1/2 bottom-full z-50 mb-2 w-max max-w-xs -translate-x-1/2 pointer-events-none"
        >
          <span
            className="block rounded px-3 py-2 text-left"
            style={{
              // 善本风:纸色底 + 朱砂细边 + 柔和投影。
              background: "var(--color-paper-raised)",
              border: "1px solid var(--color-seal)",
              boxShadow: "var(--shadow-soft)",
            }}
          >
            {/* 顶行:章号 + 证据强度徽记,一眼知道这条来自哪、硬不硬。 */}
            <span className="flex items-center gap-2 mb-1">
              {chapter != null && (
                <span
                  className="text-xs"
                  style={{ color: "var(--color-ink-muted)" }}
                >
                  第 {chapter} 章
                </span>
              )}
              <EvidenceBadge strength={strength} />
            </span>

            {/* 正文:有原文当引文显(宋体 / var(--font-display)),没有就老实标待核,绝不编。 */}
            {hasQuote ? (
              <span
                className="block text-sm leading-relaxed"
                style={{
                  fontFamily: "var(--font-display)",
                  color: "var(--color-ink)",
                }}
              >
                “{quote}”
              </span>
            ) : (
              <span
                className="block text-xs italic"
                style={{ color: "var(--color-ink-muted)" }}
              >
                暂无贴切原文（待核）
              </span>
            )}
          </span>
        </span>
      )}
    </span>
  );
}
