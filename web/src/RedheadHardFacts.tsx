// ---------------------------------------------------------------------------
// RedheadHardFacts — 公文要点提取（1.6 整合 4：原硬信息提取表 + 吸收关键时间轴）
//
// 点"生成"→ 调 /api/agent/redhead/hard-facts（整份公文进上下文）→ 把散落各处的硬信息
// 捞出来聚成一张速查表，按五类分组：时限 / 数字指标 / 适用范围 / 生效废止 / 责任主体。
// 每条说清三件事：value（那个数 / 日期 / 范围 / 主体，要醒目）、context（管的什么事）、
// evidence（钉一句原文）。
//
// 整合 4（设计稿 WP-redhead-consolidation）：吸收原「关键时间轴」——时间类硬事实（时限 /
// 生效废止）就是原时间轴抽的东西，这里加一个「时序视图」切换，把这两类按先后排成一条编年
// 时序（保留时间轴那条线的形态价值）。两个视图共用同一份后端数据，纯前端切换，不多调一次。
//
// 它跟公文结构解读的分工：结构解读是逐条款竖着拆（这条管啥）；要点提取是横切（不管在哪条，
// 只要是要照着办的硬信息就汇到一处），回答"我得记住哪几个数 / 哪几个日子 / 归谁管"。
//
// evidence-first（跟全站一个规矩）：原文核验过的盖"鉴"印；没核上的老实标"未在原文比对
// 命中·仅供参考"；后端绝不编数字 / 日期——抽不到就不抽，value 必有原文撑。
// facts 为空 → 优雅退场，不画空表。
//
// 数字善本水准的艺术化（1.6·只动视觉不动数据）——意象是古籍的"提要 / 纲目"：
//   整份做成一卷"案牍要目"：五类各成一栏，每栏朱砂小标领起（像善本提要的纲目标目，
//     朱书纲、墨书目）；栏内每条硬信息——value 用大宋体当目（读者扫表第一眼抓的就是那个
//     数 / 日期），墨钉领格、context 走小字副行点明管啥，原文引文宋体留白收在末尾。
//   时序视图复用关键时间轴的编年意象：一道竖直朱砂时轴贯穿，时间类硬事实按先后钉在轴上。
//   克制是高级——朱砂只落在纲目标目、value 前的墨钉、钤印这几个语义位，绝不当大色块；
//     栏与栏之间靠留白和一道朱砂细线分隔，不堆边框、不上花鸟山水、不堆古风。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（对着写，别改后端） ----

interface HardFact {
  kind: string; // 五类之一：时限 / 数字指标 / 适用范围 / 生效废止 / 责任主体
  value: string; // 这条硬信息本身（那个数 / 日期 / 范围 / 主体），要醒目
  context: string; // 这条管的什么事 / 出自哪条（可能空）
  evidence: string;
  verified: boolean;
  match_score: number;
  // 1.6.1 约束力层：一个数是有罚则兜底的硬门槛（硬指标），还是「力争 / 参考」的软目标（参考值）。
  // 后端封闭集兜底（缺省退「参考值」），老缓存可能没这两个字段 → 前端兜成可选、缺了不画标。
  binding?: string; // 硬指标 / 参考值
  binding_reason?: string; // 凭哪个词判的（锚原文）
}

