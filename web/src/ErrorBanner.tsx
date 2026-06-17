import { useEffect, useState } from "react";

// ---------------------------------------------------------------------------
// 类型
// ---------------------------------------------------------------------------

export interface PartialEvidence {
  tool_name: string;
  input_summary: string;
  output_summary: string;
  status: "ok" | "error";
}

export interface ApiError {
  error_type: string;
  message: string;
  details?: Record<string, unknown> | null;
  /**
   * 错误前已查到的原文摘要——第 35 轮第二波加：跑了 1-2 分钟撞 timeout /
   * format_error 时，前几轮 search 命中的结果一并回吐让用户看到产物，
   * 而不是挨空盘。
   */
  partial_evidence?: PartialEvidence[];
}

type ButtonAction =
  | "retry"
  | "rewrite"
  | "newSession"
  | "openSettings"
  | "close";

interface ButtonConfig {
  action: ButtonAction;
  label: string;
  /**
   * 倒计时秒数：仅 RateLimited 的"再试一次"用。
   * 倒计时未结束时按钮 disable，并在 label 后追加剩余秒数。
   */
  countdownSeconds?: number;
  /** primary 按钮走印章红，secondary 走中性边框 */
  variant?: "primary" | "secondary";
}

interface ErrorCopy {
  message: string;
  buttons: ButtonConfig[];
}

export interface ErrorBannerProps {
  error: ApiError;
  onClose: () => void;
  onRetry?: () => void;
  onRewrite?: () => void;
  onNewSession?: () => void;
  onOpenSettings?: () => void;
}

// ---------------------------------------------------------------------------
// 文案表（PM 文档 docs/UX_ERROR_COPYWRITING.md line 17-110）
// ---------------------------------------------------------------------------

const ERROR_COPY_MAP: Record<string, ErrorCopy> = {
  ContentFiltered: {
    message:
      "碰上 AI 内容审查了。换了三种说法重试都没过。把题里敏感的字换个说法再问，或者去设置里挑另一家厂商。",
    buttons: [
      { action: "rewrite", label: "换个说法重问", variant: "primary" },
    ],
  },
  RateLimited: {
    message:
      "AI 那边在排队，三次都没等到。歇一分钟再问。或者去厂商后台看看你这把 key 还剩多少额度。",
    buttons: [
      {
        action: "retry",
        label: "再问一次",
        countdownSeconds: 60,
        variant: "primary",
      },
    ],
  },
  ContextLimitExceeded: {
    message:
      "这次对话太长了，AI 一次塞不进去。点左上「新建对话」重开一次，重要的结论自己复制带过去。",
    buttons: [
      { action: "newSession", label: "新建对话", variant: "primary" },
    ],
  },
  MaxIterationsExceeded: {
    message:
      "翻了 12 轮没想清楚——多半是题问得太大。拆成两三个具体的小题分别问。比如别问「主角怎么变的」，问「主角在第几章发生转变」「转变以后他做了什么」。",
    buttons: [{ action: "retry", label: "再问一次", variant: "primary" }],
  },
  ProviderUnavailable: {
    message:
      "连不上 AI。先去设置看看 key 还在不在、网通不通。两样都好的话就是厂商那边出事了，过几分钟再来。",
    buttons: [
      { action: "openSettings", label: "去设置看 key", variant: "primary" },
      { action: "retry", label: "再试", variant: "secondary" },
    ],
  },
  LoopTimeout: {
    message:
      "这题查得太深，超过 3 分钟还没综合完。下方是已经查到的原文片段——别让等的时间白费。你可以直接看这些片段答自己题，或者点「再问一次」让 AI 再跑一次。",
    buttons: [{ action: "retry", label: "再问一次", variant: "primary" }],
  },
  LLMFormatError: {
    message:
      "AI 给的答案格式不合规（缺原文引用或字段错位）。这是 AI 那头的问题不是你的题，再问一次大概率就好了。下方是已经查到的原文片段。",
    buttons: [{ action: "retry", label: "再问一次", variant: "primary" }],
  },
  ToolDispatchError: {
    message:
      "AI 在查书的时候出岔子了——检索或拉章节的工具连环失败。下方是失败前已经查到的片段。再问一次基本能恢复。",
    buttons: [{ action: "retry", label: "再问一次", variant: "primary" }],
  },
};

