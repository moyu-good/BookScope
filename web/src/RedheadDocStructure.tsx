// ---------------------------------------------------------------------------
// RedheadDocStructure — 公文结构解读（1.6 红头文件垂直·第一块前端）
//
// 点"生成"→ 调 /api/agent/redhead/doc-structure（整份公文进上下文）→ 拆成两块：
//   头要素 —— 永远 8 条骨架（发文字号 / 文种 / 发文机关 / 主送机关 / 抄送机关 /
//     标题事由 / 成文日期 / 签发人），对照 GB/T 9704 公文格式。抽不到的标"待核"，
//     不藏起来——读者一眼看出这份缺了哪一项。
//   逐条款 —— 按出现顺序排开，每条说清：管的什么事、是硬要求还是软倡导、谁去做、
//     什么期限、依据哪份上位文件，再钉一句原文。
//
// evidence-first（跟全站一个规矩）：原文核验过的盖"鉴"印；没核上的老实标"未在原文
// 比对命中·仅供参考"；抽不到 value 标"待核"，绝不编。
// instruction_type 是封闭集四标签（硬要求 / 软倡导 / 信息告知 / 依据陈述），渲染成
// 带色小标签——它是分类不是打分，所以不画进度条、不报分数。
// scanned=false 或没真东西 → 优雅退场，不画空壳。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（已固定，对着写，别改后端） ----