interface HardFactsResponse {
  facts: HardFact[];
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface RedheadHardFactsProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 五类纲目的固定展示顺序 + 各自一句"这一类是看啥的"导语（提要纲目的小注）。
// 顺序跟后端 HARD_FACT_KINDS 一致——后端已按这个顺序排好 facts，前端顺着分组即可。
const KIND_ORDER: readonly string[] = [
  "时限",
  "数字指标",
  "适用范围",
  "生效废止",
  "责任主体",
];

const KIND_HINT: Record<string, string> = {
  时限: "要赶的时间点",
  数字指标: "要达到的量化目标",
  适用范围: "管谁、管到哪",
  生效废止: "这份文件的时效起止",
  责任主体: "谁来办、谁牵头",
};

// 时间类硬事实（整合 4：吸收自原关键时间轴）——时序视图只排这两类。
const TIME_KINDS: ReadonlySet<string> = new Set(["时限", "生效废止"]);

// #45 真硬指标 = 时限 + 数字指标 + 生效废止（可钉死的量/时/起止）。适用范围、责任主体是框架
// 泛信息、不算「要点」——全无真硬指标时老实说破这份以方针为主(见 research-notes/007)。
const HARD_INDICATOR_KINDS: ReadonlySet<string> = new Set(["时限", "数字指标", "生效废止"]);

// 两种视图：要目（按五类分栏的速查表）/ 时序（时间类硬事实排成编年线）。
type ViewMode = "table" | "timeline";

// 一条硬信息是否真有值（value 非空白才算抽到了——后端已保证，前端再兜一道）。
function hasValue(v: string): boolean {
  return v.trim().length > 0;
}

// 约束力小签：硬指标（有罚则兜底的硬门槛，朱砂实签提醒分量）vs 参考值（软目标，淡墨虚签）。
// 只在后端给了合法 binding 时画；老缓存没这字段就不画（向后兼容、不误导）。
const BINDING_STYLE: Record<string, { fg: string; bg: string; label: string }> = {
  硬指标: { fg: "#9a3a2e", bg: "rgba(154, 58, 46, 0.10)", label: "硬指标" },
  参考值: { fg: "var(--color-ink-muted)", bg: "var(--color-seal-soft)", label: "参考值" },
};

function bindingStyle(binding?: string) {
  if (!binding) return null;
  return BINDING_STYLE[binding] ?? null;
}

// 按 kind 把 facts 分组，按 KIND_ORDER 排栏，空类不出栏。
function groupByKind(facts: HardFact[]): Array<{ kind: string; items: HardFact[] }> {
  const groups: Array<{ kind: string; items: HardFact[] }> = [];
  for (const kind of KIND_ORDER) {
    const items = facts.filter((f) => f.kind === kind && hasValue(f.value));
    if (items.length > 0) groups.push({ kind, items });
  }
  return groups;
}

export function RedheadHardFacts({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadHardFactsProps) {
  const [result, setResult] = useState<HardFactsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 某条点开看原文出处（用 kind+索引拼 key → 开/合）
  const [openFact, setOpenFact] = useState<string | null>(null);
  // 整合 4：要目（速查表）/ 时序（时间类排成编年线）两视图切换，纯前端。
  const [view, setView] = useState<ViewMode>("table");

  async function load() {
    setLoading(true);
    setError(null);
    setOpenFact(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/hard-facts", {
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
      const data = (await resp.json()) as HardFactsResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 抽到没：scanned 为真，且至少有一条带值的硬信息
  const gotSomething =
    !!result &&
    result.scanned &&
    (result.facts ?? []).some((f) => hasValue(f.value));

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
          要点提取
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          一份红头文件里真正要照着办的硬信息——什么时候前办完、要达多少比例、管哪些单位、哪天生效哪天废止、谁来负责——往往散落在好几条款、好几页里。这功能把它们从全份里捞出来，聚成一张速查表，按五类分好，每条钉在原文。时间类的还能切到「时序视图」按先后排成一条线。适合党政公文 / 红头文件。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读这份公文捞要点中（约 1 分钟）…" : "生成要点提取"}
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
            label="读这份公文捞要点"
            hint="整份公文喂进模型，把时限 / 数字 / 范围 / 起止日 / 责任主体五类硬信息全捞出来，每条都回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没抽到：优雅退场，不画空表 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        <div className="flex items-center justify-between mb-3">
          <h3
            className="text-base font-bold text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            要点提取
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
          <RunningProcess label="读这份公文捞要点" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            没捞到能钉在原文的硬信息——这份可能偏原则倡导、没有具体的时限 / 数字 / 范围 / 起止日，或者不是规范的红头文件。换一份规范公文，或稍后重试。
          </p>
        )}
      </div>
    );
  }

