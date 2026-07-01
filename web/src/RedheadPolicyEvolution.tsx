// ---------------------------------------------------------------------------
// RedheadPolicyEvolution — 政策演变（1.6 红头文件垂直·跨文件二炮）
//
// 一项政策很少一份文件定死——先出个意见、再出实施办法、过两年又修订。一卷宗里好几份
// 公文摆一起，这块按成文日期排出**政策怎么一步步变的**：哪份先出、改了什么、再哪份接着改，
// 每个阶段钉一句那份文件的原话。一眼看清这项政策的来龙去脉。
//
// 意象 = 政策编年 / 案卷纪年（官府办事的政策沿革），不套小说的叙事曲线、不做通用甘特图：
//   一道竖直朱砂纪年轴贯穿全程，每个阶段一枚朱砂年轮墨钉钉在轴上（编年的纪年点），
//   左边「成文日期」走日晷牌（朱砂描边纪时牌），右边「这份文件改了什么」+ 真实发文字号
//   +（核得到的）那份文件原话。阶段按成文先后从上往下排（后端排好序），顶「起」底「讫」收束。
//   可另指定一个政策主题，只排这条线的演变。
//
// evidence-first（全站一个规矩）：阶段是后端按成文日期排的，每阶段 snippet 取那份文脉里
// 已核的原文（锚不到原文的阶段后端直接丢）。主题不在这摞文件 → 空 + scanned=true（老实说
// 「这卷宗里没这条政策线」）；一次推理失败 / 没可锚文件 → scanned=false，优雅退场。
//
// 设计语言（数字善本案头）：朱墨双色、宋体 var(--font-display)、留白克制——不堆古风、
// 无 emoji、不做成通用时间线组件。verified 的原话盖一枚「鉴」印（SealMark）。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";
import { DossierHint } from "./RedheadDependencyGraph";

// ---- 后端契约（对着 /api/agent/redhead/policy-evolution 写，别改后端） ----

interface PolicyStage {
  order: number; // 排序序（后端按成文日期排好）
  doc: string; // 真实发文字号
  change: string; // 这份文件改了什么 / 推进了什么
  snippet: string; // 那份文脉里已核的原文片段（锚不到的阶段后端会丢）
  verified: boolean;
}

// 措辞 diff（逐字比）——政策的新闻藏在措辞变化的 delta 里：鼓励→应当（升格）、
// 严格→合理（松绑）、某提法删了（转向）。before/after 是后端逐字核过的原话（对不上的丢），
// direction 是研判口径（套约束力阶梯判方向）。后端新增字段，老后端没有则为空、不渲染这层。
interface PolicyDiff {
  topic_point: string; // 这条 diff 针对的同一件事 / 同一提法
  before: string; // 旧措辞（逐字原话；「新增」时为空）
  before_doc: string; // 旧措辞来自哪份文件
  after: string; // 新措辞（逐字原话；「删除」时为空）
  after_doc: string; // 新措辞来自哪份文件
  direction: string; // 升格 / 松绑 / 收紧 / 转向 / 新增 / 删除
  basis: string; // 凭措辞里哪个词判的方向
  verified: boolean;
}

interface PolicyEvolutionResponse {
  stages: PolicyStage[];
  wording_diffs?: PolicyDiff[]; // 措辞 diff 层（后端新增；老后端无此字段）
  scanned: boolean;
  trace?: RunTrace;
}

// 方向标签的朱墨配色：升格 / 收紧 = 实心朱印（要紧的方向，动真格 / 加严）；
// 松绑 = 朱描边（放宽）；转向 / 新增 / 删除 = 墨描边（中性事实）。不堆色，朱墨两系。
const DIRECTION_STYLE: Record<
  string,
  { fill: boolean; tone: "seal" | "ink"; hint: string }
> = {
  升格: { fill: true, tone: "seal", hint: "约束力升：要动真格了" },
  收紧: { fill: true, tone: "seal", hint: "门槛 / 标准收窄" },
  松绑: { fill: false, tone: "seal", hint: "约束力降：放宽了" },
  转向: { fill: false, tone: "ink", hint: "提法换了方向 / 口径" },
  新增: { fill: false, tone: "ink", hint: "旧版没有、新版加上" },
  删除: { fill: false, tone: "ink", hint: "旧版有、新版删掉" },
};

