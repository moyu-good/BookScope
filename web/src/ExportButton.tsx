// ---------------------------------------------------------------------------
// ExportButton — 「存图」按钮（传播性基座，1.8.x）
//
// 数字善本风格的存图入口：汉风文案「存图」，朱砂细边 + hover 提亮 + 导出中禁用态（朱砂扫光，
// 复用 SealButton 那套 run-sweep，只表示「在跑」不伪造进度）。放在各 viz 页脚——008 说导出入口
// 的肌肉记忆位置在图页脚（Datawrapper / Flourish）。
//
// 本组件只管「按钮 UI + 导出中态 + 出错兜底文案」；真正的导出逻辑在 svgExport.ts 的
// exportSvgToPng / stampSvgForExport，由调用方在 onExport 里拼（先落款 stamp 再导出、finally 复原）。
// 这样按钮跟具体 viz 解耦，任何 viz 都能复用。
//
// 无 npm 依赖、纯 Tailwind + 内联 style（不碰 index.css，避免跟并发改 viz 的 agent 撞共享文件）。
// ---------------------------------------------------------------------------

import { useState } from "react";

interface ExportButtonProps {
  /**
   * 执行导出。约定：调用方在这里先 stampSvgForExport 落款、再 await exportSvgToPng、
   * finally restore()。可以是 async——本组件会在其间显示导出中态、结束自动恢复。
   */
  onExport: () => void | Promise<void>;
  /** 别的原因禁用（如图还没生成、没数据）。 */
  disabled?: boolean;
  /** 常态文字，默认「存图」。 */
  label?: string;
  /** 导出中文字，默认「存图中…」。 */
  busyLabel?: string;
  className?: string;
  title?: string;
}

export function ExportButton({
  onExport,
  disabled = false,
  label = "存图",
  busyLabel = "存图中…",
  className = "",
  title = "把这张图存成 PNG（带标题与来源，可直接分享）",
}: ExportButtonProps) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const inactive = busy || disabled;

  async function handleClick() {
    if (inactive) return;
    setBusy(true);
    setFailed(false);
    try {
      await onExport();
    } catch {
      // 导出出错不炸 UI，只在按钮下给一句兜底文案（不甩锅、不让用户换写法）。
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        title={title}
        disabled={inactive}
        onClick={handleClick}
        className={[
          "seal-button relative overflow-hidden inline-flex items-center gap-1.5",
          "text-xs px-3 py-1.5 rounded border font-medium",
          "transition-colors hover:brightness-105",
          inactive ? "cursor-default opacity-60" : "cursor-pointer",
          className,
        ].join(" ")}
        style={{
          borderColor: "var(--color-seal)",
          color: "var(--color-seal)",
          background: "var(--color-seal-soft)",
        }}
      >
        {/* 导出中的朱砂扫光（复用 index.css 的 run-sweep，只表示在跑、不伪造进度） */}
        {busy && <span className="seal-button__sweep" aria-hidden="true" />}
        <span className="relative z-[1] inline-flex items-center gap-1.5">
          {/* 存图小图标：一枚下载箭头 + 底托，细墨线风，不喧宾夺主 */}
          <svg
            width="13"
            height="13"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M8 2.5v7" />
            <path d="M5 7l3 2.5L11 7" />
            <path d="M3 12.5h10" />
          </svg>
          {busy ? busyLabel : label}
        </span>
      </button>
      {failed && (
        <span className="text-[var(--text-caption)] text-[var(--color-ink-muted)]">
          这张图没存成，稍后再试一次。
        </span>
      )}
    </span>
  );
}
