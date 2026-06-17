// ---------------------------------------------------------------------------
// QuestionBreakdown — 长题拆解可视化
//
// BE 收到长题（≥30 字 + flag on）会先跑一遍 question_processor，把长题拆成
// 1-3 个子问题、推算推荐章节、判断难度，再进 agent loop。
// 这个组件把拆题结果展示给用户看——黑盒变白盒，让用户知道 agent 是怎么
// 理解他这道题的。视觉上紧贴 RouteDecisionBanner 下方，属于 progress 区
// "路由判定 → 拆题 → 迭代"中间一层。
//
// fallback 情况（subquestions 长度 1 且内容等于 original）不渲染——避免
// "拆成 1 个"看着冗余。
// ---------------------------------------------------------------------------

export type Difficulty = "simple" | "medium" | "complex";

export interface QuestionProcessedEvent {
  type: "question_processed";
  iteration: 0;
  original: string;
  subquestions: string[];
  recommended_chapters: number[] | null;
  difficulty: Difficulty;
  duration_seconds: number;
}

/**
 * 拆题状态快照 —— App.tsx 收到 question_processed 事件后塞进 state。
 * 直接复用 event 字段，无需 BE 额外字段。
 */
export interface QuestionProcessedState {
  original: string;
  subquestions: string[];
  recommendedChapters: number[] | null;
  difficulty: Difficulty;
  durationSeconds: number;
}

interface QuestionBreakdownProps {
  breakdown: QuestionProcessedState;
}

const DIFFICULTY_LABEL: Record<Difficulty, string> = {
  simple: "简单",
  medium: "中等",
  complex: "复杂",
};

/**
 * 推荐章节文案：null=全书 / 单章 / 连续段 / 离散列表
 */
function formatChapters(chapters: number[] | null): string {
  if (chapters === null || chapters.length === 0) return "推荐查 全书";
  if (chapters.length === 1) return `推荐查 第 ${chapters[0]} 章`;

  // 判断连续：sorted 且相邻差都是 1
  const sorted = [...chapters].sort((a, b) => a - b);
  let isContinuous = true;
  for (let i = 1; i < sorted.length; i += 1) {
    if (sorted[i] - sorted[i - 1] !== 1) {
      isContinuous = false;
      break;
    }
  }
  if (isContinuous) {
    return `推荐查 第 ${sorted[0]}-${sorted[sorted.length - 1]} 章`;
  }
  return `推荐查 第 ${sorted.join(" / ")} 章`;
}

/**
 * fallback 判断：subquestions 长度 1 且内容等于原题 → 没拆，不渲染子问列表
 */
function isFallback(state: QuestionProcessedState): boolean {
  return (
    state.subquestions.length === 1 &&
    state.subquestions[0].trim() === state.original.trim()
  );
}

export function QuestionBreakdown({ breakdown }: QuestionBreakdownProps) {
  if (isFallback(breakdown)) return null;

  const count = breakdown.subquestions.length;
  const chaptersText = formatChapters(breakdown.recommendedChapters);
  const difficultyText = DIFFICULTY_LABEL[breakdown.difficulty];
  const showDuration = breakdown.durationSeconds >= 3;

  return (
    <div
      className="flex flex-col gap-2 pb-2 mb-2 border-b border-[var(--color-rule)]"
      data-testid="question-breakdown"
    >
      <div className="flex items-baseline gap-x-2">
        <span aria-hidden="true" className="text-base">
          🧩
        </span>
        <span
          className="text-sm leading-relaxed text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-body)" }}
        >
          BookScope 把你的题拆成
          <span
            className="font-bold mx-0.5"
            style={{ color: "var(--color-seal)" }}
            data-testid="breakdown-count"
          >
            {count} 个子问题
          </span>
        </span>
      </div>

      <ol
        className="pl-7 space-y-0.5 text-sm leading-relaxed text-[var(--color-ink)]"
        style={{ fontFamily: "var(--font-body)" }}
        data-testid="breakdown-list"
      >
        {breakdown.subquestions.map((sq, idx) => (
          <li key={idx} className="flex gap-2">
            <span className="text-[var(--color-ink-muted)] tabular-nums">
              {idx + 1}.
            </span>
            <span>{sq}</span>
          </li>
        ))}
      </ol>

      <div className="pl-7 text-xs text-[var(--color-ink-muted)]">
        {chaptersText} · 难度评估：{difficultyText}
        {showDuration && (
          <span> · 分析用了 {Math.round(breakdown.durationSeconds)} 秒</span>
        )}
      </div>
    </div>
  );
}
