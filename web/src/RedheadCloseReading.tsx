// ---------------------------------------------------------------------------
// RedheadCloseReading — 逐条精读（1.6 公文整合·centerpiece，整合 1+2）
//
// 由 RedheadPlainLanguage 改造而来。原先读懂一条公文得在三个 tab 来回拼：结构 tab 看「这条是
// 硬要求、谁负责、什么期限」、大白话 tab 看「这条人话什么意思」、名词 tab 查「这条里那个术语
// 啥意思」——三个 tab 啃的是同一批原文条款，只是切面不同。逐条精读把三个切面合到一条卡上，
// 一个富视图替原来的大白话 / 名词解释 / 公文结构条款三趟。
//
// 一条卡 =
//   1. 大白话（plain，墨色主体）——这条官话翻人话；命中措辞刻度点弦外之音（nuance，朱批）。
//   2. 结构标签（朱砂小签）——硬/软 + 责任主体 + 时限 + 依据上位文件。直接取文脉条款骨架。
//   3. 内联术语角标（这条命中的术语，点开出释义）——术语锚在出现它的那条上，不另设全文术语表。
//   4. 对原文（折叠，evidence-first）——核得到的盖「鉴」印。
//
// 后端合成：调 /api/agent/redhead/close-reading 一次出三件套（不在前端拼三个端点）。
//
// evidence-first（全站一个规矩）：大白话背后原文核过的盖「鉴」印、核不过老实标待核；内联术语
// 核不过的后端已不挂；nuance 只在原文真有该词时点。没料 → 优雅退场，不画空壳。
//
// 设计语言（数字善本案头）：朱墨双色（朱 = var(--color-seal) 钤印/书口线/朱批，墨 =
// var(--color-ink) 白话主体）、宋体 var(--font-display)、留白、古籍克制——不堆古风、无 emoji、
// 不做成通用表格。指令类型彩标沿用公文结构那套数据色（跨视图一致）。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（对着 redhead_close_reading.close_reading_from_spine 写） ----

// 弦外之意：命中措辞刻度才有（后端 detect_nuances，可选字段）。
interface Nuance {
  marker: string; // 命中的词，如「原则上」
  meaning: string; // 它的真实含义
}

// 内联术语：这条命中的术语 + 释义（后端按原句归到本条）。
interface InlineTerm {
  term: string; // 术语本身
  explanation: string; // 词典义（人话）
  context_meaning?: string; // 本文件语境特指义（证据层，可空）
  policy_intent?: string; // 政策意图研判（评估层，可空）
}

// 结构标签：硬/软 + 责任主体 + 时限 + 依据（直接取文脉条款骨架）。
interface StructureLabel {
  instruction_type: string; // 封闭集：硬要求 / 软倡导 / 方针部署 / 信息告知 / 依据陈述
  actor: string; // 责任主体（可空）
  deadline: string; // 时限（可空）
  basis_ref: string; // 依据上位文件（可空）
}

interface CloseReadingItem {
  chapter: number; // 条款序号
  matter: string; // 官话事项（旁注）
  plain: string; // 大白话（改写失败退回 matter）；纯表态时是固定说明句、非翻译
  clause_kind?: string; // #5：pure_statement=纯表态(方向不办事) / substantive=实质
  structure: StructureLabel;
  glossary: InlineTerm[]; // 内联术语（可空）
  evidence: string; // 逐字原文
  verified: boolean;
  match_score: number;
  nuance?: Nuance[];
}

interface CloseReadingResponse {
  items: CloseReadingItem[];
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface RedheadCloseReadingProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  // 整合 round2 A：跳去公文结构看整份骨架 + 效力研判（鸟瞰 vs 这里的逐条钻）。不传则不显。
  onJumpToStructure?: () => void;
}

function hasText(v: string | null | undefined): boolean {
  return !!v && v.trim().length > 0;
}

