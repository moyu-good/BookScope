// ---------------------------------------------------------------------------
// RedheadTimeline — 公文关键时间轴（1.6 红头文件垂直·三炮）
//
// 一份公文里时间散落各处——申报截止在第三条、过渡期在第十条、生效日在落款、阶段目标埋在
// 附则。这块把这些**带时间的要求**抽出来，排成一条**编年时序**：从上到下一条朱砂时轴，
// 每个时间节点钉在轴上，左边是这个点的「时间」（具体日期 / 「自印发起30日内」这类相对期），
// 右边是「到这个点要发生啥」+ 撑它的原文。一眼看清这份公文给你定了哪些时间节点。
//
// 意象 = 编年 / 时轴 / 排程（官府办事的时间线），不是套书的山水叙事曲线、不是通用甘特图：
//   一道竖直朱砂时轴贯穿全程（像案牍编年的纪年线）→ 每个节点一枚朱砂年轮墨钉钉在轴上 →
//   时间走「日晷牌」形态（朱砂描边小牌摆日期 / 相对期，案头记事的纪时牌）→ 事项墨色宋体在右。
//   节点按时间先后从上往下排（后端排好序），轴有起讫——顶上「起」、底下「讫」两道横规收束。
//
// evidence-first（全站一个规矩）：时间是从原文抽的、不是脑补——撑这个时间的原文核得到的，
// 节点上盖「鉴」印；核不过的老实标「未在原文比对命中·仅供参考」/「待核」，绝不假装这个日期
// 有原文撑。没抽到带时间的要求 → 优雅退场，不画空轴。
//
// 设计语言（数字善本案头，参 docs/design/WP-ui-design-language.md）：朱墨双色（朱砂 =
// var(--color-seal) 时轴 / 年轮 / 日晷牌描边，墨 = var(--color-ink) 事项主体，淡墨 =
// var(--color-ink-muted) 原文 / 元信息）、宋体 var(--font-display)、留白、古籍克制——
// 不堆古风、无 emoji、不做成通用甘特图 / 表格。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（对着 redhead_timeline.timeline_from_spine 写） ----

interface TimelineNode {
  when: string; // 时间：具体日期或「自印发起30日内」这类相对期（照原文写法）
  what: string; // 到这个时间点要发生 / 完成啥
  chapter: number | null; // 来源条款序号（可能 null）
  evidence: string; // 撑这个时间的原文逐字片段
  verified: boolean;
  match_score: number;
}

interface TimelineResponse {
  nodes: TimelineNode[];
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface RedheadTimelineProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

function hasText(v: string): boolean {
  return !!v && v.trim().length > 0;
}

export function RedheadTimeline({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadTimelineProps) {
  const [result, setResult] = useState<TimelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 默认收起原文，点开看撑这个时间的那句原话——保时轴干净，要溯源再展开
  const [openOrigin, setOpenOrigin] = useState<Record<number, boolean>>({});

  async function load() {
    setLoading(true);
    setError(null);
    setOpenOrigin({});
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/timeline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const j = (await resp.json().catch(() => null)) as
          | { detail?: { message?: string } }
          | null;
        throw new Error(j?.detail?.message ?? `请求失败（${resp.status}）`);
      }
      const data = (await resp.json()) as TimelineResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const nodes = result?.nodes ?? [];
  const scanned = !!result && result.scanned;
  const gotSomething = scanned && nodes.length > 0;
  const verifiedCount = useMemo(
    () => nodes.filter((n) => n.verified && hasText(n.evidence)).length,
    [nodes],
  );

  // ---- 未生成：入口卡片 ----
  if (!result) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1 flex items-center gap-2"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {/* 红头点缀：标题前一道朱砂短脊，预告这是红头公文视图 */}
          <span
            className="h-4 w-[3px] rounded-full bg-[var(--color-seal)]"
            aria-hidden="true"
          />
          关键时间轴
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          把一份红头文件里散落各处的时间节点拉成一条时序——申报截止、实施日、过渡期、生效、废止、阶段目标，一眼看清这份公文给你定了哪些时间点、各要在哪个点前做什么，每个节点钉在原文。时间从原文里抽、绝不替你换算或脑补日期。适合党政公文
          / 红头文件。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "抽出时间节点排成时序中（约 1 分钟）…" : "排出关键时间轴"}
        </button>
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {!apiKey && (
          <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
            填了 API key 才能生成。
          </p>
        )}
        {loading && (
          <RunningProcess
            label="排出关键时间轴"
            hint="整份公文喂进模型先拆出条款，再把带时间的要求挑出来排成时序——每个节点都回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没抽到：优雅退场，不画空轴 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        <div className="flex items-center justify-between mb-3">
          <h3
            className="text-base font-bold text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            关键时间轴
          </h3>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
          >
            {loading ? "重出中…" : "重新生成"}
          </button>
        </div>
        {loading ? (
          <RunningProcess label="排出关键时间轴" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            没抽到带时间的要求——这份公文可能没定具体时间节点（如纯倡导性意见），或者格式太特殊。换一份带申报截止
            / 实施日 / 过渡期的公文，或稍后重试。
          </p>
        )}
      </div>
    );
  }

  // ---- 已抽到：编年时序 ----
  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          关键时间轴
        </h3>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "重出中…" : "重新生成"}
        </button>
      </div>

      {/* 题署一行：共几个时间节点 · 原文核验几个。朱印描边小签，案头规矩。 */}
      <div className="mb-4 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          编年 · {nodes.length} 个时间节点
        </span>
        <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
          原文核验 {verifiedCount}/{nodes.length}
        </span>
      </div>

