// ---------------------------------------------------------------------------
// RedheadLevelConsistency — 上下级一致性（1.6 红头文件垂直·跨文件三炮）
//
// 上面发文定个要求，下面发文照着办——但常有对不上的地方：上面要 30 天办完，下面写成 60 天
// （走样）；上面说「原则上」，下面层层加码变硬指标（加码）；上面定了五项，下面只落实三项
// （漏落实）。一卷宗里上位文件 + 下位文件摆一起，这块把这些对不上的地方挑出来，每条**上下
// 两栏对照**：左边上层级要求、右边下层级落实，中间一枚 deviation 标签说清是哪类不一致，
// 两侧各钉那份文件的原话。一眼看清下面有没有照上面办、哪里走了样。
//
// 意象 = 对照校核 / 朱批勘合（拿两份文牍并排勘对，像古时勘合符契对得上对不上），
//   不套小说的关系对照、不做通用 diff 表：每条冲突一张「勘合卡」，左右两栏分上 / 下层级，
//   各自一枚机关 / 字号小签 + 那条要求 + 原话；中间一道朱砂勘缝线 + deviation 朱批标签
//   （走样 / 加码 / 漏落实，三类各配色）。题署一行说共勘出几处对不上。
//
// evidence-first（全站一个规矩）：每处冲突两侧 snippet 都取各自文脉里已核的原文——任一侧
// 坐实不了的整条后端直接丢（不 cry wolf 喊狼来了）。题材自适应：这卷宗全平级 / 单文件 /
// 层级全未知（没上下级落差）→ scanned=false，这个视图本就该掉；都一致没扫出走样 →
// 空 + scanned=true（老实说「核过了，没发现对不上的」）。
//
// 设计语言（数字善本案头）：朱墨双色、宋体 var(--font-display)、留白克制——不堆古风、
// 无 emoji。两侧原话核得到的各盖一枚「鉴」印。deviation 标签是封闭三类、纯分类不打分。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";
import { DossierHint } from "./RedheadDependencyGraph";

// ---- 后端契约（对着 /api/agent/redhead/level-consistency 写，别改后端） ----

interface ClauseSide {
  doc: string; // 发文字号
  clause: string; // 这条要求（这一侧的）
  snippet: string; // 那份文脉已核原文
  verified: boolean;
}

interface Conflict {
  topic: string; // 这处对不上的是什么事
  detail: string; // 怎么对不上的说明
  deviation: string; // 走样 / 加码 / 漏落实
  upper: ClauseSide; // 上层级要求
  lower: ClauseSide; // 下层级落实
  // 博弈姿态（研判口径，可选）：下位对上位是什么姿态——忠实落实 / 层层加码 / 打折扣 / 创新先行。
  // deviation 看「哪类不一致（核验得出）」，posture 看「下位什么态度（研判）」，各看一面。
  // 后端判不准就没这个字段（FE 据有无决定显不显），上下两栏原话是引发它的对照证据。
  posture?: string | null;
}

interface LevelConsistencyResponse {
  conflicts: Conflict[];
  scanned: boolean;
  trace?: RunTrace;
}