// 指令类型 = 封闭集标签，各配一个克制的色（跟公文结构视图同一套数据色，跨视图一致）。
// 硬要求 → 朱砂；软倡导 → 暖绿；方针部署 → 木褐；信息告知 → 墨青；依据陈述 → 木褐。
// 写死 hex（数据色不跟主题走），未知标签 fallback 走墨色。
const INSTRUCTION_STYLE: Record<string, { fg: string; bg: string }> = {
  硬要求: { fg: "#9a3a2e", bg: "rgba(154, 58, 46, 0.10)" },
  软倡导: { fg: "#4f7a52", bg: "rgba(79, 122, 82, 0.10)" },
  方针部署: { fg: "#8a6b3f", bg: "rgba(138, 107, 63, 0.12)" },
  信息告知: { fg: "#3a6378", bg: "rgba(58, 99, 120, 0.10)" },
  依据陈述: { fg: "#8a6b3f", bg: "rgba(138, 107, 63, 0.10)" },
};

function instructionStyle(type: string): { fg: string; bg: string } {
  return (
    INSTRUCTION_STYLE[type] ?? {
      fg: "var(--color-ink-muted)",
      bg: "var(--color-seal-soft)",
    }
  );
}

export function RedheadCloseReading({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  onJumpToStructure,
}: RedheadCloseReadingProps) {
  const [result, setResult] = useState<CloseReadingResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 默认收起原文夹注，点「对原文」展开——保精读笺干净，要对照再展开
  const [openOrigin, setOpenOrigin] = useState<Record<number, boolean>>({});
  // 点开的术语角标（"条索引-词索引" → 开/合），点词头出释义
  const [openTerm, setOpenTerm] = useState<Record<string, boolean>>({});

  async function load() {
    setLoading(true);
    setError(null);
    setOpenOrigin({});
    setOpenTerm({});
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/close-reading", {
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
      const data = (await resp.json()) as CloseReadingResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const items = result?.items ?? [];
  const scanned = !!result && result.scanned;
  const gotSomething = scanned && items.length > 0;
  const verifiedCount = useMemo(
    () => items.filter((it) => it.verified && hasText(it.evidence)).length,
    [items],
  );
  const nuanceCount = useMemo(
    () => items.filter((it) => (it.nuance?.length ?? 0) > 0).length,
    [items],
  );
  const termCount = useMemo(
    () => items.reduce((n, it) => n + (it.glossary?.length ?? 0), 0),
    [items],
  );

  // ---- 未生成：入口卡片 ----
  if (!result) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          逐条精读
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          一条一条把红头文件吃透。每条三件事一次看全：大白话（这条人话什么意思，碰到「原则上」「研究」这类官腔还点破弦外之意）、结构标签（是硬要求还是软倡导、谁负责、到几号、依据哪份上位文件）、生词随手点开（这条里的政策黑话当场解释）。背后原文核得到的盖「鉴」印，只忠实转述、不替你脑补。适合党政公文
          / 红头文件。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="mt-3 text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "逐条精读中（约 1 分钟）…" : "逐条精读这份公文"}
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
            label="逐条精读"
            hint="整份公文喂进模型，逐条翻成人话、标出硬/软结构、挑出生词，每条回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没抽到：优雅退场 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        <div className="flex items-center justify-between mb-3">
          <h3
            className="text-base font-bold text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            逐条精读
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
          <RunningProcess label="逐条精读" />
        ) : (
          <p className="mt-3 text-sm text-[var(--color-ink-muted)] leading-relaxed">
            这份没拆出可逐条精读的正文，可能正文太短或格式太特殊。换一份规范公文，或稍后重试。
          </p>
        )}
      </div>
    );
  }

  // ---- 已抽到：逐条精读笺 ----
  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          逐条精读
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

      {/* 题署一行：共几条 · 原文核验几条 · 内联术语几个 · 弦外之音几处。朱印描边小签。 */}
      <div className="mt-3 mb-3 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          精读 · {items.length} 条
        </span>
        <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
          原文核验 {verifiedCount}/{items.length}
        </span>
        {termCount > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            内联术语 {termCount} 个
          </span>
        )}
        {nuanceCount > 0 && (
          <span className="text-xs tabular-nums" style={{ color: "var(--color-seal)" }}>
            弦外之音 {nuanceCount} 处
          </span>
        )}
        {/* 整合 round2 A：跳去公文结构看整份骨架 + 分量（鸟瞰 vs 这里逐条钻）。 */}
        {onJumpToStructure && (
          <button
            type="button"
            onClick={onJumpToStructure}
            className="ml-auto text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
          >
            看整份骨架与分量 →
          </button>
        )}
      </div>

      {/* 精读笺：一条 = 一张卡。大白话主体（墨）+ 结构标签（朱签）+ 术语角标 + 对原文（折叠）。 */}
      <div className="space-y-4">
        {items.map((it, i) => {
          const verified = it.verified && hasText(it.evidence);
          const isOpen = !!openOrigin[i];
          const canOpenOrigin = hasText(it.evidence);
          const ordinal = `第 ${it.chapter ?? i + 1} 条`;
          const sideNote = it.matter;
          const nuances = it.nuance ?? [];
          const st = it.structure;
          const istyle = instructionStyle(st?.instruction_type ?? "");
          const terms = it.glossary ?? [];
          return (
            <article
              key={i}
              className="relative rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] overflow-hidden"
            >
              {/* 左侧朱砂书口线——古籍版心的竖栏，立精读笺的身份 */}
              <span
                aria-hidden
                className="absolute left-0 top-0 bottom-0 w-[3px]"
                style={{ background: "var(--color-seal)", opacity: 0.55 }}
              />

              <div className="pl-4 pr-3 py-3">
                {/* 编次行：朱砂序号 + 事项旁注 + 指令类型彩标（结构标签里最显眼的一项提到行首） */}
                <div className="flex items-baseline gap-2 mb-1.5 flex-wrap">
                  <span
                    className="text-xs tabular-nums shrink-0"
                    style={{
                      color: "var(--color-seal)",
                      fontFamily: "var(--font-display)",
                    }}
                  >
                    {ordinal}
                  </span>
                  {hasText(sideNote) && (
                    <span
                      className="text-xs text-[var(--color-ink-muted)] truncate"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {sideNote}
                    </span>
                  )}
                  {hasText(st?.instruction_type) && (
                    <span
                      className="ml-auto text-xs px-2 py-0.5 rounded-full shrink-0 whitespace-nowrap"
                      style={{ color: istyle.fg, background: istyle.bg }}
                    >
                      {st.instruction_type}
                    </span>
                  )}
                </div>

                {/* 大白话——精读笺主体。纯表态条款(方针/原则)不摆成带鉴印的"翻译"——那是复读;
                    老实标它是方向、淡化呈现,鉴印只留给下面「对原文」(WP-redhead-substance-vs-slogan §3.4)。 */}
                {it.clause_kind === "pure_statement" ? (
                  <p className="text-[13px] leading-relaxed text-[var(--color-ink-muted)] italic">
                    {it.plain}
                  </p>
                ) : (
                  <div className="flex items-start gap-2">
                    {verified && <SealMark size={18} title="原文已核验" />}
                    <p
                      className="text-[15px] leading-7 text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {it.plain || "（这条没翻出大白话）"}
                    </p>
                  </div>
                )}

                {/* 结构标签（朱砂小签）——责任主体 / 时限 / 依据，有才显、空的不占位。
                    指令类型已提到编次行，这里只列另三项硬骨架。 */}
                {(hasText(st?.actor) ||
                  hasText(st?.deadline) ||
                  hasText(st?.basis_ref)) && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-ink-muted)]">
                    {hasText(st?.actor) && (
                      <span>
                        责任主体 ·{" "}
                        <span className="text-[var(--color-ink)]">{st.actor}</span>
                      </span>
                    )}
                    {hasText(st?.deadline) && (
                      <span>
                        时限 ·{" "}
                        <span className="text-[var(--color-ink)]">{st.deadline}</span>
                      </span>
                    )}
                    {hasText(st?.basis_ref) && (
                      <span>
                        依据 ·{" "}
                        <span className="text-[var(--color-ink)]">{st.basis_ref}</span>
                      </span>
                    )}
                  </div>
                )}

                {/* 内联术语角标——这条命中的术语，点词头出释义。朱砂虚框小签，点开降调展开释义。 */}
                {terms.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {terms.map((t, k) => {
                      const tkey = `${i}-${k}`;
                      const topen = !!openTerm[tkey];
                      const hasIntent = hasText(t.policy_intent);
                      return (
                        <div key={k} className="w-full">
                          <button
                            type="button"
                            onClick={() =>
                              setOpenTerm((cur) => ({ ...cur, [tkey]: !cur[tkey] }))
                            }
                            className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full transition-colors"
                            style={{
                              color: "var(--color-seal)",
                              border: "0.5px solid var(--color-seal)",
                              background: topen
                                ? "var(--color-seal-soft)"
                                : "transparent",
                            }}
                            title="点开看这个词的解释"
                          >
                            <span style={{ fontFamily: "var(--font-display)" }}>
                              {t.term}
                            </span>
                            <span className="text-[10px] opacity-70">
                              {topen ? "收" : "释"}
                            </span>
                          </button>
                          {topen && (
                            <div className="mt-1 pl-2 border-l-2 border-[var(--color-seal)]/40">
                              {hasText(t.explanation) && (
                                <p
                                  className="text-[13px] leading-relaxed text-[var(--color-ink)]"
                                  style={{ fontFamily: "var(--font-display)" }}
                                >
                                  {t.explanation}
                                </p>
                              )}
                              {hasText(t.context_meaning) && (
                                <p
                                  className="mt-1 text-[13px] leading-relaxed text-[var(--color-ink)]"
                                  style={{ fontFamily: "var(--font-display)" }}
                                >
                                  <span
                                    className="text-[11px] mr-1.5 align-top whitespace-nowrap"
                                    style={{ color: "var(--color-seal)" }}
                                  >
                                    本文件指
                                  </span>
                                  {t.context_meaning}
                                </p>
                              )}
                              {hasIntent && (
                                <div
                                  className="mt-1.5 rounded px-2 py-1.5"
                                  style={{
                                    border: "1px dashed var(--color-rule)",
                                    background: "var(--color-paper-sunken)",
                                  }}
                                >
                                  <span
                                    className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded text-[var(--color-ink-muted)] whitespace-nowrap mb-1"
                                    style={{
                                      border: "1px dashed var(--color-ink-muted)",
                                      opacity: 0.85,
                                    }}
                                  >
                                    政策意图 · 研判
                                  </span>
                                  <p className="text-[12px] leading-relaxed text-[var(--color-ink-muted)]">
                                    {t.policy_intent}
                                  </p>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* 弦外之音——朱批夹注：命中官腔 marker 才有 */}
                {nuances.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {nuances.map((nu, k) => (
                      <div
                        key={k}
                        className="flex items-start gap-1.5 pl-2 border-l-2 text-xs leading-relaxed"
                        style={{ borderColor: "var(--color-seal)" }}
                      >
                        <span
                          className="shrink-0 font-medium"
                          style={{
                            color: "var(--color-seal)",
                            fontFamily: "var(--font-display)",
                          }}
                          title="弦外之音"
                        >
                          「{nu.marker}」
                        </span>
                        <span className="text-[var(--color-ink-muted)]">
                          {nu.meaning}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {/* 核不过老实标一行，绝不假装翻得有原文撑 */}
                {!verified && (
                  <p className="mt-1.5 text-xs text-[var(--color-ink-muted)] italic">
                    {hasText(it.evidence)
                      ? "未在原文比对命中·仅供参考"
                      : "暂无贴切原文（待核）"}
                  </p>
                )}

                {/* 官话原文——夹注，默认收起。点「对原文」展开，朱砂细规一隔，淡墨小字。 */}
                {canOpenOrigin && (
                  <div className="mt-2.5">
                    <button
                      type="button"
                      onClick={() =>
                        setOpenOrigin((cur) => ({ ...cur, [i]: !cur[i] }))
                      }
                      className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                    >
                      {isOpen ? "收起原文" : "对原文"}
                    </button>
                    {isOpen && (
                      <div className="mt-2">
                        {/* 朱砂细规：官话与白话之间的版心界栏 */}
                        <div
                          aria-hidden
                          className="h-px mb-2"
                          style={{ background: "var(--color-seal)", opacity: 0.3 }}
                        />
                        <p
                          className="text-[13px] leading-relaxed text-[var(--color-ink-muted)]"
                          style={{ fontFamily: "var(--font-display)" }}
                        >
                          <span
                            className="text-[11px] mr-1.5 align-top"
                            style={{ color: "var(--color-seal)" }}
                          >
                            原文
                          </span>
                          {it.evidence}
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>

      {!loading && (
        <RunStats
          trace={trace}
          note={`精读 ${items.length} 条 · 原文核验 ${verifiedCount}${
            termCount > 0 ? ` · 内联术语 ${termCount}` : ""
          }${nuanceCount > 0 ? ` · 弦外之音 ${nuanceCount}` : ""}`}
        />
      )}
    </div>
  );
}