const FALLBACK_COPY: ErrorCopy = {
  message:
    "我们这边出了点没料到的问题，跟你的题没关系。再问一次大概率就好；下方是已经查到的原文片段。",
  buttons: [{ action: "retry", label: "再问一次", variant: "primary" }],
};

// ---------------------------------------------------------------------------
// 组件
// ---------------------------------------------------------------------------

export function ErrorBanner({
  error,
  onClose,
  onRetry,
  onRewrite,
  onNewSession,
  onOpenSettings,
}: ErrorBannerProps) {
  const copy = ERROR_COPY_MAP[error.error_type] ?? FALLBACK_COPY;

  // 找到带倒计时的按钮（最多一个，通常是 RateLimited 的 retry）
  const countdownSeconds = copy.buttons.find(
    (b) => typeof b.countdownSeconds === "number",
  )?.countdownSeconds;

  const [secondsLeft, setSecondsLeft] = useState<number>(
    countdownSeconds ?? 0,
  );

  useEffect(() => {
    setSecondsLeft(countdownSeconds ?? 0);
  }, [countdownSeconds, error.error_type]);

  useEffect(() => {
    if (secondsLeft <= 0) return;
    const timer = setInterval(() => {
      setSecondsLeft((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [secondsLeft]);

  function handleButton(btn: ButtonConfig) {
    switch (btn.action) {
      case "retry":
        if (onRetry) onRetry();
        break;
      case "rewrite":
        if (onRewrite) onRewrite();
        break;
      case "newSession":
        if (onNewSession) onNewSession();
        break;
      case "openSettings":
        if (onOpenSettings) onOpenSettings();
        break;
      case "close":
        onClose();
        break;
    }
  }

  function isButtonDisabled(btn: ButtonConfig): boolean {
    if (typeof btn.countdownSeconds === "number" && secondsLeft > 0) {
      return true;
    }
    return false;
  }

  function buttonLabel(btn: ButtonConfig): string {
    if (typeof btn.countdownSeconds === "number" && secondsLeft > 0) {
      return `${btn.label}（${secondsLeft} 秒）`;
    }
    return btn.label;
  }

  function buttonClass(btn: ButtonConfig): string {
    const base =
      "inline-flex items-center gap-2 px-4 py-1.5 rounded text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed";
    if (btn.variant === "secondary") {
      return `${base} border border-[var(--color-rule)] bg-white text-[var(--color-ink)] hover:border-[var(--color-seal)]/50`;
    }
    return `${base} bg-[var(--color-seal)] text-white hover:brightness-110`;
  }

  const partial = error.partial_evidence ?? [];

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="mt-6 border border-[var(--color-seal)]/40 bg-[var(--color-seal)]/5 p-4 rounded"
    >
      <div className="flex items-start gap-3">
        <div className="flex-1">
          <p
            className="text-sm leading-relaxed text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-body)" }}
          >
            {copy.message}
          </p>
          {copy.buttons.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {copy.buttons.map((btn) => (
                <button
                  key={btn.action}
                  type="button"
                  onClick={() => handleButton(btn)}
                  disabled={isButtonDisabled(btn)}
                  className={buttonClass(btn)}
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {buttonLabel(btn)}
                </button>
              ))}
            </div>
          )}
          {partial.length > 0 && (
            <PartialEvidenceList items={partial} />
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭提示"
          className="text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] text-sm"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 子组件：partial_evidence 列表——失败前已查到的原文片段
// ---------------------------------------------------------------------------

function PartialEvidenceList({ items }: { items: PartialEvidence[] }) {
  return (
    <div className="mt-4 border-t border-[var(--color-rule)] pt-3">
      <p
        className="text-xs uppercase tracking-wider text-[var(--color-ink-muted)] mb-2"
        style={{ fontFamily: "var(--font-display)" }}
      >
        失败前已经查到的原文（{items.length} 条）
      </p>
      <ul className="space-y-2">
        {items.map((item, idx) => (
          <li
            key={idx}
            className="text-sm leading-relaxed text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-body)" }}
          >
            <div className="text-[var(--color-ink-muted)] text-xs">
              {item.input_summary}
            </div>
            <div className="mt-0.5 whitespace-pre-wrap break-words text-[var(--color-ink)]/90">
              {item.output_summary}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
