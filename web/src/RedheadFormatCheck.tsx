// ---------------------------------------------------------------------------
// RedheadFormatCheck — 规范性自检（1.6 红头文件垂直·发明区一炮）
//
// 点"生成"→ 调 /api/agent/redhead/format-check → 对照 GB/T 9704《党政机关公文格式》
// 逐项过：该有的要素齐没齐、文种对不对。这是四个红头功能里**唯一有国标当标准答案**的——
// 别处要 LLM 临场判，这里是对着规矩比对出来的，所以做成一份「朱笔校勘单」。
//
// 朱批校勘意象（区别于结构解读的"红头版头"、大白话的"官话↔白话译笺"、跟我相关的"身份清单"）：
//   像校对员拿朱笔在原稿边逐项过——
//     齐 → 朱笔一勾"过"（朱钩 ✓），核过的角上盖「鉴」印；
//     缺 → 朱笔标缺（朱叉 ✗，一道朱删线），明说 GB/T 这项该有却没见；
//     存疑 → 朱笔一个问号（朱问 ?），分两种：要么这份本就可不设、要么我们没抽到——
//       老实区分"公文真没有"和"我们没抽到"，绝不把没抽到的武断判成"缺"冤枉一份规范公文。
//   每条带一句"按什么规矩判的"（GB/T 国标点）+ 对应头要素的原文出处。
//
// evidence-first（全站一个规矩）：判"齐"且原文核过的盖「鉴」印；没核上的不盖、老实标。
// 三态是分类不是打分——不画进度条、不报分数，只朱笔勾/叉/问。
// extraction_trustworthy=false（这次整体没抽好）时，顶上挂一句提醒：很多"存疑"是没抽到、
// 不是公文缺，请回原件看——别让用户把我们的抽取问题当成公文不规范。
// scanned=false 或没 checks → 优雅退场，不画空壳。
//
// 设计语言（数字善本案头）：朱墨双色（朱 = var(--color-seal) 校改笔色/钤印，墨 = var(--color-ink)
// 要素名/原文）、宋体 var(--font-display)、留白、古籍克制——不堆古风、无 emoji、不做成通用 checklist。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（对着 redhead_format_check.format_check_from_spine 写，别改后端） ----

interface FormatCheck {
  item: string; // 国标要素名：发文字号 / 文种(是否合法) / 发文机关署名 / 标题 / 成文日期 / 主送机关 / 抄送机关 / 签发人
  status: string; // 封闭集三态：齐 / 缺 / 存疑
  note: string; // 一句话判定理由
  evidence: string; // 对应头要素的逐字原文（可能空）
  verified: boolean; // 这条原文文脉核过没（盖「鉴」印的依据）
  rule_note: string; // 对照的 GB/T 9704 国标点
}

interface FormatCheckSummary {
  ok: number;
  missing: number;
  unsure: number;
  total: number;
  text: string; // "齐 N/T"
  extraction_trustworthy: boolean; // 这次头要素抽取整体可不可信
}

