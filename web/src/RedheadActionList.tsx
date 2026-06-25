// ---------------------------------------------------------------------------
// RedheadActionList — 办事清单（1.6 红头文件垂直·发明区首炮）
//
// 跟「公文结构解读」共用同一个端点 /api/agent/redhead/doc-structure，但换个看法：
// 不画头要素 + 逐条款的"解读"视图，而是把 clauses 渲染成一份可勾选的办事清单——
// 一份红头文件读完最实际的问题是"我到底要干什么、到几号、凭哪条"，这块就答这个。
//
// 每条 clause = 一行待办：勾选框 + 做什么（matter，主体）+ 指令类型彩标 +
//   一行 meta（谁 / 何时 / 依据，空的不显示不占位）+ 原文（核过盖「鉴」印，核不过标待核）。
// 顶部 4 个汇总卡：指令总数 / 硬要求 / 软倡导 / 有时限。
// 三个筛子（纯前端）：全部 / 只看硬要求 / 只看有时限。
// 排序：硬要求排最前——最有约束力的先看。
//
// evidence-first（全站一个规矩）：核不过的原文老实标"待核·仅供参考"，绝不假装有原文。
// 勾选只是本地阅读态（看到哪了 / 哪条要做），不回写后端、不持久化。
// scanned=false 或没 clauses → 优雅退场（可能是报告 / 批复类，没有可执行指令）。
//
// 数字善本水准的艺术化（1.6·只动视觉不动数据）：借红头公文气质——
//   标题前一道朱砂红头短脊；汇总卡做成"案卷签条"，硬要求那张顶上点一道朱砂脊（最有约束力、
//     先看它）；可勾清单每条像"案牍待办"：左侧朱砂批注线 + 宋体事项 + 钤印原文。
// 克制——朱砂只落在红头脊、案卷签条顶脊、批注线、钤印这几个语义位；instruction_type 彩标
// 颜色一律不动（数据色）。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（跟 RedheadDocStructure 同一份，对着写，别改后端） ----

interface Clause {
  chapter: number;
  matter: string; // 这条要做的事
  instruction_type: string; // 封闭集：硬要求 / 软倡导 / 信息告知 / 依据陈述
  actor: string; // 谁去做（可能空）
  deadline: string; // 期限（可能空）
  basis_ref: string; // 依据的上位文件（可能空）
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface DocStructureResponse {
  head: unknown[]; // 办事清单不用头要素，留着不解析
  clauses: Clause[];
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface RedheadActionListProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 指令类型彩标，跟 RedheadDocStructure 一致（封闭集四标签，纯分类不打分）。
// 硬要求 → 朱砂红；软倡导 → 暖绿；信息告知 → 墨青；依据陈述 → 木褐。
// 写死 hex（数据色不跟主题走），未知标签 fallback 走墨色避免炸掉。
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

// 排序权重：硬要求最前，其余按封闭集顺序，未知排最后。
const TYPE_ORDER: Record<string, number> = {
  硬要求: 0,
  软倡导: 1,
  信息告知: 2,
  依据陈述: 3,
};

function typeRank(type: string): number {
  return TYPE_ORDER[type] ?? 99;
}

function hasText(v: string): boolean {
  return !!v && v.trim().length > 0;
}

type FilterKind = "all" | "hard" | "deadline";

export function RedheadActionList({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadActionListProps) {
  const [result, setResult] = useState<DocStructureResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 本地勾选态：clause 原始下标 → 勾没勾（只是阅读态，不回写后端）
  const [checked, setChecked] = useState<Record<number, boolean>>({});
  const [filter, setFilter] = useState<FilterKind>("all");

  async function load() {
    setLoading(true);
    setError(null);
    setChecked({});
    setFilter("all");
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

  // 排序后的条款（硬要求排前），带上原始下标作为勾选态 key + React key。
  const sorted = useMemo(() => {
    const clauses = result?.clauses ?? [];
    return clauses
      .map((c, idx) => ({ c, idx }))
      .sort((a, b) => typeRank(a.c.instruction_type) - typeRank(b.c.instruction_type));
  }, [result]);

  // 汇总数字：总数 / 硬要求 / 软倡导 / 有时限
  const summary = useMemo(() => {
    const clauses = result?.clauses ?? [];
    return {
      total: clauses.length,
      hard: clauses.filter((c) => c.instruction_type === "硬要求").length,
      soft: clauses.filter((c) => c.instruction_type === "软倡导").length,
      timed: clauses.filter((c) => hasText(c.deadline)).length,
    };
  }, [result]);

  // 按筛子过滤
  const shown = useMemo(() => {
    if (filter === "hard") {
      return sorted.filter((x) => x.c.instruction_type === "硬要求");
    }
    if (filter === "deadline") {
      return sorted.filter((x) => hasText(x.c.deadline));
    }
    return sorted;
  }, [sorted, filter]);

  const scanned = !!result && result.scanned;
  const gotSomething = scanned && (result?.clauses ?? []).length > 0;

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
          办事清单
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          把一份红头文件拆成一张能勾的待办清单——每条说清做什么、谁去做、到几号、凭哪份上位文件，硬要求排最前，每条钉在原文。读完一份公文，照着这张表挨条办就行。适合党政公文 / 红头文件。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读这份公文拆清单中（约 1 分钟）…" : "生成办事清单"}
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
            label="读这份公文拆清单"
            hint="整份公文喂进模型，逐条拆出要办的事——谁去做、到几号、凭哪条，每条回原文核验，约 1 分钟。"
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
            办事清单
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
          <RunningProcess label="读这份公文拆清单" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            没抽到可执行指令，可能这份是报告 / 批复类，本身没有要办的条款，或者格式太特殊。换一份带具体要求的公文，或稍后重试。
          </p>
        )}
      </div>
    );
  }

