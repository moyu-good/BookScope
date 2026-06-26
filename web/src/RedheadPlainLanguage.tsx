// ---------------------------------------------------------------------------
// RedheadPlainLanguage — 大白话翻译（1.6 红头文件垂直·二炮 + #22 全文逐句 + 弦外之意）
//
// 公文体官话普通人看不懂。这块把官话翻成人话，做成一卷「官话 ↔ 白话」的对照译笺：摆原
// 公文体（像古籍夹注），一道朱砂细规一隔，醒目墨色摆大白话。白话是对原文的**忠实转述、
// 不是编**——背后那句原文核得到，就在白话角上盖「鉴」印。
//
// 两种看法（一个开关切）：
//   · 逐条款（clauses，默认）：走文脉条款，一条一句白话，要对照分条结构时用。
//   · 全文逐句（fulltext，#22 作者点名）：整份公文按句顺下来，每句一对，一句不落地跟原文走。
//
// 懂刻度（深度）：翻译不止字面通顺——命中措辞刻度（「原则上」有口子、「研究」约等于不办、
// 「逐步」没时间表）就在那条白话下点一行朱批「弦外之音」（后端 nuance 字段，命中才有）。
//
// evidence-first（全站一个规矩）：白话背后原文核过的盖「鉴」印；核不过的老实标「未在原文
// 比对命中·仅供参考」；改写失败的白话退回原文、不假装翻好了。没料 → 优雅退场，不画空壳。
//
// 设计语言（数字善本案头）：朱墨双色（朱 = var(--color-seal) 钤印/细规/朱批，墨 = var(--color-ink)
// 白话主体，淡墨 = var(--color-ink-muted) 官话原文）、宋体 var(--font-display)、留白、古籍
// 克制——不堆古风、无 emoji、不做成通用表格。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（对着 redhead_plain.plain_language_from_spine 写） ----

type PlainMode = "clauses" | "fulltext";

// 弦外之意：命中措辞刻度才有（后端 detect_nuances，可选字段）。
interface Nuance {
  marker: string; // 命中的词，如「原则上」
  meaning: string; // 它的真实含义，如「留了口子……」
}

// clauses 模式条目（逐条款）。
interface ClauseItem {
  chapter: number;
  matter: string; // 原公文体事项（这条管的事，官话）
  plain: string; // 大白话（改写失败时退回原事项）
  evidence: string; // 原条款逐字原文
  verified: boolean;
  match_score: number;
  nuance?: Nuance[]; // 命中措辞刻度才有
}

// fulltext 模式条目（全文逐句）。
interface FulltextItem {
  seq: number; // 第几句（从 1 连续）
  original: string; // 这句逐字原文（官话）
  plain: string; // 这句大白话（顺译失败时退回原文）
  evidence: string; // = original，核验锚
  verified: boolean;
  match_score: number;
  nuance?: Nuance[]; // 命中措辞刻度才有
}

type PlainItem = ClauseItem | FulltextItem;

function isFulltextItem(it: PlainItem): it is FulltextItem {
  return "seq" in it;
}

