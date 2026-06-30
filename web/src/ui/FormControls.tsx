// ---------------------------------------------------------------------------
// 善本风表单控件——把全站的下拉 / 勾选框 / 滑块统一成「数字善本案头」的样子，
// 不再露白底原生浏览器控件。配色全走 index.css 的 CSS 变量（纸 / 墨 / rule / 朱砂），
// 不硬编色值，深色主题靠这些 token 自然适配。
//
// 三个控件只管样式，不管行为：value / checked / onChange 等照常透传，
// 跟原生 <select> / <input> 用法一字不差。
// ---------------------------------------------------------------------------

import { forwardRef } from "react";

// 共享的控件外观：纸底、墨字、rule 描边，hover / focus 转朱砂。
// 各控件在此基础上各加各的（下拉留出右侧箭头位、勾选框做成方印）。
const FIELD_BASE =
  "rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] " +
  "outline-none transition-colors hover:border-[var(--color-seal)] " +
  "focus:border-[var(--color-seal)] focus-visible:border-[var(--color-seal)] " +
  "disabled:opacity-50 disabled:cursor-not-allowed";

// ---------------------------------------------------------------------------
// Select——去掉原生箭头（appearance-none），自己画一枚朱砂小箭头。
// 触发器（收起态）做成善本风；展开后的 <option> 列表浏览器不让完全控样，
// 这里不强行做自定义下拉（过度工程），只把看得见的触发器做对。
// ---------------------------------------------------------------------------
export const Select = forwardRef<
  HTMLSelectElement,
  // wrapperClassName 控外层宽度 / 布局（默认贴内容宽）；className 控 <select> 本身（字号 / padding）
  React.SelectHTMLAttributes<HTMLSelectElement> & { wrapperClassName?: string }
>(function Select(
  { className = "", wrapperClassName = "", children, ...rest },
  ref
) {
  return (
    <span className={`relative inline-flex ${wrapperClassName}`}>
      <select
        ref={ref}
        // appearance-none 去掉系统下拉箭头；右侧多留 padding 给自画的朱砂箭头让位
        className={`${FIELD_BASE} appearance-none w-full cursor-pointer pl-3 pr-9 py-2 text-sm ${className}`}
        {...rest}
      >
        {children}
      </select>
      {/* 自画的朱砂小箭头——纯装饰，不拦点击 */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2"
        style={{ color: "var(--color-seal)" }}
      >
        <svg width="11" height="7" viewBox="0 0 11 7" fill="none">
          <path
            d="M1 1l4.5 4.5L10 1"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    </span>
  );
});

// ---------------------------------------------------------------------------
// Checkbox——appearance-none 去掉原生方框，自己做一枚善本方印：
// 未选 = rule 描边的纸底小方；选中 = 朱砂底盖一笔墨白勾。
// 用真正的 <input type="checkbox"> 承载状态（键盘 / 表单语义都在），勾用覆盖的 SVG。
// ---------------------------------------------------------------------------
export const Checkbox = forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(function Checkbox({ className = "", ...rest }, ref) {
  return (
    <span className={`relative inline-flex shrink-0 ${className}`}>
      <input
        ref={ref}
        type="checkbox"
        // appearance-none 去原生外观；自己画方框（纸底 rule 边），选中态翻成朱砂底
        className="peer appearance-none w-4 h-4 rounded-[3px] border border-[var(--color-rule)]
          bg-[var(--color-paper)] cursor-pointer transition-colors
          hover:border-[var(--color-seal)]
          checked:bg-[var(--color-seal)] checked:border-[var(--color-seal)]
          disabled:opacity-50 disabled:cursor-not-allowed"
        {...rest}
      />
      {/* 选中时浮现的墨白勾——只在 checked 时显示，不拦点击 */}
      <svg
        aria-hidden="true"
        viewBox="0 0 16 16"
        className="pointer-events-none absolute left-0 top-0 w-4 h-4 opacity-0 peer-checked:opacity-100 transition-opacity"
      >
        <path
          d="M4 8.2l2.6 2.6L12 5"
          fill="none"
          stroke="var(--color-paper)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
});

// ---------------------------------------------------------------------------
// RangeInput——滑块。轨道 / 滑块拇指的善本配色靠 index.css 的 .seal-range 类
// （webkit / firefox 的轨道伪元素没法用内联 Tailwind 写），这里只挂类 + 透传。
// ---------------------------------------------------------------------------
export const RangeInput = forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(function RangeInput({ className = "", ...rest }, ref) {
  return (
    <input
      ref={ref}
      type="range"
      className={`seal-range ${className}`}
      {...rest}
    />
  );
});