interface RedheadPolicyEvolutionProps {
  bookSessionIds: string[];
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

function hasText(v: string | null | undefined): boolean {
  return !!v && v.trim().length > 0;
}

export function RedheadPolicyEvolution({
  bookSessionIds,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadPolicyEvolutionProps) {
  const [result, setResult] = useState<PolicyEvolutionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [topic, setTopic] = useState("");
  // 默认收起原文，点开看撑这个阶段的那句原话
  const [openOrigin, setOpenOrigin] = useState<Record<number, boolean>>({});
  // 这次结果是不是带主题跑的——空态文案据此区分（主题没命中 vs 整卷宗没政策线）
  const [ranWithTopic, setRanWithTopic] = useState(false);

  const canRun = bookSessionIds.length >= 2 && !!apiKey;

  async function load() {
    if (bookSessionIds.length < 2) return;
    setLoading(true);
    setError(null);
    setOpenOrigin({});
    const t = topic.trim();
    setRanWithTopic(!!t);
    try {
      const body: Record<string, unknown> = {
        book_session_ids: bookSessionIds,
        provider,
        api_key: apiKey,
      };
      if (t) body.topic = t;
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/policy-evolution", {
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
      const data = (await resp.json()) as PolicyEvolutionResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const stages = result?.stages ?? [];
  const diffs = useMemo(
    () => (result?.wording_diffs ?? []).filter((d) => d.verified),
    [result],
  );
  const scanned = !!result && result.scanned;
  // 排出了阶段、或抓到了措辞 diff，都算「有料」——diff 层独立，可能阶段没排出但 diff 有
  const gotSomething = scanned && (stages.length > 0 || diffs.length > 0);
  const verifiedCount = useMemo(
    () => stages.filter((s) => s.verified && hasText(s.snippet)).length,
    [stages],
  );

  // ---- 未生成：入口卡片（带主题输入框） ----
  if (!result) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1 flex items-center gap-2"
          style={{ fontFamily: "var(--font-display)" }}
        >
          <span
            className="h-4 w-[3px] rounded-full bg-[var(--color-seal)]"
            aria-hidden="true"
          />
          政策演变
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          把一卷宗里好几份公文按成文日期排成一条线——哪份先出、改了什么、再哪份接着改，看一项政策是怎么一步步演变到现在的，每个阶段钉一句那份文件的原话。可以只盯一个主题排（比如「补贴标准」），也可整卷宗排。阶段是按成文日期排的、原话从原文锚出来的，绝不替你脑补先后。适合一组同主题、有先后的党政公文。
        </p>
        <DossierHint count={bookSessionIds.length} />
        <div className="mt-3 mb-1">
          <label className="block text-xs text-[var(--color-ink-muted)] mb-1.5">
            盯一个政策主题（可空，空则整卷宗排）
          </label>
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="如：补贴标准 / 审批流程 / 适用范围"
            className="w-full max-w-md text-sm px-3 py-2 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] focus:border-[var(--color-seal)] focus:outline-none"
            style={{ fontFamily: "var(--font-display)" }}
          />
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading || !canRun}
          className="mt-2 text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读这卷宗排政策演变中（约 1-2 分钟）…" : "排出政策演变"}
        </button>
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {loading && (
          <RunningProcess
            label="读这卷宗排政策演变"
            hint="卷宗里每份公文各建文脉，再按成文日期排出演变阶段，每阶段标改了什么、钉一句原话，约 1-2 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没排出：优雅退场，区分「主题没命中」和「整卷宗没政策线」 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        <ViewHeader title="政策演变" loading={loading} onReload={load} />
        {loading ? (
          <RunningProcess label="读这卷宗排政策演变" />
        ) : scanned ? (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            {ranWithTopic
              ? "这卷宗里没排出这个主题的演变线，可能这几份文件没都谈到它，或者主题换个说法再试（比如把「补贴」换成原文里的准确叫法）。也可以清空主题、整卷宗排一遍看看。"
              : "没排出政策演变，这卷宗里的公文可能不是同一项政策的不同阶段，或者彼此没有先后承继关系。挑一组同主题、有先后的公文（比如意见 + 实施办法 + 修订版），再试一次。"}
          </p>
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            没排出政策演变——没有能锚回原文的真实文件，或者这几份文件凑不出一条政策线。挑一组同主题、有先后的公文再试一次。
          </p>
        )}
      </div>
    );
  }

  // ---- 已排出：政策编年时序 ----
  return (
    <div className="pt-4">
      <ViewHeader title="政策演变" loading={loading} onReload={load} />

      {/* 题署：编年 · 几个阶段 · 原文核验几个 · 措辞变化几处 */}
      <div className="mb-4 flex items-center gap-2 flex-wrap">
        {stages.length > 0 && (
          <>
            <span
              className="inline-block text-xs px-2 py-0.5 rounded-full"
              style={{
                color: "var(--color-seal)",
                border: "0.5px solid var(--color-seal)",
              }}
            >
              政策编年 · {stages.length} 个阶段
            </span>
            <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
              原文核验 {verifiedCount}/{stages.length}
            </span>
          </>
        )}
        {diffs.length > 0 && (
          <span
            className="inline-block text-xs px-2 py-0.5 rounded-full"
            style={{ color: "var(--color-seal)", border: "0.5px solid var(--color-seal)" }}
          >
            措辞变化 · {diffs.length} 处
          </span>
        )}
        {ranWithTopic && hasText(topic) && (
          <span className="text-xs text-[var(--color-ink-muted)]">
            主题 ·{" "}
            <span className="text-[var(--color-ink)]">{topic.trim()}</span>
          </span>
        )}
      </div>

      {/* ── 政策编年：竖直朱砂纪年轴 + 每阶段年轮墨钉 ── */}
      {stages.length > 0 && (
      <div className="relative pl-1">
        <div
          aria-hidden
          className="absolute top-0 bottom-0"
          style={{
            left: "calc(6rem + 7px)",
            width: "2px",
            background:
              "linear-gradient(to bottom, transparent, var(--color-seal) 6%, var(--color-seal) 94%, transparent)",
            opacity: 0.5,
          }}
        />

        <ol className="space-y-5">
          {stages.map((s, i) => {
            const verified = s.verified && hasText(s.snippet);
            const isOpen = !!openOrigin[i];
            const canOpenOrigin = hasText(s.snippet);
            const first = i === 0;
            const last = i === stages.length - 1;
            return (
              <li key={i} className="relative flex items-stretch gap-0">
                {/* 左栏：日晷牌——发文字号摆这里当纪年牌（公文的纪年就是字号 + 日期） */}
                <div className="shrink-0 pt-0.5" style={{ width: "6rem" }}>
                  <div
                    className="inline-flex flex-col items-end text-right rounded px-2 py-1 leading-tight"
                    style={{
                      border: "0.5px solid var(--color-seal)",
                      background: "var(--color-seal-soft)",
                      fontFamily: "var(--font-display)",
                    }}
                  >
                    <span
                      className="text-caption font-bold tabular-nums break-all"
                      style={{ color: "var(--color-seal)" }}
                    >
                      {hasText(s.doc) ? s.doc : `第 ${s.order ?? i + 1} 阶段`}
                    </span>
                  </div>
                </div>

                {/* 中栏：年轮墨钉钉在轴上。起 / 讫两端加横规。 */}
                <div className="w-4 shrink-0 flex flex-col items-center relative">
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

                {/* 右栏：这份文件改了什么 + 原话（默认收起） */}
                <div className="flex-1 min-w-0 pl-3 pb-1">
                  <div className="flex items-start gap-2">
                    {verified && <SealMark size={17} title="原文已核验" />}
                    <p
                      className="text-body leading-7 text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {hasText(s.change)
                        ? s.change
                        : "（这一阶段没说改了什么）"}
                    </p>
                  </div>

                  {!verified && (
                    <p className="mt-1 text-xs text-[var(--color-ink-muted)] italic">
                      {hasText(s.snippet)
                        ? "未在原文比对命中·仅供参考"
                        : "暂无贴切原文（待核）"}
                    </p>
                  )}

                  {canOpenOrigin && (
                    <div className="mt-1.5">
                      <button
                        type="button"
                        onClick={() =>
                          setOpenOrigin((cur) => ({ ...cur, [i]: !cur[i] }))
                        }
                        className="text-caption text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                      >
                        {isOpen ? "收起原文" : "看原文出处"}
                      </button>
                      {isOpen && (
                        <p
                          className="mt-1.5 text-body-sm leading-relaxed text-[var(--color-ink)] border-l-2 pl-3"
                          style={{
                            borderColor:
                              "color-mix(in oklch, var(--color-seal) 40%, transparent)",
                            fontFamily: "var(--font-display)",
                          }}
                        >
                          {s.snippet}
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
      )}

      {/* ── 措辞 diff（逐字比）：政策的新闻在 delta 里 ── */}
      {diffs.length > 0 && (
        <div className={stages.length > 0 ? "mt-7" : ""}>
          <div className="flex items-baseline gap-2 mb-1">
            <h4
              className="text-sm font-bold text-[var(--color-ink)] flex items-center gap-2"
              style={{ fontFamily: "var(--font-display)" }}
            >
              <span
                className="h-3.5 w-[3px] rounded-full bg-[var(--color-seal)]"
                aria-hidden="true"
              />
              措辞变化
            </h4>
            <span className="text-xs text-[var(--color-ink-muted)]">
              逐字比，新闻在改了的词里
            </span>
          </div>
          <p className="text-xs text-[var(--color-ink-muted)] mb-3 leading-relaxed">
            同一件事跨文件措辞变了的地方——旧措辞、新措辞逐字摆出来。方向（升格 / 松绑 /
            收紧…）是按约束力阶梯研判的口径；两边的原话都从原文逐字锚出来、核过才留。
          </p>
          <ul className="space-y-3">
            {diffs.map((d, i) => (
              <DiffCard key={i} diff={d} />
            ))}
          </ul>
        </div>
      )}

      {!loading && (
        <RunStats
          trace={trace}
          note={
            `政策编年 ${stages.length} 个阶段 · 原文核验 ${verifiedCount}` +
            (diffs.length > 0 ? ` · 措辞变化 ${diffs.length} 处` : "")
          }
        />
      )}
    </div>
  );
}

// 一条措辞 diff：topic_point + 方向印 + 旧措辞 →(朱砂) 新措辞（逐字、盖鉴印）+ basis。
function DiffCard({ diff }: { diff: PolicyDiff }) {
  const ds = DIRECTION_STYLE[diff.direction] ?? {
    fill: false,
    tone: "ink" as const,
    hint: "",
  };
  const hasBefore = hasText(diff.before);
  const hasAfter = hasText(diff.after);
  return (
    <li
      className="rounded border p-3"
      style={{
        borderColor: "var(--color-rule)",
        background: "var(--color-paper)",
      }}
    >
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <DirectionBadge direction={diff.direction} style={ds} />
        {hasText(diff.topic_point) && (
          <span
            className="text-body-sm font-bold text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {diff.topic_point}
          </span>
        )}
      </div>

      {/* 旧措辞 → 新措辞：逐字原话，各盖鉴印 + 标来自哪份 */}
      <div className="space-y-1.5">
        {hasBefore && (
          <WordingLine
            tag="旧"
            text={diff.before}
            doc={diff.before_doc}
            tone="muted"
          />
        )}
        {hasAfter && (
          <WordingLine
            tag="新"
            text={diff.after}
            doc={diff.after_doc}
            tone="ink"
          />
        )}
      </div>

      {hasText(diff.basis) && (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)] leading-relaxed">
          {diff.basis}
        </p>
      )}
    </li>
  );
}

function DirectionBadge({
  direction,
  style,
}: {
  direction: string;
  style: { fill: boolean; tone: "seal" | "ink"; hint: string };
}) {
  const accent =
    style.tone === "seal" ? "var(--color-seal)" : "var(--color-ink)";
  return (
    <span
      title={style.hint || undefined}
      className="inline-flex items-center text-caption px-1.5 py-0.5 rounded font-bold shrink-0"
      style={{
        fontFamily: "var(--font-display)",
        color: style.fill ? "var(--color-paper)" : accent,
        background: style.fill ? accent : "transparent",
        border: `0.5px solid ${accent}`,
      }}
    >
      {direction}
    </span>
  );
}

function WordingLine({
  tag,
  text,
  doc,
  tone,
}: {
  tag: string;
  text: string;
  doc: string;
  tone: "muted" | "ink";
}) {
  return (
    <div className="flex items-start gap-2">
      <span
        className="text-caption mt-1 px-1 rounded shrink-0 leading-tight"
        style={{
          color: "var(--color-ink-muted)",
          border: "0.5px solid var(--color-rule)",
          fontFamily: "var(--font-display)",
        }}
      >
        {tag}
      </span>
      <SealMark size={15} title="原文逐字已核验" className="mt-0.5" />
      <div className="min-w-0">
        <span
          className="text-body-sm leading-relaxed"
          style={{
            fontFamily: "var(--font-display)",
            color:
              tone === "ink" ? "var(--color-ink)" : "var(--color-ink-muted)",
          }}
        >
          {text}
        </span>
        {hasText(doc) && (
          <span className="ml-2 text-caption text-[var(--color-ink-muted)] tabular-nums break-all">
            — {doc}
          </span>
        )}
      </div>
    </div>
  );
}

function ViewHeader({
  title,
  loading,
  onReload,
}: {
  title: string;
  loading: boolean;
  onReload: () => void;
}) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h3
        className="text-base font-bold text-[var(--color-ink)]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        {title}
      </h3>
      <button
        type="button"
        onClick={onReload}
        disabled={loading}
        className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
      >
        {loading ? "重出中…" : "重新生成"}
      </button>
    </div>
  );
}
