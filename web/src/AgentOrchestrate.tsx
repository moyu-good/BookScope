// ---------------------------------------------------------------------------
// AgentOrchestrate — agent 编排（说目标 → 编排已有分析 → 综合）
//
// 「问书」里的第二条路：用户不问具体问题，而是给一个目标（「这本书伏笔铺得怎么样」），
// 调 /api/agent/orchestrate（SSE）。编排器先规划挑哪几个功能、逐个跑、最后综合成带原文
// 证据的回答。这里照「问书」的 SSE 消费写法逐帧渲染：
//   plan      → 显示计划（打算跑 X / Y / Z，每个一句 why）
//   step      → 每个功能跑完逐条显示（功能名 + 一句话结果 + 「点开看完整 X 视图」）
//   synthesis → 综合文 + 行内引用（核验过的盖朱砂「鉴」印，沿用问书答案的引用渲染）
//   done      → 收尾（trace 用量小字）
//   error     → 友好提示（沿用现有错误兜底文案风格）
//
// 不碰普通问答路径（普通提问照样走 /api/agent/ask/stream）；evidence-first：综合引用照样
// 可核验、盖印；drill-into 把功能名 + 参数交给父组件跳进 App 里那个功能的完整视图。
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react";
import { RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// 编排综合的引用——与问书答案的 Citation 同形态（chapter + snippet + verified）。
interface OrchestrateCitation {
  chapter: number;
  snippet: string;
  verified?: boolean;
}

// 一条 drill 信息：跳进哪个功能、带什么参数（功能名为后端编排菜单的键）。
export interface DrillInfo {
  feature: string;
  params: Record<string, string>;
}

interface PlanEntry {
  feature: string;
  why: string;
  params: Record<string, string>;
}

interface StepEntry {
  feature: string;
  summary: string;
  found: number;
  drill: DrillInfo;
}

// orchestrate 的 SSE 事件（与 bookscope/agent/orchestrate.py emit 的 dict 对齐）。
type OrchestrateEvent =
  | { type: "plan"; plan: PlanEntry[] }
  | {
      type: "step";
      feature: string;
      summary: string;
      found: number;
      drill: DrillInfo;
    }
  | { type: "synthesis"; text: string; citations: OrchestrateCitation[] }
  | { type: "done"; trace?: RunTrace }
  | { type: "error"; message: string };

// 编排菜单功能名 → 中文标签（给计划 / step 显示人话名，不露后端键名）。
// 与 App.tsx 的 NAV_MODES 标签对齐。
const FEATURE_LABEL: Record<string, string> = {
  character_graph: "关系图",
  character_flow: "叙事流",
  timeline: "时间线",
  consistency: "设定一致性",
  entity_recall: "实体回溯",
  concept_evolution: "概念演进",
  motif: "母题追踪",
  argument_structure: "论点结构",
  writing_technique: "写作手法",
  study_cards: "知识卡片",
  style_issues: "文体体检",
  narrative_curve: "叙事曲线",
  relationship_timeline: "关系演变",
  character_arc: "人物弧线",
  character_voice: "声口一致",
  subplot_weave: "支线编织",
  foreshadow: "伏笔回收",
};

function featureLabel(feature: string): string {
  return FEATURE_LABEL[feature] ?? feature;
}

interface ApiErrorLike {
  error_type: string;
  message: string;
}

async function parseHttpError(resp: Response): Promise<ApiErrorLike> {
  try {
    const body = await resp.json();
    const detail = body?.detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      return {
        error_type: (detail.error_type as string) ?? `HTTP_${resp.status}`,
        message: detail.message as string,
      };
    }
    return {
      error_type: `HTTP_${resp.status}`,
      message: typeof detail === "string" ? detail : resp.statusText,
    };
  } catch {
    return { error_type: `HTTP_${resp.status}`, message: resp.statusText };
  }
}

/**
 * 调 /api/agent/orchestrate 并逐帧吐 SSE 事件。帧格式同问书：
 * ``event: <type>\ndata: <json>\n\n``。setup-time 错误（session 不存在 / 书太大 /
 * SDK 缺）走 HTTP 4xx，不进流——这里抛 ApiErrorLike。
 */
async function* streamOrchestrate(args: {
  goal: string;
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}): AsyncGenerator<OrchestrateEvent> {
  const body: Record<string, unknown> = {
    goal: args.goal,
    book_session_id: args.sessionId,
    provider: args.provider,
    api_key: args.apiKey,
  };
  if (args.model) body.model = args.model;
  if (args.baseUrl) body.base_url = args.baseUrl;

  const resp = await fetch("/api/agent/orchestrate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw await parseHttpError(resp);
  if (!resp.body)
    throw { error_type: "NoStreamBody", message: "响应没有流式正文" };

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let eventType = "";
      const dataLines: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventType = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!eventType || dataLines.length === 0) continue;
      try {
        const data = JSON.parse(dataLines.join("\n"));
        yield { ...data, type: eventType } as OrchestrateEvent;
      } catch {
        // 单帧解析失败不打断流
      }
    }
  }
}