interface RedheadLevelConsistencyProps {
  bookSessionIds: string[];
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// deviation = 封闭三类，各配克制的色（数据语义不跟主题走，写死 hex；未知走墨色兜底）。
// 走样 = 改了味（朱砂）；加码 = 越定越严（木褐）；漏落实 = 没全办（墨青）。纯分类不打分。
const DEVIATION_STYLE: Record<string, { fg: string; bg: string }> = {
  走样: { fg: "#9a3a2e", bg: "rgba(154, 58, 46, 0.10)" },
  加码: { fg: "#8a6b3f", bg: "rgba(138, 107, 63, 0.10)" },
  漏落实: { fg: "#3a6378", bg: "rgba(58, 99, 120, 0.10)" },
};

function deviationStyle(d: string): { fg: string; bg: string } {
  return (
    DEVIATION_STYLE[d] ?? {
      fg: "var(--color-ink-muted)",
      bg: "var(--color-seal-soft)",
    }
  );
}

// 博弈姿态四类各配克制的色（研判维，写死 hex；未知走墨色兜底）。和 deviation 标签分开看：
// deviation 是核验得出的「哪类不一致」，posture 是研判「下位什么态度」。纯分类不打分。
const POSTURE_STYLE: Record<string, { fg: string; bg: string }> = {
  忠实落实: { fg: "#3a6378", bg: "rgba(58, 99, 120, 0.10)" },
  层层加码: { fg: "#8a6b3f", bg: "rgba(138, 107, 63, 0.10)" },
  打折扣: { fg: "#9a3a2e", bg: "rgba(154, 58, 46, 0.10)" },
  创新先行: { fg: "#4f7a52", bg: "rgba(79, 122, 82, 0.10)" },
};

function postureStyle(p: string): { fg: string; bg: string } {
  return (
    POSTURE_STYLE[p] ?? {
      fg: "var(--color-ink-muted)",
      bg: "var(--color-seal-soft)",
    }
  );
}

function hasText(v: string | null | undefined): boolean {
  return !!v && v.trim().length > 0;
}

export function RedheadLevelConsistency({
  bookSessionIds,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadLevelConsistencyProps) {
  const [result, setResult] = useState<LevelConsistencyResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);

  const canRun = bookSessionIds.length >= 2 && !!apiKey;

  async function load() {
    if (bookSessionIds.length < 2) return;
    setLoading(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        book_session_ids: bookSessionIds,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/level-consistency", {
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
      const data = (await resp.json()) as LevelConsistencyResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const conflicts = result?.conflicts ?? [];
  const scanned = !!result && result.scanned;
  // scanned=true 但 conflicts 空 = 核过了没扫出走样（这是好结果，单独一态展示）。
  const cleanPass = scanned && conflicts.length === 0;
  const gotConflicts = scanned && conflicts.length > 0;

  // 各 deviation 计数（题署用）
  const counts = useMemo(() => {
    return {
      走样: conflicts.filter((c) => c.deviation === "走样").length,
      加码: conflicts.filter((c) => c.deviation === "加码").length,
      漏落实: conflicts.filter((c) => c.deviation === "漏落实").length,
    };
  }, [conflicts]);

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
          上下级一致性
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          上面发文定要求、下面发文照着办，常有对不上的地方——上面 30 天下面写成 60 天（走样）、上面「原则上」下面层层加码变硬指标（加码）、上面定五项下面只办三项（漏落实）。这块把上位文件和下位文件并排勘对，把对不上的挑出来，每处上下两栏对照、各钉原话。一眼看清下面有没有照上面办。需要卷宗里有明确上下级关系的公文（上位规定 + 下位实施件）。
        </p>
        <DossierHint count={bookSessionIds.length} />
        <button
          type="button"
          onClick={load}
          disabled={loading || !canRun}
          className="mt-3 text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "并排勘对上下级中（约 1-2 分钟）…" : "勘对上下级一致性"}
        </button>
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {loading && (
          <RunningProcess
            label="并排勘对上下级"
            hint="卷宗里每份公文各建文脉，按机关层级分出上下级，再逐条勘对要求对不对得上——两侧原话都核得到才算数，约 1-2 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- scanned=false：题材自适应该掉（全平级 / 单文件 / 层级未知） ----
  if (!scanned) {
    return (
      <div className="pt-4">
        <ViewHeader title="上下级一致性" loading={loading} onReload={load} />
        {loading ? (
          <RunningProcess label="并排勘对上下级" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            这卷宗里没有上下级落差可勘——可能这几份公文是平级的、或者只有一份、或者认不出谁管谁。这个视图只对「上位规定 + 下位实施件」这种有层级的卷宗有用。换一组有明确上下级关系的公文再试。
          </p>
        )}
      </div>
    );
  }

  // ---- scanned=true 但没冲突：核过了没发现走样（好结果，正面陈述） ----
  if (cleanPass) {
    return (
      <div className="pt-4">
        <ViewHeader title="上下级一致性" loading={loading} onReload={load} />
        <div className="rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-4 flex items-start gap-3">
          <SealMark size={22} title="勘对通过" />
          <div>
            <p
              className="text-sm font-bold text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              勘对通过——没发现对不上的地方
            </p>
            <p className="mt-1 text-sm text-[var(--color-ink-muted)] leading-relaxed">
              逐条勘对了上下级要求，下位文件该落实的都对得上，没扫出走样 / 加码 / 漏落实。
            </p>
          </div>
        </div>
        {!loading && <RunStats trace={trace} note="勘对通过 · 0 处对不上" />}
      </div>
    );
  }

  // ---- 勘出冲突：勘合卡列表 ----
  if (!gotConflicts) return null; // 理论到不了，类型收口

  return (
    <div className="pt-4">
      <ViewHeader title="上下级一致性" loading={loading} onReload={load} />

      {/* 题署：勘出几处 · 各类几处 */}
      <div className="mb-4 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{ color: "var(--color-seal)", border: "0.5px solid var(--color-seal)" }}
        >
          勘合 · 勘出 {conflicts.length} 处对不上
        </span>
        {(["走样", "加码", "漏落实"] as const).map((k) =>
          counts[k] > 0 ? (
            <span
              key={k}
              className="text-xs px-2 py-0.5 rounded-full"
              style={{ color: deviationStyle(k).fg, background: deviationStyle(k).bg }}
            >
              {k} {counts[k]}
            </span>
          ) : null,
        )}
      </div>

      {/* ── 勘合卡：每处冲突一张，左右两栏分上 / 下层级 ── */}
      <div className="space-y-4">
        {conflicts.map((c, i) => (
          <ConflictCard key={i} conflict={c} />
        ))}
      </div>

      {!loading && (
        <RunStats trace={trace} note={`勘出 ${conflicts.length} 处对不上`} />
      )}
    </div>
  );
}

// 一张勘合卡：顶部 topic + deviation 朱批标签；下面左右两栏（上层级 / 下层级）+ 中间勘缝线。
function ConflictCard({ conflict }: { conflict: Conflict }) {
  const st = deviationStyle(conflict.deviation);
  return (
    <div className="rounded border border-[var(--color-rule)] bg-white overflow-hidden">
      {/* 卡头：这处对不上的是什么事 + deviation 标签 */}
      <div className="px-3.5 py-2.5 border-b border-[var(--color-rule)] flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p
            className="text-sm font-bold text-[var(--color-ink)] leading-snug"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {hasText(conflict.topic) ? conflict.topic : "（这处没说是什么事）"}
          </p>
          {hasText(conflict.detail) && (
            <p className="mt-1 text-xs text-[var(--color-ink-muted)] leading-relaxed">
              {conflict.detail}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {/* 博弈姿态小标（研判口径，区别于 deviation 这个核验得出的分类） */}
          {hasText(conflict.posture) && (
            <span
              className="text-xs px-2 py-0.5 rounded-full whitespace-nowrap inline-flex items-center gap-1"
              style={{
                color: postureStyle(conflict.posture ?? "").fg,
                background: postureStyle(conflict.posture ?? "").bg,
              }}
              title="博弈姿态：下位对上位的态度（研判，非核验事实）"
            >
              <span className="opacity-70">研判</span>
              {conflict.posture}
            </span>
          )}
          {hasText(conflict.deviation) && (
            <span
              className="text-xs px-2 py-0.5 rounded-full whitespace-nowrap"
              style={{ color: st.fg, background: st.bg }}
            >
              {conflict.deviation}
            </span>
          )}
        </div>
      </div>

      {/* 两栏对照：上层级 / 下层级。中间一道朱砂勘缝线（手机端竖排，宽屏左右）。 */}
      <div className="relative grid grid-cols-1 md:grid-cols-2">
        {/* 勘缝线：宽屏时竖在两栏中缝，朱砂细线（像符契对缝） */}
        <span
          aria-hidden
          className="hidden md:block absolute top-3 bottom-3 left-1/2 w-px"
          style={{ background: "var(--color-seal)", opacity: 0.3 }}
        />
        <SidePane
          rank="上层级"
          side={conflict.upper}
          accent={st.fg}
        />
        <div className="border-t md:border-t-0 border-[var(--color-rule)]">
          <SidePane rank="下层级" side={conflict.lower} accent={st.fg} />
        </div>
      </div>
    </div>
  );
}

// 一栏：层级签 + 字号 + 这条要求 + 那份文件原话（核得到盖印）。
function SidePane({
  rank,
  side,
  accent,
}: {
  rank: "上层级" | "下层级";
  side: ClauseSide;
  accent: string;
}) {
  const verified = side.verified && hasText(side.snippet);
  return (
    <div className="p-3.5">
      {/* 层级签 + 发文字号 */}
      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
        <span
          className="text-[11px] px-1.5 py-0.5 rounded"
          style={{
            color: accent,
            border: `0.5px solid ${accent}`,
            fontFamily: "var(--font-display)",
          }}
        >
          {rank}
        </span>
        {hasText(side.doc) && (
          <span
            className="text-xs text-[var(--color-ink-muted)] tabular-nums break-all"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {side.doc}
          </span>
        )}
      </div>

      {/* 这条要求 */}
      <p
        className="text-sm text-[var(--color-ink)] leading-relaxed"
        style={{ fontFamily: "var(--font-display)" }}
      >
        {hasText(side.clause) ? side.clause : "（这一侧没给具体要求）"}
      </p>

      {/* 原话：核得到盖印；核不过老实标待核 */}
      {verified ? (
        <div className="mt-2 flex items-start gap-2">
          <SealMark size={16} title="原文已核验" />
          <p
            className="text-[12.5px] leading-relaxed text-[var(--color-ink-muted)] border-l-2 pl-2.5"
            style={{
              borderColor: "color-mix(in oklch, var(--color-seal) 35%, transparent)",
              fontFamily: "var(--font-display)",
            }}
          >
            {side.snippet}
          </p>
        </div>
      ) : (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)] italic">
          {hasText(side.snippet)
            ? "未在原文比对命中·仅供参考"
            : "暂无贴切原文（待核）"}
        </p>
      )}
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