interface HeadElement {
  field: string; // 8 个之一：发文字号 / 文种 / 发文机关 / 主送机关 / 抄送机关 / 标题事由 / 成文日期 / 签发人
  value: string; // 抽不到为空 → 显示"待核"
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface Clause {
  chapter: number;
  matter: string; // 这条管的事
  instruction_type: string; // 封闭集：硬要求 / 软倡导 / 信息告知 / 依据陈述
  actor: string; // 谁去做（可能空）
  deadline: string; // 期限（可能空）
  basis_ref: string; // 依据的上位文件（可能空）
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface DocStructureResponse {
  head: HeadElement[];
  clauses: Clause[];
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface RedheadDocStructureProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 指令类型 = 封闭集四标签，各配一个克制的色（不是打分，纯分类）。
// 硬要求最有约束力 → 朱砂；软倡导 → 暖绿；信息告知 → 墨青；依据陈述 → 木褐。
// 写死 hex（数据色，不跟主题走），fallback 走墨色避免未知标签炸掉。
const INSTRUCTION_STYLE: Record<string, { fg: string; bg: string }> = {
  硬要求: { fg: "#9a3a2e", bg: "rgba(154, 58, 46, 0.10)" },
  软倡导: { fg: "#4f7a52", bg: "rgba(79, 122, 82, 0.10)" },
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

// 一条头要素是否真有内容（value 非空白才算抽到了）。
function hasValue(v: string): boolean {
  return v.trim().length > 0;
}

export function RedheadDocStructure({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadDocStructureProps) {
  const [result, setResult] = useState<DocStructureResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 头要素里某条点开看原文出处（field → 开/合）
  const [openHead, setOpenHead] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setOpenHead(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/doc-structure", {
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
      const data = (await resp.json()) as DocStructureResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 抽到没：scanned 为真，且头要素有值的或条款里有东西
  const gotSomething =
    !!result &&
    result.scanned &&
    ((result.head ?? []).some((h) => hasValue(h.value)) ||
      (result.clauses ?? []).length > 0);

  // ---- 未生成：入口卡片 ----
  if (!result) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          公文结构解读
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          把一份红头文件拆开看——先列发文字号、发文机关、成文日期这八项头要素，对照公文格式标准看缺没缺；再把正文逐条排开：这条管什么事、是硬要求还是软倡导、谁去做、什么期限、依据哪份上位文件，每条钉在原文。适合党政公文 / 红头文件。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读这份公文出结构中（约 1 分钟）…" : "生成公文结构解读"}
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
            label="读这份公文出结构"
            hint="整份公文喂进模型，先认头要素八项、再逐条拆正文——每一项都回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没抽到：优雅退场，不画空壳 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        <div className="flex items-center justify-between mb-3">
          <h3
            className="text-base font-bold text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            公文结构解读
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
          <RunningProcess label="读这份公文出结构" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            没抽到公文结构——这份可能不是规范的红头文件，或者格式太特殊。换一份规范公文，或稍后重试。
          </p>
        )}
      </div>
    );
  }

  const head = result.head ?? [];
  const clauses = result.clauses ?? [];
  const headFilled = head.filter((h) => hasValue(h.value)).length;
  const clauseVerified = clauses.filter((c) => c.verified && c.evidence).length;

  // ---- 已抽到：头要素清单 + 逐条款 ----
  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          公文结构解读
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

      {/* ── 头要素：八项骨架清单 ── */}
      <div className="mb-2 flex items-center gap-2">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          头要素 · 八项
        </span>
        <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
          抽到 {headFilled}/{head.length || 8}
        </span>
      </div>

      <div className="rounded border border-[var(--color-rule)] bg-white overflow-hidden">
        {head.map((h, i) => {
          const filled = hasValue(h.value);
          const canOpen = filled && !!h.evidence;
          const isOpen = openHead === h.field;
          return (
            <div
              key={h.field || i}
              className="border-b border-[var(--color-rule)] last:border-b-0"
            >
              <div className="flex items-start gap-3 px-3 py-2">
                {/* 左：要素名 */}
                <span
                  className="text-sm text-[var(--color-ink-muted)] shrink-0 w-20"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {h.field}
                </span>
                {/* 右：值 + 核验状态 */}
                <div className="flex-1 min-w-0">
                  {filled ? (
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className="text-sm text-[var(--color-ink)]"
                        style={{ fontFamily: "var(--font-display)" }}
                      >
                        {h.value}
                      </span>
                      {h.verified ? (
                        <SealMark size={17} title="原文已核验" />
                      ) : (
                        <span className="text-[11px] text-[var(--color-ink-muted)]">
                          未在原文比对命中·仅供参考
                        </span>
                      )}
                      {canOpen && (
                        <button
                          type="button"
                          onClick={() =>
                            setOpenHead((cur) =>
                              cur === h.field ? null : h.field,
                            )
                          }
                          className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                        >
                          {isOpen ? "收起原文" : "看原文出处"}
                        </button>
                      )}
                    </div>
                  ) : (
                    <span className="text-sm text-[var(--color-ink-muted)] italic">
                      待核
                    </span>
                  )}
                  {/* 点开的原文出处 */}
                  {canOpen && isOpen && (
                    <p
                      className="mt-1.5 text-[13px] leading-relaxed text-[var(--color-ink)] border-l-2 border-[var(--color-seal)]/40 pl-3"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {h.evidence}
                    </p>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── 逐条款 ── */}
      <div className="mt-5 mb-2 flex items-center gap-2">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          逐条款 · {clauses.length} 条
        </span>
        {clauses.length > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            原文核验 {clauseVerified}/{clauses.length}
          </span>
        )}
      </div>

      {clauses.length === 0 ? (
        <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
          头要素抽到了，但没拆出可逐条列的正文条款——这份正文可能偏叙述、不是分条式公文。
        </p>
      ) : (
        <div className="space-y-3">
          {clauses.map((c, i) => {
            const st = instructionStyle(c.instruction_type);
            const showOrigin = c.verified && !!c.evidence;
            return (
              <div
                key={i}
                className="rounded border border-[var(--color-rule)] bg-white p-3"
              >
                {/* 标题行：序号 + 指令类型标签 */}
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-bold text-[var(--color-ink)] leading-snug">
                    <span className="text-[var(--color-ink-muted)] tabular-nums mr-1.5">
                      {i + 1}.
                    </span>
                    {c.matter || "（这条没给主体事项）"}
                  </p>
                  {c.instruction_type && (
                    <span
                      className="text-xs px-2 py-0.5 rounded-full shrink-0 whitespace-nowrap"
                      style={{ color: st.fg, background: st.bg }}
                    >
                      {c.instruction_type}
                    </span>
                  )}
                </div>

                {/* 元信息：谁去做 / 期限 / 依据——有才显示，空的不占位 */}
                {(c.actor || c.deadline || c.basis_ref) && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-ink-muted)]">
                    {c.actor && (
                      <span>
                        责任主体 ·{" "}
                        <span className="text-[var(--color-ink)]">
                          {c.actor}
                        </span>
                      </span>
                    )}
                    {c.deadline && (
                      <span>
                        期限 ·{" "}
                        <span className="text-[var(--color-ink)]">
                          {c.deadline}
                        </span>
                      </span>
                    )}
                    {c.basis_ref && (
                      <span>
                        依据 ·{" "}
                        <span className="text-[var(--color-ink)]">
                          {c.basis_ref}
                        </span>
                      </span>
                    )}
                  </div>
                )}

                {/* 原文：核验通过且非空才当引文 + 盖印；否则老实标待核 */}
                {showOrigin ? (
                  <div className="mt-2 flex items-start gap-2">
                    <SealMark size={17} title="原文已核验" />
                    <p
                      className="text-[13px] leading-relaxed text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {c.evidence}
                    </p>
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-[var(--color-ink-muted)] italic">
                    {c.evidence
                      ? "未在原文比对命中·仅供参考"
                      : "暂无贴切原文（待核）"}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!loading && (
        <RunStats
          trace={trace}
          note={`头要素 ${headFilled}/${head.length || 8} · 条款 ${clauses.length} 条`}
        />
      )}
    </div>
  );
}