interface AgentOrchestrateProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  /** drill-into：父组件据功能名 + 参数跳进 App 里那个功能的完整视图。 */
  onDrill: (drill: DrillInfo) => void;
  /** 互相递：从某个功能视图「把它跟别的维度串起来看」过来时，预填一个目标 + 令牌，到了就自动编排一次。 */
  prefill?: { goal: string; token: number } | null;
}

export function AgentOrchestrate({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  onDrill,
  prefill,
}: AgentOrchestrateProps) {
  const [goal, setGoal] = useState("");
  const [running, setRunning] = useState(false);
  const [plan, setPlan] = useState<PlanEntry[] | null>(null);
  const [steps, setSteps] = useState<StepEntry[]>([]);
  const [synthesis, setSynthesis] = useState<{
    text: string;
    citations: OrchestrateCitation[];
  } | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [error, setError] = useState<ApiErrorLike | null>(null);

  // 互相递：prefill 令牌变化时填入目标并自动编排一次（apiKey 缺时只填不跑）。
  useEffect(() => {
    if (!prefill || !prefill.goal.trim()) return;
    setGoal(prefill.goal);
    if (apiKey) void run(prefill.goal);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.token]);

  async function run(override?: string) {
    const g = (override ?? goal).trim();
    if (!g || !apiKey || running) return;
    setRunning(true);
    setError(null);
    setPlan(null);
    setSteps([]);
    setSynthesis(null);
    setTrace(null);
    try {
      const stream = streamOrchestrate({
        goal: g,
        sessionId,
        provider,
        apiKey,
        model,
        baseUrl,
      });
      for await (const ev of stream) {
        if (ev.type === "plan") {
          setPlan(ev.plan);
        } else if (ev.type === "step") {
          setSteps((prev) => [
            ...prev,
            {
              feature: ev.feature,
              summary: ev.summary,
              found: ev.found,
              drill: ev.drill,
            },
          ]);
        } else if (ev.type === "synthesis") {
          setSynthesis({ text: ev.text, citations: ev.citations });
        } else if (ev.type === "done") {
          if (ev.trace) setTrace(ev.trace);
        } else if (ev.type === "error") {
          setError({ error_type: "OrchestrateFailed", message: ev.message });
        }
      }
    } catch (err) {
      setError(err as ApiErrorLike);
    } finally {
      setRunning(false);
    }
  }

  // 还没跑成几个功能、计划也没出来时——进度感全靠"计划 + 已跑步数"逐条出。
  const plannedCount = plan?.length ?? 0;
  const doneCount = steps.length;

  return (
    <div className="grid gap-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run();
        }}
        className="grid gap-3"
      >
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="说一个目标，让 agent 自己规划该跑哪几个分析、串起来综合给你。比如：这本书伏笔铺得怎么样？或：这书在论证什么、证据扎不扎实？"
          rows={3}
          className="rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm resize-y min-h-[80px]"
        />
        <button
          type="submit"
          disabled={!goal.trim() || !apiKey || running}
          className="inline-flex items-center gap-2 bg-[var(--color-seal)] text-white px-5 py-2 rounded hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed text-sm transition-all self-start"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {running ? (
            <>
              <span className="animate-pulse">●</span>
              agent 编排中 · 见下方进度
            </>
          ) : (
            "让 agent 编排"
          )}
        </button>
      </form>

      {error && (
        <div
          role="alert"
          className="border border-[var(--color-seal)]/40 bg-[var(--color-seal)]/5 p-4 rounded"
        >
          <p className="text-sm leading-relaxed text-[var(--color-ink)]">
            {orchestrateErrorCopy(error)}
          </p>
          <button
            type="button"
            onClick={() => run()}
            disabled={running}
            className="mt-3 inline-flex items-center gap-2 px-4 py-1.5 rounded text-sm bg-[var(--color-seal)] text-white hover:brightness-110 disabled:opacity-50 transition-all"
            style={{ fontFamily: "var(--font-display)" }}
          >
            再试一次
          </button>
        </div>
      )}

      {/* 计划：打算跑哪几个、每个 why */}
      {plan && (
        <section className="rounded-md border border-[var(--color-rule)] bg-[var(--color-surface)] p-4">
          <div className="flex items-center gap-2 mb-2.5">
            <span className="text-[var(--color-seal)]" aria-hidden>
              ❡
            </span>
            <h3
              className="text-sm text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
            >
              编排计划
              {running && (
                <span className="ml-2 text-xs text-[var(--color-ink-muted)] font-normal">
                  · {doneCount} / {plannedCount} 跑完
                </span>
              )}
            </h3>
          </div>
          {plan.length === 0 ? (
            <p className="text-sm text-[var(--color-ink-muted)]">
              没规划出可跑的分析——目标太泛或这本书不适用，换个更具体的目标再试。
            </p>
          ) : (
            <ol className="space-y-2">
              {plan.map((p, i) => {
                const ran = steps.some((s) => s.feature === p.feature);
                return (
                  <li
                    key={`${p.feature}-${i}`}
                    className="flex items-start gap-2.5 text-sm"
                  >
                    <span
                      className="mt-0.5"
                      style={{
                        color: ran
                          ? "var(--color-seal)"
                          : "var(--color-ink-muted)",
                      }}
                      aria-hidden
                    >
                      {ran ? "✓" : running ? "●" : "·"}
                    </span>
                    <span>
                      <span
                        className="text-[var(--color-ink)]"
                        style={{
                          fontFamily: "var(--font-display)",
                          fontWeight: 600,
                        }}
                      >
                        {featureLabel(p.feature)}
                      </span>
                      {p.why && (
                        <span className="text-[var(--color-ink-muted)]">
                          {" "}
                          —— {p.why}
                        </span>
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
        </section>
      )}

      {/* 等计划：刚提交、plan 还没回来 */}
      {running && !plan && (
        <p className="text-sm text-[var(--color-ink-muted)] italic">
          <span className="animate-pulse">●</span> agent 正在读这本书、规划该跑哪几个分析…
        </p>
      )}

      {/* 逐步结果：每个功能一条 + drill-into */}
      {steps.length > 0 && (
        <section>
          <h3 className="text-xs tracking-wider text-[var(--color-ink-muted)] mb-2.5">
            逐个跑 · {steps.length} 个分析
          </h3>
          <ol className="space-y-2.5">
            {steps.map((s, i) => (
              <li
                key={`${s.feature}-${i}`}
                className="rounded-md border px-3.5 py-2.5 flex items-center justify-between gap-3"
                style={{
                  borderColor: "var(--color-folio-edge)",
                  background: "var(--color-paper-raised)",
                }}
              >
                <div className="min-w-0">
                  <div
                    className="text-[14px] text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
                  >
                    {featureLabel(s.feature)}
                  </div>
                  <div className="text-xs text-[var(--color-ink-muted)] mt-0.5">
                    {s.summary}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onDrill(s.drill)}
                  className="shrink-0 text-xs px-2.5 py-1.5 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] transition-colors"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  点开看完整「{featureLabel(s.feature)}」视图
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}

      {/* 综合：带行内引用、核验过的盖「鉴」印 */}
      {synthesis && (
        <article className="mt-2 space-y-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span
                className="inline-block w-1.5 h-1.5 rounded-full"
                style={{ background: "var(--color-seal)" }}
                aria-hidden
              />
              <h3
                className="text-sm tracking-wide text-[var(--color-ink)]"
                style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
              >
                综合
              </h3>
            </div>
            <div
              className="whitespace-pre-wrap leading-[1.85] text-[15.5px] text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {synthesis.text}
            </div>
          </div>

          {synthesis.citations.length > 0 && (
            <div>
              <h3 className="text-xs tracking-wider text-[var(--color-ink-muted)] mb-3">
                原文为证 · {synthesis.citations.length} 条
              </h3>
              <ol className="space-y-3">
                {synthesis.citations.map((c, idx) => (
                  <li
                    key={idx}
                    className="relative rounded-md border px-3.5 py-3"
                    style={{
                      borderColor: "var(--color-folio-edge)",
                      background: "var(--color-paper-raised)",
                    }}
                  >
                    {c.verified !== false && (
                      <SealMark
                        className="seal-stamp absolute top-2.5 right-2.5"
                        title="编排综合的每条结论都钉在已核验的原文上，盖章为证"
                      />
                    )}
                    <div className="text-xs text-[var(--color-ink-muted)] mb-1.5 pr-9">
                      第 {c.chapter} 章
                    </div>
                    <div
                      className="text-[14px] leading-relaxed text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {c.snippet}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </article>
      )}

      {!running && trace && <RunStats trace={trace} />}
    </div>
  );
}

// 编排出错的友好文案——沿用现有错误兜底口吻（说人话、不甩锅）。
function orchestrateErrorCopy(error: ApiErrorLike): string {
  if (error.error_type === "BookTooLargeForOrchestrate") {
    return "这本书太大，编排要把整本书塞进上下文，暂时跑不了。可以直接用左栏单个分析功能。";
  }
  if (
    error.error_type === "ProviderSdkMissing" ||
    error.error_type === "ClientBuildFailed"
  ) {
    return "连不上你选的 AI——去设置看看 key 填了没、厂商选对没。";
  }
  // 其余（编排中途整体失败 / 网络 / 超时）统一兜底
  return (
    error.message ||
    "编排这一步出岔子了，跟你的目标没关系。再试一次大概率就好；或者直接用左栏单个分析功能。"
  );
}