interface FormatCheckResponse {
  checks: FormatCheck[];
  summary: FormatCheckSummary;
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface RedheadFormatCheckProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 三态各配一支朱笔笔色 + 一个校改符号。
//   齐 → 朱钩（核过的公文实务里的"无误"批），木绿沉着（过了就过了，不抢眼）；
//   缺 → 朱叉，朱砂红（最重的笔，明说缺）；
//   存疑 → 朱问号，赭石暖褐（拿不准，留个问号让人回原件）。
// 写死 hex（校改笔色，不跟主题走，跟全站数据色一个规矩），fallback 走墨色避免未知 status 炸掉。
const STATUS_STYLE: Record<
  string,
  { mark: string; fg: string; bg: string; line: string }
> = {
  齐: {
    mark: "✓",
    fg: "#4f7a52",
    bg: "rgba(79, 122, 82, 0.10)",
    line: "rgba(79, 122, 82, 0.55)",
  },
  缺: {
    mark: "✗",
    fg: "#9a3a2e",
    bg: "rgba(154, 58, 46, 0.10)",
    line: "rgba(154, 58, 46, 0.60)",
  },
  存疑: {
    mark: "?",
    fg: "#8a6b3f",
    bg: "rgba(138, 107, 63, 0.12)",
    line: "rgba(138, 107, 63, 0.50)",
  },
};

function statusStyle(status: string): {
  mark: string;
  fg: string;
  bg: string;
  line: string;
} {
  return (
    STATUS_STYLE[status] ?? {
      mark: "·",
      fg: "var(--color-ink-muted)",
      bg: "var(--color-seal-soft)",
      line: "var(--color-rule)",
    }
  );
}

function hasText(v: string): boolean {
  return !!v && v.trim().length > 0;
}

export function RedheadFormatCheck({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadFormatCheckProps) {
  const [result, setResult] = useState<FormatCheckResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 默认收起每条的原文出处 + 国标依据，点开看（保校勘单干净）
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setOpenIdx(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/format-check", {
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
      const data = (await resp.json()) as FormatCheckResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const gotSomething =
    !!result && result.scanned && (result.checks ?? []).length > 0;

  // ---- 未生成：入口卡片 ----
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
          规范性自检
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          对照《党政机关公文格式》（GB/T 9704）逐项过一遍——发文字号、标题、成文日期、发文机关这些该有的要素齐没齐，文种用得对不对。这是有国标当尺子量出来的，不是凭感觉判。抽不到的要素老实区分"公文真没有"和"我们没抽到"，不冤枉一份其实规范的公文。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "对着国标逐项校对中…" : "对照 GB/T 9704 自检"}
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
            label="对照国标逐项校对"
            hint="拿这份公文的头要素，逐项对照 GB/T 9704 看齐没齐、文种对不对。同份公文已读过就秒出。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没东西：优雅退场 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        <div className="flex items-center justify-between mb-3">
          <h3
            className="text-base font-bold text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            规范性自检
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
          <RunningProcess label="对照国标逐项校对" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            没法做规范性自检——这份可能不是规范的红头文件，或者头要素一项都没抽到。换一份规范公文，或稍后重试。
          </p>
        )}
      </div>
    );
  }

  const checks = result.checks ?? [];
  const summary = result.summary;
  const trustworthy = summary?.extraction_trustworthy ?? true;

  // ---- 已抽到：朱笔校勘单 ----
  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          规范性自检
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

      {/* ── 校勘单眉首：一道朱砂细规 + 国标出处 + 齐 N/总 + 朱钩/朱叉/朱问三态计数 ── */}
      <div className="text-center mb-1">
        <p
          className="text-[13px] text-[var(--color-ink-muted)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          对照 GB/T 9704《党政机关公文格式》
        </p>
        <div className="mt-2 flex items-center justify-center gap-2">
          <span className="h-px w-8 bg-[var(--color-seal)] opacity-40" />
          <span className="text-[11px] text-[var(--color-ink-muted)] tabular-nums">
            {summary?.text ?? `齐 ${summary?.ok ?? 0}/${checks.length}`}
          </span>
          <span className="h-px w-8 bg-[var(--color-seal)] opacity-40" />
        </div>
        {/* 三态小计：朱钩 N · 朱叉 M · 朱问 K（各带自己的笔色） */}
        {summary && (
          <div className="mt-2 flex items-center justify-center gap-3 text-[11px] tabular-nums">
            <span style={{ color: STATUS_STYLE["齐"].fg }}>
              ✓ 齐 {summary.ok}
            </span>
            <span style={{ color: STATUS_STYLE["缺"].fg }}>
              ✗ 缺 {summary.missing}
            </span>
            <span style={{ color: STATUS_STYLE["存疑"].fg }}>
              ? 存疑 {summary.unsure}
            </span>
          </div>
        )}
      </div>

      {/* 这次整体没抽好 → 顶上一条朱砂提醒：很多"存疑"是没抽到、不是公文缺 */}
      {!trustworthy && (
        <div
          className="mt-3 mb-1 rounded border-l-2 px-3 py-2 text-[12px] leading-relaxed text-[var(--color-ink)]"
          style={{
            borderColor: "var(--color-seal)",
            background: "var(--color-seal-soft)",
          }}
        >
          这次头要素整体抽到得偏少（可能是扫描件糊了或格式特殊）。下面标"存疑"的多半是我们没抽到、不是这份公文真缺——请回原件对照确认，别据此判它不规范。
        </div>
      )}

      {/* ── 逐条校勘：朱笔勾/叉/问 + 要素名 + 一句判定 ── */}
      <div className="mt-3 space-y-2.5">
        {checks.map((c, i) => {
          const st = statusStyle(c.status);
          const isOpen = openIdx === i;
          const canOpen = hasText(c.evidence) || hasText(c.rule_note);
          const sealable = c.status === "齐" && c.verified && hasText(c.evidence);
          return (
            <div
              key={c.item || i}
              className="relative rounded border border-[var(--color-rule)] bg-white p-3 pl-4"
            >
              {/* 校改领格：卡左侧一道朱笔细脊，颜色跟着三态走（缺最重、齐最沉、存疑居中） */}
              <span
                className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full"
                style={{ background: st.line }}
                aria-hidden="true"
              />
              <div className="flex items-start gap-3">
                {/* 朱笔校改符：圆角小方里一个勾/叉/问，仿校对员朱批落在要素旁 */}
                <span
                  className="inline-flex items-center justify-center shrink-0 select-none"
                  style={{
                    width: "22px",
                    height: "22px",
                    borderRadius: "4px",
                    color: st.fg,
                    background: st.bg,
                    border: `1.5px solid ${st.line}`,
                    fontSize: "13px",
                    lineHeight: 1,
                    fontWeight: 700,
                    transform: "rotate(-5deg)",
                  }}
                  aria-hidden="true"
                  title={c.status}
                >
                  {st.mark}
                </span>

                <div className="flex-1 min-w-0">
                  {/* 要素名 + 三态文字标 + （齐且核过）钤印 */}
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className="text-sm font-bold text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {c.item}
                    </span>
                    <span
                      className="text-[11px] px-1.5 py-0.5 rounded"
                      style={{ color: st.fg, background: st.bg }}
                    >
                      {c.status}
                    </span>
                    {sealable && <SealMark size={16} title="原文已核验" />}
                    {canOpen && (
                      <button
                        type="button"
                        onClick={() =>
                          setOpenIdx((cur) => (cur === i ? null : i))
                        }
                        className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors ml-auto"
                      >
                        {isOpen ? "收起依据" : "看原文 / 国标依据"}
                      </button>
                    )}
                  </div>

                  {/* 一句判定理由（说人话区分"真没有"和"没抽到"） */}
                  <p className="mt-1 text-[13px] leading-relaxed text-[var(--color-ink-muted)]">
                    {c.note}
                  </p>

                  {/* 点开：原文出处 + 国标依据 */}
                  {canOpen && isOpen && (
                    <div className="mt-2 space-y-2">
                      {hasText(c.evidence) && (
                        <div className="flex items-start gap-2">
                          {c.verified ? (
                            <SealMark size={16} title="原文已核验" />
                          ) : (
                            <span className="text-[11px] text-[var(--color-ink-muted)] shrink-0 mt-0.5">
                              未核
                            </span>
                          )}
                          <p
                            className="text-[13px] leading-relaxed text-[var(--color-ink)] border-l-2 pl-3"
                            style={{
                              fontFamily: "var(--font-display)",
                              borderColor: "color-mix(in oklch, var(--color-seal) 40%, transparent)",
                            }}
                          >
                            {c.evidence}
                          </p>
                        </div>
                      )}
                      {hasText(c.rule_note) && (
                        <p className="text-[11px] leading-relaxed text-[var(--color-ink-muted)] italic">
                          按规矩 · {c.rule_note}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {!loading && (
        <RunStats
          trace={trace}
          note={`${summary?.text ?? ""} · 缺 ${summary?.missing ?? 0} · 存疑 ${summary?.unsure ?? 0}`}
        />
      )}
    </div>
  );
}