      {/* ── 编年时序：一道竖直朱砂时轴贯穿全程，每个节点一枚年轮墨钉钉在轴上 ── */}
      {/* 时轴：左侧一条贯通的朱砂竖线（案牍编年的纪年线）。顶「起」底「讫」两道横规收束。 */}
      <div className="relative pl-1">
        {/* 贯通竖轴——从首节点到末节点，居于左栏年轮的中线上（left = 日晷牌区宽度 + 年轮半径） */}
        <div
          aria-hidden
          className="absolute top-0 bottom-0"
          style={{
            left: "calc(5.5rem + 7px)",
            width: "2px",
            background:
              "linear-gradient(to bottom, transparent, var(--color-seal) 6%, var(--color-seal) 94%, transparent)",
            opacity: 0.5,
          }}
        />

        <ol className="space-y-5">
          {nodes.map((n, i) => {
            const verified = n.verified && hasText(n.evidence);
            const isOpen = !!openOrigin[i];
            const canOpenOrigin = hasText(n.evidence);
            const first = i === 0;
            const last = i === nodes.length - 1;
            return (
              <li key={i} className="relative flex items-stretch gap-0">
                {/* 左栏：日晷牌——朱砂描边小牌摆「时间」（纪时牌），案头记事的站位 */}
                <div className="shrink-0 pt-0.5" style={{ width: "5.5rem" }}>
                  {hasText(n.when) ? (
                    <div
                      className="inline-flex flex-col items-end text-right rounded px-2 py-1 leading-tight"
                      style={{
                        border: "0.5px solid var(--color-seal)",
                        background: "var(--color-seal-soft)",
                        fontFamily: "var(--font-display)",
                      }}
                    >
                      <span
                        className="text-[12.5px] font-bold tabular-nums"
                        style={{ color: "var(--color-seal)" }}
                      >
                        {n.when}
                      </span>
                    </div>
                  ) : (
                    <span className="text-[11px] text-[var(--color-ink-muted)] italic">
                      时间待核
                    </span>
                  )}
                </div>

                {/* 中栏：年轮墨钉——钉在竖轴上的朱砂圆印（编年的纪年点）。起 / 讫两端加横规。 */}
                <div className="w-4 shrink-0 flex flex-col items-center relative">
                  {/* 起讫横规：首节点上加一道「起」横线，末节点下加一道「讫」横线 */}
                  {first && (
                    <span
                      aria-hidden
                      className="absolute -top-1 h-px w-3"
                      style={{ background: "var(--color-seal)", opacity: 0.6 }}
                    />
                  )}
                  <span
                    aria-hidden
                    className="mt-1 rounded-full shrink-0 z-10"
                    style={{
                      width: "12px",
                      height: "12px",
                      // 核过的实心朱砂年轮；核不过的空心年轮（描边不填色）——状态从纪年点上一眼看出
                      background: verified
                        ? "var(--color-seal)"
                        : "var(--color-paper)",
                      border: "2px solid var(--color-seal)",
                      opacity: verified ? 1 : 0.55,
                    }}
                  />
                  {last && (
                    <span
                      aria-hidden
                      className="absolute -bottom-1 h-px w-3"
                      style={{ background: "var(--color-seal)", opacity: 0.6 }}
                    />
                  )}
                </div>

                {/* 右栏：事项——墨色宋体主体 + 元信息（第几条）+ 原文（默认收起） */}
                <div className="flex-1 min-w-0 pl-3 pb-1">
                  <div className="flex items-start gap-2">
                    {verified && <SealMark size={17} title="原文已核验" />}
                    <p
                      className="text-[15px] leading-7 text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {n.what || "（这个时间点没说要发生啥）"}
                    </p>
                  </div>

                  {/* 元信息：来自第几条——有才显示 */}
                  {typeof n.chapter === "number" && (
                    <p className="mt-1 text-xs text-[var(--color-ink-muted)] tabular-nums">
                      出自 第 {n.chapter} 条
                    </p>
                  )}

                  {/* 核不过老实标一行，绝不假装这个日期有原文撑 */}
                  {!verified && (
                    <p className="mt-1 text-xs text-[var(--color-ink-muted)] italic">
                      {hasText(n.evidence)
                        ? "未在原文比对命中·仅供参考"
                        : "暂无贴切原文（待核）"}
                    </p>
                  )}

                  {/* 原文——撑这个时间的那句，默认收起。点「看原文」展开，朱砂细规一隔，淡墨小字。 */}
                  {canOpenOrigin && (
                    <div className="mt-1.5">
                      <button
                        type="button"
                        onClick={() =>
                          setOpenOrigin((cur) => ({ ...cur, [i]: !cur[i] }))
                        }
                        className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                      >
                        {isOpen ? "收起原文" : "看原文出处"}
                      </button>
                      {isOpen && (
                        <p
                          className="mt-1.5 text-[13px] leading-relaxed text-[var(--color-ink)] border-l-2 pl-3"
                          style={{
                            borderColor: "color-mix(in oklch, var(--color-seal) 40%, transparent)",
                            fontFamily: "var(--font-display)",
                          }}
                        >
                          {n.evidence}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      {!loading && (
        <RunStats
          trace={trace}
          note={`编年 ${nodes.length} 个时间节点 · 原文核验 ${verifiedCount}`}
        />
      )}
    </div>
  );
}