  const facts = result.facts ?? [];
  const groups = groupByKind(facts);
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  const verifiedCount = facts.filter((f) => f.verified && f.evidence).length;
  // #45:真硬指标(时限/数字指标/生效废止)——排除适用范围/责任主体这类泛框架。全无但又抽到了
  // 别的(total>0)= 这份以方针为主、可钉死硬指标稀,老实说破,别让泛信息冒充「要点」。
  const hardIndicatorCount = facts.filter(
    (f) => HARD_INDICATOR_KINDS.has(f.kind) && hasValue(f.value),
  ).length;

  // 整合 4：时间类硬事实（时限 / 生效废止）——时序视图排这些，按后端给的顺序（同类内已保抽取序）。
  const timeFacts = facts.filter((f) => TIME_KINDS.has(f.kind) && hasValue(f.value));
  // 没有时间类硬事实就不给时序视图入口（避免空轴）；当前在时序视图但没料则退回要目。
  const hasTimeline = timeFacts.length > 0;
  const effectiveView: ViewMode =
    view === "timeline" && hasTimeline ? "timeline" : "table";

  // ---- 已抽到：案牍要目纲目表 / 编年时序（整合 4 两视图切换）----
  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          要点提取
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

      {/* #45 硬指标稀：真硬指标(时限/数字/起止)全无、只抽到框架泛信息时,老实说破这份以方针为主
          ——evidence-first 空值三态(确证稀 ≠ 没抽到),别让「适用范围/责任主体」冒充「要点」。 */}
      {hardIndicatorCount === 0 && total > 0 && (
        <p className="mb-3 text-[13px] leading-relaxed rounded border border-[var(--color-rule)] bg-[var(--color-paper)] px-3 py-2 text-[var(--color-ink-muted)]">
          这份没有可钉死的硬指标（办结时限 / 达标比例 / 金额门槛这类）——它以方针部署为主，硬要求本就稀，不是没抽到。下面列的是适用范围、责任主体这类框架信息；要看逐条要求，去「逐条精读」。
        </p>
      )}

      {/* 视图切换：要目（按五类分栏速查）/ 时序（时间类排成编年线）。只有抽到时间类硬事实才给时序入口。 */}
      {hasTimeline && (
        <div className="mb-4 flex items-center gap-2">
          <ViewTab
            active={effectiveView === "table"}
            onClick={() => setView("table")}
            label="要目"
          />
          <ViewTab
            active={effectiveView === "timeline"}
            onClick={() => setView("timeline")}
            label={`时序视图（${timeFacts.length}）`}
          />
        </div>
      )}

