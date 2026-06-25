// ---------------------------------------------------------------------------
// RedheadGlossary — 名词解释（1.6 红头文件垂直·三炮）
//
// 红头文件满是政策黑话——「证照分离」「负面清单」「放管服」「一业一证」。普通人读到卡住，
// 不知道是啥。这块把一份公文里**外行看不懂的词**挑出来，每个用人话讲清意思，做成一卷
// 「释词笺注」：词头朱砂提行立起（像古籍词条的标目），人话释义紧随其后，原句落在角下当
// 夹注——核得到的原句角上盖「鉴」印。
//
// 跟「大白话翻译」的分工：那个逐条款把整句官话翻成人话（一条 → 一句白话）；这个换个看法，
// 不逐条翻整句，只把散落全文的难词挑出来逐个释义（一个词 → 一条注解）。同一个词全文出现
// 几次只出一条；释义讲的是「这词什么意思」，不是「这句话什么意思」。独有维度 = 笺注（给难
// 词夹注释义）。意象走古籍夹注 / 词条旁批，不是通用词典卡片、不套花鸟山水。
//
// evidence-first（全站一个规矩）：词出现的原句核过的盖「鉴」印；核不过的老实标「未在原文比
// 对命中·仅供参考」、原句退空（不留假原句撑场）。scanned=false 或没挑到难词 → 优雅退场，
// 不画空壳。
//
// 设计语言（数字善本案头）：朱墨双色（朱 = var(--color-seal) 钤印/词头提行/书口线，墨 =
// var(--color-ink) 词头与释义主体，淡墨 = var(--color-ink-muted) 原句夹注）、宋体
// var(--font-display)、留白、古籍克制——不堆古风、无 emoji、不做成通用术语表格。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（对着 redhead_glossary.glossary_from_spine 写） ----

interface GlossaryTerm {
  term: string; // 术语本身（逐字原文写法）
  explanation: string; // 大白话释义
  chapter: number | null; // 这词所在条款/章节序号（核不到原句时为 null）
  evidence: string; // 这词出现的原句（核不过时退空）
  verified: boolean;
  match_score: number;
}

interface GlossaryResponse {
  terms: GlossaryTerm[];
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface RedheadGlossaryProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

function hasText(v: string | null | undefined): boolean {
  return !!v && v.trim().length > 0;
}

export function RedheadGlossary({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadGlossaryProps) {
  const [result, setResult] = useState<GlossaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 默认收起原句夹注，点「见原文」展开——保笺注干净，要看出处再展开
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
      const resp = await fetch("/api/agent/redhead/glossary", {
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
      const data = (await resp.json()) as GlossaryResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const terms = result?.terms ?? [];
  const scanned = !!result && result.scanned;
  const gotSomething = scanned && terms.length > 0;
  const verifiedCount = useMemo(
    () => terms.filter((t) => t.verified && hasText(t.evidence)).length,
    [terms],
  );

  // ---- 未生成：入口卡片 ----
  if (!result) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          名词解释
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          把一份红头文件里普通人看不懂的政策黑话挑出来、用人话讲清——「证照分离」「负面清单」「放管服」「一业一证」这类词，逐个释义。每个做成一条笺注：词头立起，下面是大白话讲解，背后原句核得到的盖「鉴」印。释义只讲这词什么意思，不替你脑补原文没说的。适合党政公文
          / 红头文件。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "逐个挑词释义中（约 1 分钟）…" : "挑出难词释义"}
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
            label="逐个挑词释义"
            hint="整份公文喂进模型分段挑出外行看不懂的术语，再逐个用人话释义——每个都回原句核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没挑到：优雅退场 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        <div className="flex items-center justify-between mb-3">
          <h3
            className="text-base font-bold text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            名词解释
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
          <RunningProcess label="逐个挑词释义" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            没挑出需要解释的难词——这份可能用词都挺常见，或者格式太特殊没读出正文。换一份政策黑话多的公文，或稍后重试。
          </p>
        )}
      </div>
    );
  }

  // ---- 已挑到：释词笺注 ----
  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          名词解释
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

      {/* 题署一行：共几条 · 原句核验几条。朱印描边小签，案头规矩。 */}
      <div className="mb-3 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          笺注 · {terms.length} 条
        </span>
        <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
          原文核验 {verifiedCount}/{terms.length}
        </span>
      </div>

      {/* 释词笺注：一条 = 一词条。词头朱砂提行立起（古籍标目）→ 人话释义 → 原句夹注（默认收）。 */}
      <div className="space-y-4">
        {terms.map((t, i) => {
          const verified = t.verified && hasText(t.evidence);
          const isOpen = !!openOrigin[i];
          const canOpenOrigin = hasText(t.evidence);
          return (
            <article
              key={i}
              className="relative rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] overflow-hidden"
            >
              {/* 左侧朱砂书口线——古籍版心的竖栏，立笺注的身份 */}
              <span
                aria-hidden
                className="absolute left-0 top-0 bottom-0 w-[3px]"
                style={{ background: "var(--color-seal)", opacity: 0.55 }}
              />

              <div className="pl-4 pr-3 py-3">
                {/* 词头：朱砂提行立起的标目 + 章次小签。古籍词条的标目位。 */}
                <div className="flex items-baseline gap-2 mb-1.5 flex-wrap">
                  <span
                    className="text-[17px] font-bold leading-tight"
                    style={{
                      color: "var(--color-seal)",
                      fontFamily: "var(--font-display)",
                    }}
                  >
                    {t.term}
                  </span>
                  {typeof t.chapter === "number" && (
                    <span
                      className="text-xs tabular-nums shrink-0 text-[var(--color-ink-muted)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      第 {t.chapter} 条
                    </span>
                  )}
                </div>

                {/* 人话释义——笺注主体，墨色、宋体、舒朗行距 */}
                <div className="flex items-start gap-2">
                  {verified && <SealMark size={18} title="原文已核验" />}
                  <p
                    className="text-[15px] leading-7 text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {t.explanation || "（这条没给出释义）"}
                  </p>
                </div>

                {/* 核不过老实标一行，绝不假装释义有原句撑 */}
                {!verified && (
                  <p className="mt-1.5 text-xs text-[var(--color-ink-muted)] italic">
                    {canOpenOrigin
                      ? "未在原文比对命中·仅供参考"
                      : "未锚到原文出处·仅供参考"}
                  </p>
                )}

                {/* 原句夹注——默认收起。点「见原文」展开，朱砂细规一隔，淡墨小字。 */}
                {canOpenOrigin && (
                  <div className="mt-2.5">
                    <button
                      type="button"
                      onClick={() =>
                        setOpenOrigin((cur) => ({ ...cur, [i]: !cur[i] }))
                      }
                      className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                    >
                      {isOpen ? "收起原文" : "见原文"}
                    </button>
                    {isOpen && (
                      <div className="mt-2">
                        {/* 朱砂细规：释义与原句之间的版心界栏 */}
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
                          {t.evidence}
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
          note={`笺注 ${terms.length} 条 · 原文核验 ${verifiedCount}`}
        />
      )}
    </div>
  );
}