interface PlainResponse {
  mode?: PlainMode; // 后端回显当前模式（老后端可能没有，默认按 clauses）
  items: PlainItem[];
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface RedheadPlainLanguageProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

function hasText(v: string): boolean {
  return !!v && v.trim().length > 0;
}

export function RedheadPlainLanguage({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadPlainLanguageProps) {
  const [result, setResult] = useState<PlainResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 译法：逐条款（默认）或全文逐句。切换即重出一份。
  const [mode, setMode] = useState<PlainMode>("clauses");
  // 默认收起原文夹注，点开看「官话原话」——保译笺干净，要对照再展开
  const [openOrigin, setOpenOrigin] = useState<Record<number, boolean>>({});

  async function load(runMode: PlainMode) {
    setLoading(true);
    setError(null);
    setOpenOrigin({});
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
        mode: runMode,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/plain-language", {
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
      const data = (await resp.json()) as PlainResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 切到另一种译法：换 mode 并立刻重出（避免显示与开关状态不一致）。
  function switchMode(next: PlainMode) {
    if (next === mode || loading) return;
    setMode(next);
    setResult(null);
    void load(next);
  }

  const items = result?.items ?? [];
  const scanned = !!result && result.scanned;
  const gotSomething = scanned && items.length > 0;
  // 当前展示的实际模式：以后端回显为准，老后端没回显就按请求的 mode。
  const shownMode: PlainMode = result?.mode ?? mode;
  const verifiedCount = useMemo(
    () => items.filter((it) => it.verified && hasText(it.evidence)).length,
    [items],
  );
  const nuanceCount = useMemo(
    () => items.filter((it) => (it.nuance?.length ?? 0) > 0).length,
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
          大白话翻译
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          把一份红头文件的官话翻成人话——「应当于三十日内予以办结」翻成「得在三十天内办完」。做成「官话
          ↔
          白话」对照：摆原文，下面是大白话，背后原文核得到的盖「鉴」印；命中「原则上」「研究」「逐步」这类官腔的，再点一句弦外之音。白话只忠实转述、绝不替你脑补原文没说的。适合党政公文
          / 红头文件。
        </p>
        <ModeToggle mode={mode} onSwitch={setMode} disabled={loading} />
        <button
          type="button"
          onClick={() => load(mode)}
          disabled={loading || !apiKey}
          className="mt-3 text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading
            ? `${modeVerb(mode)}中（约 1 分钟）…`
            : modeVerb(mode)}
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
            label={modeVerb(mode)}
            hint={
              mode === "fulltext"
                ? "整份公文喂进模型，按句一句句翻成人话——分段并发、每句回原文核验，约 1 分钟。"
                : "整份公文喂进模型先拆出条款，再逐条把官话改写成人话——每条都回原文核验，约 1 分钟。"
            }
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
            大白话翻译
          </h3>
          <button
            type="button"
            onClick={() => load(mode)}
            disabled={loading}
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
          >
            {loading ? "重出中…" : "重新生成"}
          </button>
        </div>
        <ModeToggle mode={mode} onSwitch={switchMode} disabled={loading} />
        {loading ? (
          <RunningProcess label={modeVerb(mode)} />
        ) : (
          <p className="mt-3 text-sm text-[var(--color-ink-muted)] leading-relaxed">
            {shownMode === "fulltext"
              ? "这份没顺出可逐句翻的正文——可能正文太短或格式太特殊。换一份规范公文，或换「逐条款」试试。"
              : "没拆出可逐条翻的正文条款——这份可能偏叙述、不是分条式公文，或者格式太特殊。换一份规范公文，或换「全文逐句」试试。"}
          </p>
        )}
      </div>
    );
  }

  // ---- 已抽到：对照译笺 ----
  const unit = shownMode === "fulltext" ? "句" : "条";
  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          大白话翻译
        </h3>
        <button
          type="button"
          onClick={() => load(shownMode)}
          disabled={loading}
          className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "重出中…" : "重新生成"}
        </button>
      </div>

      <ModeToggle mode={mode} onSwitch={switchMode} disabled={loading} />

      {/* 题署一行：共几条/句 · 原文核验几条 · 弦外之音几处。朱印描边小签，案头规矩。 */}
      <div className="mt-3 mb-3 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          译笺 · {items.length} {unit}
        </span>
        <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
          原文核验 {verifiedCount}/{items.length}
        </span>
        {nuanceCount > 0 && (
          <span className="text-xs tabular-nums" style={{ color: "var(--color-seal)" }}>
            弦外之音 {nuanceCount} 处
          </span>
        )}
      </div>