      {effectiveView === "timeline" ? (
        <HardFactsTimeline
          facts={timeFacts}
          openFact={openFact}
          setOpenFact={setOpenFact}
        />
      ) : (
        <>

      {/* 要目卷首：一道朱砂细线 + 居中卷题 + 收束短线，仿善本提要的卷端纲目页 */}
      <div className="text-center mb-1">
        <div
          className="h-[2px] rounded-full mx-auto"
          style={{
            background:
              "linear-gradient(90deg, transparent, var(--color-seal), transparent)",
          }}
        />
        <p
          className="mt-2.5 text-sm text-[var(--color-ink)] tracking-[0.3em]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          案牍要目
        </p>
        <div className="mt-1.5 flex items-center justify-center gap-2">
          <span className="h-px w-8 bg-[var(--color-seal)] opacity-40" />
          <span className="text-[11px] text-[var(--color-ink-muted)] tabular-nums">
            硬信息 {total} 条 · 原文核验 {verifiedCount}/{total}
          </span>
          <span className="h-px w-8 bg-[var(--color-seal)] opacity-40" />
        </div>
      </div>

      {/* 五类纲目，逐栏排开 */}
      <div className="mt-5 space-y-6">
        {groups.map((g) => (
          <section key={g.kind}>
            {/* 纲目标目：朱书纲（类名）+ 墨书小注（这一类看啥）+ 条数 */}
            <div className="flex items-baseline gap-2.5 mb-2.5">
              {/* 朱砂纲：类名前一道竖脊领格，类名朱墨重笔 */}
              <span
                className="inline-flex items-center gap-2 shrink-0"
                style={{ fontFamily: "var(--font-display)" }}
              >
                <span
                  className="h-4 w-[3px] rounded-full bg-[var(--color-seal)] opacity-80"
                  aria-hidden="true"
                />
                <span className="text-[15px] font-bold text-[var(--color-seal)]">
                  {g.kind}
                </span>
              </span>
              {KIND_HINT[g.kind] && (
                <span className="text-xs text-[var(--color-ink-muted)]">
                  {KIND_HINT[g.kind]}
                </span>
              )}
              <span className="ml-auto text-xs text-[var(--color-ink-muted)] tabular-nums">
                {g.items.length} 条
              </span>
            </div>

            {/* 栏内每条硬信息：墨钉领格 + value 当目（大宋体醒目）+ context 副行 + 原文 */}
            <ul className="space-y-2.5">
              {g.items.map((f, i) => {
                const factKey = `${g.kind}-${i}`;
                const isOpen = openFact === factKey;
                const canOpen = !!f.evidence;
                const verifiedOrigin = f.verified && !!f.evidence;
                return (
                  <li
                    key={factKey}
                    className="relative pl-4 py-0.5 border-l border-[var(--color-rule)]"
                  >
                    {/* 墨钉：每条目前的领格小钉（朱砂，核过的深一点） */}
                    <span
                      className="absolute left-[-3px] top-2 h-1.5 w-1.5 rounded-full"
                      style={{
                        background: "var(--color-seal)",
                        opacity: verifiedOrigin ? 0.7 : 0.3,
                      }}
                      aria-hidden="true"
                    />
                    {/* value 当目：大宋体，是读者扫表第一眼抓的；核过的角上盖印 */}
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className="text-[15px] font-bold text-[var(--color-ink)] leading-snug"
                        style={{ fontFamily: "var(--font-display)" }}
                      >
                        {f.value}
                      </span>
                      {/* 约束力小签：硬指标 = 有罚则兜底的硬门槛、参考值 = 软目标。鼠标悬停看判据 */}
                      {(() => {
                        const bs = bindingStyle(f.binding);
                        if (!bs) return null;
                        return (
                          <span
                            className="text-[11px] px-1.5 py-0.5 rounded-full shrink-0 whitespace-nowrap"
                            style={{ color: bs.fg, background: bs.bg }}
                            title={f.binding_reason || undefined}
                          >
                            {bs.label}
                          </span>
                        );
                      })()}
                      {verifiedOrigin ? (
                        <SealMark size={16} title="原文已核验" />
                      ) : (
                        <span className="text-[11px] text-[var(--color-ink-muted)]">
                          未在原文比对命中·仅供参考
                        </span>
                      )}
                      {canOpen && (
                        <button
                          type="button"
                          onClick={() =>
                            setOpenFact((cur) =>
                              cur === factKey ? null : factKey,
                            )
                          }
                          className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                        >
                          {isOpen ? "收起原文" : "看原文出处"}
                        </button>
                      )}
                    </div>
                    {/* context 副行：这条管的什么事，小字点明语境 */}
                    {hasValue(f.context) && (
                      <p className="mt-0.5 text-xs text-[var(--color-ink-muted)] leading-relaxed">
                        {f.context}
                      </p>
                    )}
                    {/* 点开的原文出处：宋体引文留白 */}
                    {canOpen && isOpen && (
                      <p
                        className="mt-1.5 text-[13px] leading-relaxed text-[var(--color-ink)] border-l-2 border-[var(--color-seal)]/40 pl-3"
                        style={{ fontFamily: "var(--font-display)" }}
                      >
                        {f.evidence}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
        </>
      )}

      {!loading && (
        <RunStats
          trace={trace}
          note={
            effectiveView === "timeline"
              ? `时序 ${timeFacts.length} 个时间节点`
              : `要点 ${total} 条 · ${groups.length} 类`
          }
        />
      )}
    </div>
  );
}

// ---- 视图切换按钮（要目 / 时序）----
function ViewTab({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-xs px-3 py-1 rounded-full border transition-colors"
      style={
        active
          ? {
              color: "var(--color-seal)",
              borderColor: "var(--color-seal)",
              background: "var(--color-seal-soft)",
            }
          : {
              color: "var(--color-ink-muted)",
              borderColor: "var(--color-rule)",
              background: "white",
            }
      }
    >
      {label}
    </button>
  );
}

// ---- 时序视图（整合 4：吸收自原关键时间轴的编年形态）----
// 把时间类硬事实（时限 / 生效废止）按先后排成一条编年线：一道竖直朱砂时轴贯穿，每个时间点一枚
// 年轮墨钉钉在轴上，左边日晷牌摆「时间」（value）、右边墨字事项（context）+ 约束力签 + 原文。
// 数据复用要点提取那张表，纯前端切换，不多调一次后端。
function HardFactsTimeline({
  facts,
  openFact,
  setOpenFact,
}: {
  facts: HardFact[];
  openFact: string | null;
  setOpenFact: (fn: (cur: string | null) => string | null) => void;
}) {
  const verifiedCount = facts.filter((f) => f.verified && f.evidence).length;
  return (
    <div>
      {/* 题署一行：共几个时间节点 · 原文核验几个 */}
      <div className="mb-4 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          编年 · {facts.length} 个时间节点
        </span>
        <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
          原文核验 {verifiedCount}/{facts.length}
        </span>
      </div>

      {/* 编年时序：一道竖直朱砂时轴贯穿，每个节点一枚年轮墨钉钉在轴上。 */}
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
          {facts.map((f, i) => {
            const verified = f.verified && hasValue(f.evidence);
            const factKey = `tl-${i}`;
            const isOpen = openFact === factKey;
            const canOpen = !!f.evidence;
            const bs = bindingStyle(f.binding);
            return (
              <li key={factKey} className="relative flex items-stretch gap-0">
                {/* 左栏：日晷牌——朱砂描边小牌摆「时间」（value） */}
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
                      className="text-[12.5px] font-bold"
                      style={{ color: "var(--color-seal)" }}
                    >
                      {f.value}
                    </span>
                  </div>
                </div>

                {/* 中栏：年轮墨钉——钉在竖轴上的朱砂圆印 */}
                <div className="w-4 shrink-0 flex flex-col items-center relative">
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
                </div>

                {/* 右栏：事项（context）+ 约束力签 + 原文 */}
                <div className="flex-1 min-w-0 pl-3 pb-1">
                  <div className="flex items-start gap-2 flex-wrap">
                    {verified && <SealMark size={17} title="原文已核验" />}
                    <p
                      className="text-[15px] leading-7 text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {hasValue(f.context) ? f.context : f.value}
                    </p>
                    {/* 约束力签：硬指标（咬人的硬期限）vs 参考值（软目标）。悬停看判据 */}
                    {bs && (
                      <span
                        className="self-center text-[11px] px-1.5 py-0.5 rounded-full shrink-0 whitespace-nowrap"
                        style={{ color: bs.fg, background: bs.bg }}
                        title={f.binding_reason || undefined}
                      >
                        {bs.label}
                      </span>
                    )}
                  </div>

                  {/* 核不过老实标一行，绝不假装这个日期有原文撑 */}
                  {!verified && (
                    <p className="mt-1 text-xs text-[var(--color-ink-muted)] italic">
                      {hasValue(f.evidence)
                        ? "未在原文比对命中·仅供参考"
                        : "暂无贴切原文（待核）"}
                    </p>
                  )}

                  {/* 原文——默认收起，点开看撑这个时间的那句 */}
                  {canOpen && (
                    <div className="mt-1.5">
                      <button
                        type="button"
                        onClick={() =>
                          setOpenFact((cur) =>
                            cur === factKey ? null : factKey,
                          )
                        }
                        className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                      >
                        {isOpen ? "收起原文" : "看原文出处"}
                      </button>
                      {isOpen && (
                        <p
                          className="mt-1.5 text-[13px] leading-relaxed text-[var(--color-ink)] border-l-2 pl-3"
                          style={{
                            borderColor:
                              "color-mix(in oklch, var(--color-seal) 40%, transparent)",
                            fontFamily: "var(--font-display)",
                          }}
                        >
                          {f.evidence}
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
    </div>
  );
}