  const doneCount = shown.filter((x) => checked[x.idx]).length;

  // ---- 已抽到：汇总卡 + 筛子 + 可勾清单 ----
  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          办事清单
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

      {/* ── 汇总卡：四个数字 ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
        <SummaryCard label="指令总数" value={summary.total} />
        <SummaryCard label="硬要求" value={summary.hard} accent="#9a3a2e" />
        <SummaryCard label="软倡导" value={summary.soft} accent="#4f7a52" />
        <SummaryCard label="有时限" value={summary.timed} accent="#8a6b3f" />
      </div>

      {/* ── 筛子 ── */}
      <div className="mb-3 flex items-center gap-2 flex-wrap">
        <FilterTab
          active={filter === "all"}
          onClick={() => setFilter("all")}
          label="全部"
        />
        <FilterTab
          active={filter === "hard"}
          onClick={() => setFilter("hard")}
          label="只看硬要求"
        />
        <FilterTab
          active={filter === "deadline"}
          onClick={() => setFilter("deadline")}
          label="只看有时限"
        />
        <span className="ml-auto text-xs text-[var(--color-ink-muted)] tabular-nums">
          已勾 {doneCount}/{shown.length}
        </span>
      </div>

      {/* ── 可勾清单 ── */}
      {shown.length === 0 ? (
        <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
          这个筛子下没有条款。换「全部」看完整清单。
        </p>
      ) : (
        <div className="space-y-2">
          {shown.map(({ c, idx }) => {
            const st = instructionStyle(c.instruction_type);
            const isDone = !!checked[idx];
            const showOrigin = c.verified && hasText(c.evidence);
            return (
              <div
                key={idx}
                className="relative rounded border border-[var(--color-rule)] bg-white p-3 pl-4"
              >
                {/* 案牍批注线：左侧朱砂细脊（批注领格），核过的深一点、勾掉的淡下去 */}
                <span
                  className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full"
                  style={{
                    background: "var(--color-seal)",
                    opacity: isDone ? 0.12 : showOrigin ? 0.45 : 0.18,
                  }}
                  aria-hidden="true"
                />
                <div className="flex items-start gap-3">
                  {/* 勾选框（本地阅读态） */}
                  <label className="flex items-center pt-0.5 cursor-pointer shrink-0">
                    <input
                      type="checkbox"
                      checked={isDone}
                      onChange={() =>
                        setChecked((cur) => ({ ...cur, [idx]: !cur[idx] }))
                      }
                      className="w-4 h-4 accent-[var(--color-seal)] cursor-pointer"
                    />
                  </label>

                  <div className="flex-1 min-w-0">
                    {/* 标题行：做什么 + 指令类型彩标 */}
                    <div className="flex items-start justify-between gap-2">
                      <p
                        className={[
                          "text-sm font-bold leading-snug",
                          isDone
                            ? "text-[var(--color-ink-muted)] line-through"
                            : "text-[var(--color-ink)]",
                        ].join(" ")}
                      >
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

                    {/* 元信息：谁 / 何时 / 依据——有才显示，空的不占位 */}
                    {(hasText(c.actor) ||
                      hasText(c.deadline) ||
                      hasText(c.basis_ref)) && (
                      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-ink-muted)]">
                        {hasText(c.actor) && (
                          <span>
                            谁 ·{" "}
                            <span className="text-[var(--color-ink)]">
                              {c.actor}
                            </span>
                          </span>
                        )}
                        {hasText(c.deadline) && (
                          <span>
                            何时 ·{" "}
                            <span className="text-[var(--color-ink)]">
                              {c.deadline}
                            </span>
                          </span>
                        )}
                        {hasText(c.basis_ref) && (
                          <span>
                            依据 ·{" "}
                            <span className="text-[var(--color-ink)]">
                              {c.basis_ref}
                            </span>
                          </span>
                        )}
                      </div>
                    )}

                    {/* 原文：核过盖印；核不过老实标待核 */}
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
                        {hasText(c.evidence)
                          ? "待核·仅供参考"
                          : "暂无贴切原文（待核）"}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!loading && (
        <RunStats
          trace={trace}
          note={`指令 ${summary.total} 条 · 硬要求 ${summary.hard} · 有时限 ${summary.timed}`}
        />
      )}
    </div>
  );
}

// 顶部汇总数字卡——做成"案卷签条"：顶上一道极细色脊（accent 那类的标识色）+ 大宋体数字
// + 一行标签。accent 给数字和顶脊同一个色（硬要求朱砂等），没 accent 的总数卡走素墨脊。
function SummaryCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: string;
}) {
  const tint = accent ?? "var(--color-ink-muted)";
  return (
    <div className="relative rounded border border-[var(--color-rule)] bg-white px-3 pt-2.5 pb-2 overflow-hidden">
      {/* 案卷签条顶脊：一道细色脊标识这张卡是哪类（朱砂=硬要求等） */}
      <span
        className="absolute left-0 right-0 top-0 h-[2.5px]"
        style={{ background: tint, opacity: accent ? 0.85 : 0.3 }}
        aria-hidden="true"
      />
      <div
        className="text-xl font-bold tabular-nums leading-none"
        style={{
          color: accent ?? "var(--color-ink)",
          fontFamily: "var(--font-display)",
        }}
      >
        {value}
      </div>
      <div className="mt-1 text-xs text-[var(--color-ink-muted)]">{label}</div>
    </div>
  );
}

// 筛子按钮——选中走朱印描边，未选走普通描边。
function FilterTab({
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