      {/* 译笺：一条 = 一开对照。官话夹注（淡墨小字，默认收）→ 朱砂细规 → 大白话（墨色主体）。 */}
      <div className="space-y-4">
        {items.map((it, i) => {
          const verified = it.verified && hasText(it.evidence);
          const isOpen = !!openOrigin[i];
          const canOpenOrigin = hasText(it.evidence);
          // 编次 + 旁注随模式变：clauses 用「第 N 条 + 事项」，fulltext 用「第 N 句」。
          const fullText = isFulltextItem(it);
          const ordinal = fullText
            ? `第 ${it.seq ?? i + 1} 句`
            : `第 ${it.chapter ?? i + 1} 条`;
          const sideNote = fullText ? "" : it.matter;
          const nuances = it.nuance ?? [];
          return (
            <article
              key={i}
              className="relative rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] overflow-hidden"
            >
              {/* 左侧朱砂书口线——古籍版心的竖栏，立译笺的身份 */}
              <span
                aria-hidden
                className="absolute left-0 top-0 bottom-0 w-[3px]"
                style={{ background: "var(--color-seal)", opacity: 0.55 }}
              />

              <div className="pl-4 pr-3 py-3">
                {/* 编次：朱砂小篆位的序号，案头编次（条款=第N条+事项，逐句=第N句） */}
                <div className="flex items-baseline gap-2 mb-1.5">
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
                </div>

                {/* 大白话——译笺主体，墨色、宋体、舒朗行距，醒目 */}
                <div className="flex items-start gap-2">
                  {verified && <SealMark size={18} title="原文已核验" />}
                  <p
                    className="text-[15px] leading-7 text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {it.plain || "（这条没翻出大白话）"}
                  </p>
                </div>

                {/* 弦外之音——朱批夹注：命中官腔 marker 才有，点这词的真实含义。
                    左侧朱砂细竖线立「批」的身份，淡朱底，与白话主体分层。 */}
                {nuances.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {nuances.map((nu, k) => (
                      <div
                        key={k}
                        className="flex items-start gap-1.5 pl-2 border-l-2 text-xs leading-relaxed"
                        style={{
                          borderColor: "var(--color-seal)",
                        }}
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
                  <p className="mt-1.5 pl-0 text-xs text-[var(--color-ink-muted)] italic">
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
                          style={{
                            background: "var(--color-seal)",
                            opacity: 0.3,
                          }}
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
          note={`译笺 ${items.length} ${unit} · 原文核验 ${verifiedCount}${
            nuanceCount > 0 ? ` · 弦外之音 ${nuanceCount}` : ""
          }`}
        />
      )}
    </div>
  );
}

// 两种译法的动作词（按钮/loading 文案共用）。
function modeVerb(mode: PlainMode): string {
  return mode === "fulltext" ? "全文逐句翻成大白话" : "逐条翻成大白话";
}

// 译法切换：逐条款 ↔ 全文逐句。两段式胶囊，朱选墨弃，案头克制。
function ModeToggle({
  mode,
  onSwitch,
  disabled,
}: {
  mode: PlainMode;
  onSwitch: (next: PlainMode) => void;
  disabled?: boolean;
}) {
  const opts: { key: PlainMode; label: string; hint: string }[] = [
    { key: "clauses", label: "逐条款", hint: "走文脉条款，一条一句白话——对照分条结构" },
    { key: "fulltext", label: "全文逐句", hint: "整份按句顺下来，每句一对，一句不落" },
  ];
  return (
    <div
      className="inline-flex rounded border overflow-hidden"
      style={{ borderColor: "var(--color-rule)" }}
      role="tablist"
      aria-label="译法"
    >
      {opts.map((o) => {
        const active = o.key === mode;
        return (
          <button
            key={o.key}
            type="button"
            role="tab"
            aria-selected={active}
            title={o.hint}
            disabled={disabled}
            onClick={() => onSwitch(o.key)}
            className="text-xs px-3 py-1 transition-colors disabled:opacity-50"
            style={{
              color: active ? "var(--color-paper)" : "var(--color-ink-muted)",
              background: active ? "var(--color-seal)" : "transparent",
              fontFamily: "var(--font-display)",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
