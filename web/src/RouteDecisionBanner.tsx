// ---------------------------------------------------------------------------
// RouteDecisionBanner — 路由可视化 + elapsed 计时器 + 超时提示
//
// BE 在 agent 启动前发 RouteDecisionEvent 表明这道题走的是哪条 fast path（或
// agent_loop）。FE 立刻把人话标签 + 预期时长 + 实时计时器顶在进度区第一行，
// 让用户随时知道"我等多久了 / 还要等多久"。
//
// 状态分三档：
//   1) elapsed <= expected_max ——正常文案 "已用 X 秒"
//   2) expected_max < elapsed <= expected_max * 1.5 ——补一句 "（比预期慢）"
//   3) elapsed > expected_max * 1.5 ——把提示换成 "但 agent 还在查"，计时变红
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react";

export type RouteType =
  | "fast_general"
  | "fast_review"
  | "fast_summary"
  | "fast_rating"
  | "agent_loop";

export interface RouteDecisionEvent {
  event_type: "route_decision";
  iteration: 0;
  timestamp: number;
  route_type: RouteType;
  human_label: string;
  expected_duration_seconds_min: number;
  expected_duration_seconds_max: number;
}

/**
 * 路由决策的 FE 状态快照 —— App.tsx 收到 route_decision 事件后塞进 state，
 * 计时基准用 startedAtMs（不一定等于 BE 的 timestamp，FE 自己记一个保险）。
 */
export interface RouteDecisionState {
  routeType: RouteType;
  humanLabel: string;
  expectedMinSec: number;
  expectedMaxSec: number;
  startedAtMs: number;
}

interface RouteDecisionBannerProps {
  /** 路由决策快照；未收到时整个 banner 不渲染 */
  decision: RouteDecisionState;
  /** final_answer 已经到了 —— 停 tick，显示终态用时 */
  done: boolean;
  /** 终态用时（毫秒）—— done 为 true 时优先用这个；缺省走自己的 tick */
  finalDurationMs?: number | null;
}

const ROUTE_EMOJI: Record<RouteType, string> = {
  fast_general: "📖",
  fast_review: "✍️",
  fast_summary: "📝",
  fast_rating: "⭐",
  agent_loop: "🔍",
};

/**
 * elapsed tick —— 1Hz 更新，done 后停。
 * done=true 时直接 short-circuit 不挂 interval，避免后台还在跑。
 */
function useElapsedSeconds(startedAtMs: number, done: boolean): number {
  const [elapsedSec, setElapsedSec] = useState<number>(() =>
    Math.max(0, Math.floor((Date.now() - startedAtMs) / 1000)),
  );

  useEffect(() => {
    if (done) return;
    const tick = (): void => {
      setElapsedSec(Math.max(0, Math.floor((Date.now() - startedAtMs) / 1000)));
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => {
      window.clearInterval(id);
    };
  }, [startedAtMs, done]);

  return elapsedSec;
}

export function RouteDecisionBanner({
  decision,
  done,
  finalDurationMs,
}: RouteDecisionBannerProps) {
  const liveElapsedSec = useElapsedSeconds(decision.startedAtMs, done);

  const elapsedSec =
    done && typeof finalDurationMs === "number"
      ? Math.max(0, Math.round(finalDurationMs / 1000))
      : liveElapsedSec;

  const expectedMax = decision.expectedMaxSec;
  const expectedMin = decision.expectedMinSec;
  const overMax = elapsedSec > expectedMax;
  const overOneAndHalf = elapsedSec > expectedMax * 1.5;

  // 提示文案三档
  let prefix: string;
  if (overOneAndHalf) {
    prefix = `看起来是【${decision.humanLabel}】，预计 ${expectedMin}-${expectedMax} 秒，但 agent 还在查。`;
  } else {
    prefix = `看起来是【${decision.humanLabel}】，预计 ${expectedMin}-${expectedMax} 秒。`;
  }

  // 计时文案
  let elapsedText: string;
  if (done) {
    elapsedText = `用了 ${elapsedSec} 秒`;
  } else if (overOneAndHalf) {
    elapsedText = `已用 ${elapsedSec} 秒`;
  } else if (overMax) {
    elapsedText = `已用 ${elapsedSec} 秒（比预期慢）`;
  } else {
    elapsedText = `已用 ${elapsedSec} 秒`;
  }

  const elapsedRed = overMax && !done;

  return (
    <div
      className="flex flex-wrap items-baseline gap-x-2 gap-y-1 pb-2 mb-2 border-b border-[var(--color-rule)]"
      data-testid="route-decision-banner"
    >
      <span aria-hidden="true" className="text-base">
        {ROUTE_EMOJI[decision.routeType]}
      </span>
      <span
        className="text-sm leading-relaxed text-[var(--color-ink)]"
        style={{ fontFamily: "var(--font-body)" }}
      >
        看起来是
        <span
          className="font-bold mx-0.5"
          style={{ color: "var(--color-seal)" }}
          data-testid="route-label"
        >
          【{decision.humanLabel}】
        </span>
        <span className="text-[var(--color-ink-muted)]">
          ，预计 {expectedMin}-{expectedMax} 秒
          {overOneAndHalf ? "，但 agent 还在查" : ""}。
        </span>
      </span>
      <span
        data-testid="elapsed-text"
        className={`text-sm ${
          elapsedRed
            ? "font-bold"
            : "text-[var(--color-ink-muted)]"
        }`}
        style={elapsedRed ? { color: "var(--color-seal)" } : undefined}
      >
        {elapsedText}
      </span>
      {/* prefix 字段保留作 SR-only 一致性后备 —— 避免 lint 把 prefix 算未使用变量 */}
      <span className="sr-only">{prefix}</span>
    </div>
  );
}
