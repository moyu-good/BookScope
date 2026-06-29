// ---------------------------------------------------------------------------
// Onboarding 一次性引导卡片 · 三类触发点
//
//   first_visit  · 用户第一次进页面 → 在 LLM 配置区下方
//   first_upload · 第一次上传完成   → 在问答区上方
//   first_switch · 第一次切书       → 在书柜下方
//
// localStorage key: bookscope_onboarding_seen_v1
// 结构: { first_visit?: boolean, first_upload?: boolean, first_switch?: boolean }
//
// 容错原则同 historyStorage.ts：SSR / 隐私模式 / JSON 损坏一律默默忽略。
// 失败时倾向"已看过"——避免反复弹同一张卡骚扰用户。
// ---------------------------------------------------------------------------
import { useEffect, useState } from "react";

const STORAGE_KEY = "bookscope_onboarding_seen_v1";

export type OnboardingType = "first_visit" | "first_upload" | "first_switch";

interface SeenMap {
  first_visit?: boolean;
  first_upload?: boolean;
  first_switch?: boolean;
}

function readSeen(): SeenMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    return parsed as SeenMap;
  } catch {
    return {};
  }
}

function writeSeen(type: OnboardingType): void {
  if (typeof window === "undefined") return;
  try {
    const current = readSeen();
    const next: SeenMap = { ...current, [type]: true };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // 隐私模式 / 配额满 —— 失败不阻断主流程
  }
}

interface OnboardingProps {
  type: OnboardingType;
  /** 上方 App.tsx 控制是否到了该 type 的触发时机 */
  triggered: boolean;
  /** 替换文案里 {bookTitle} 占位，仅 first_switch 用到 */
  bookTitle?: string;
}

const COPY: Record<OnboardingType, string> = {
  first_visit:
    "BookScope 是给写过、在写长文本的人用的，上传你的书或文章，AI 给你带原文出处的判断（不只是摘要）。",
  first_upload:
    "上传完了，可以点上方“快问 / 深问”里的题试一道，或者输入自己的问题。",
  first_switch:
    "切到《{bookTitle}》了，之前的问答记录在右侧 HistoryPanel 还能翻回来。",
};

export function Onboarding({ type, triggered, bookTitle }: OnboardingProps) {
  const [seen, setSeen] = useState<boolean>(true);

  // 进组件时读一次 seen；triggered 变 true 才决定要不要显示
  useEffect(() => {
    setSeen(readSeen()[type] === true);
  }, [type]);

  if (!triggered || seen) return null;

  const text = COPY[type].replace("{bookTitle}", bookTitle ?? "");

  function handleDismiss() {
    writeSeen(type);
    setSeen(true);
  }

  return (
    <div
      className="my-4 rounded border-l-2 border-[var(--color-seal)] bg-[var(--color-surface)] px-4 py-3 flex items-start gap-3"
      role="note"
    >
      <p className="text-sm text-[var(--color-ink)] flex-1 leading-relaxed">
        {text}
      </p>
      <button
        type="button"
        onClick={handleDismiss}
        className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] px-2 py-1 rounded shrink-0 transition-colors"
      >
        知道了
      </button>
    </div>
  );
}
