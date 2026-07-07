// ---------------------------------------------------------------------------
// FeatureEntryCard — 各功能「还没生成」入口态的统一件（视觉表现根治 · #27）
//
// 起因：作者看没填 key 的空态，满屏是各 viz 各写一版的朴素「生成 X」按钮 + 一段说明，
// "太正常了、没设计感、没功能动线引导"。根治成一套入口卡，所有功能空态共用：
//   函套底 + 左朱砂脊（引眼的动线起点）→ 标题（这是什么）→ 一句你会得到什么 →
//   钤印动作按钮（SealButton，焦点）→ 时耗/缓存提示（点下去会发生什么）→ 没 key 时禁用 + 引导。
//   动线自上而下一条线，视线落在那枚朱砂按钮上。
//
// 只管空态（!result）。有结果后各 viz 自己画结果，顶部用 <SealButton size="sm"> 做「重新生成」。
// ---------------------------------------------------------------------------

import type { ReactNode } from "react";
import { SealButton } from "./SealButton";

interface FeatureEntryCardProps {
  /** 功能名（宋体标题） */
  title: string;
  /** 一句「你会得到什么」——说结果 / 价值，不说实现 */
  lead: ReactNode;
  /** 动作按钮常态文字，如「生成叙事曲线」 */
  actionLabel: string;
  /** loading 文字 */
  loadingLabel?: string;
  onAction: () => void;
  loading?: boolean;
  /** 没 key 等原因禁用 */
  disabled?: boolean;
  /** 按钮旁的时耗 / 缓存提示——告诉用户点下去会发生什么（动线的一环） */
  hint?: ReactNode;
  error?: string | null;
  /** loading 时塞进来的进度件（RunningProcess 等） */
  children?: ReactNode;
}

export function FeatureEntryCard({
  title,
  lead,
  actionLabel,
  loadingLabel,
  onAction,
  loading = false,
  disabled = false,
  hint,
  error,
  children,
}: FeatureEntryCardProps) {
  return (
    <div className="pt-4">
      <div
        className="relative overflow-hidden rounded-lg border px-5 py-5"
        style={{
          borderColor: "var(--color-folio-edge)",
          background: "var(--color-paper-raised)",
        }}
      >
        {/* 左朱砂脊：动线起点，把视线一路带到标题 → 按钮 */}
        <span
          className="absolute inset-y-0 left-0 w-[3px]"
          style={{ background: "var(--color-seal)", opacity: 0.85 }}
          aria-hidden
        />
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1.5"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {title}
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed mb-4 max-w-[52ch]">
          {lead}
        </p>
        <div className="flex items-center gap-3 flex-wrap">
          <SealButton
            label={actionLabel}
            loadingLabel={loadingLabel}
            loading={loading}
            disabled={disabled}
            onClick={onAction}
          />
          {hint && !loading && (
            <span className="text-xs text-[var(--color-ink-muted)]">{hint}</span>
          )}
        </div>
        {disabled && !loading && (
          <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
            填了 API key 才能生成（左栏底部「设置」，自带 key、不上传服务器）。
          </p>
        )}
        {error && (
          <p className="mt-3 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {children}
      </div>
    </div>
  );
}
