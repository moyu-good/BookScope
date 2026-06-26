// ---------------------------------------------------------------------------
// RedheadStakes — 利害与风向（1.6.1 红头文件垂直·机会/风险/信号 + 含金量 + 建议）
//
// 读公文的真正用事不是"读懂字面"（那是大白话干的活），是"知道这份文件对我藏着什么
// 机会、什么风险、透出什么风向"。用户报上身份（个体户 / 投资人 / 某市场监管局 …），
// 这块按身份研判三段——同一份公文，个体户看到的和投资人看到的是两份不同的利害账。
//
// 三段三种证据契约（1.6.1 evidence-first 升级，这是命门）：
//   建议（recommendation）—— 系统一句话 take，带立场、轻重缓急。放最显眼，做成"批语 /
//     判语"气质（朱砂判语框），不是普通段落——这是先生替你下的总批。
//   机会 / 风险 —— 证据层：每条锚原文、过核验、核过的盖「鉴」印。右上挂含金量徽章
//     （真金白银 / 有条件兑现 / 空头倡导），视觉权重跟着含金量走——真金白银朱红重、
//     空头倡导灰弱降调，一眼看出哪条值钱。带 horizon（近 / 远 / 无期）小标。
//   信号 —— 评估层：结论是推断，**绝不盖鉴印**（鉴印 = 核验过的事实，信号不配）。
//     视觉必须和机会/风险区隔开——虚线框 + 降调底 + 「研判·非核验」标，显方向 +
//     置信度（高 / 中 / 低）+ basis（引发它的原文片段，可展开）。
//
// 含金量按钱学森开环/闭环判（后端读原文的承诺强度算好排好序，前端照序渲染）：
//   闭环（指令 + 主体 + 时限 + 考核罚则）= 真金白银，会兑现；
//   开环（纯号召）= 空头，自然漂没。判据全在原文里可读，所以仍 evidence-grounded。
//
// 设计语言（数字善本案头）：朱墨双色（朱 = var(--color-seal)，墨 = var(--color-ink)，
// 淡墨 = var(--color-ink-muted)）、宋体 var(--font-display)、留白、古籍克制——不堆
// 古风、无 emoji。复用 SealMark（钤印）/ RunningProcess / RunStats，不引新依赖。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（对着 RedheadStakesResponse 写，别改后端） ----

// 含金量：真金白银（闭环·会兑现）/ 有条件兑现（半开环）/ 空头倡导（开环·必漂）。
type Substance = "真金白银" | "有条件兑现" | "空头倡导";
// 时效：近 / 远 / 无期（开环号召可能"十年后"或永不）。
type Horizon = "近" | "远" | "无期";
// 信号置信度（评估层专用，绝不是核验态）。
type Confidence = "高" | "中" | "低";

interface Opportunity {
  what: string; // 机会本身
  why: string; // 对这角色为何是机会
  action: string; // 可采取的动作
  substance: Substance;
  substance_reason: string; // 凭哪些 marker 判的（锚原文）
  horizon: Horizon;
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface Risk {
  what: string; // 风险本身
  cost: string; // 代价 / 后果
  substance: Substance;
  substance_reason: string;
  horizon: Horizon;
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface Signal {
  direction: string; // 研判出的政策方向
  basis: string[]; // 引发它的原文片段（一条都不能没有——后端已守）
  confidence: Confidence;
}

interface StakesResponse {
  role: string; // 回显身份
  opportunities: Opportunity[];
  risks: Risk[];
  signals: Signal[];
  recommendation: string; // 系统一句话 take（带立场）
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface RedheadStakesProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 常见身份预设——一点就填进输入框，省得用户自己想怎么描述。
const ROLE_PRESETS: readonly string[] = [
  "个体工商户",
  "一家小微企业",
  "投资人",
  "某市场监管局",
  "行业从业者",
];

// ---- 含金量徽章样式：视觉权重跟着含金量走 ----
// 真金白银 = 朱红重（突出，值钱）；有条件兑现 = 中性墨；空头倡导 = 灰弱降调。
// 写死语义色（含金量是评级语义不是主题色），fallback 走墨色避免未知值炸掉。
interface SubstanceStyle {
  fg: string; // 徽章字色
  bg: string; // 徽章底
  border: string; // 徽章描边
  cardOpacity: number; // 整条卡片不透明度——空头降调
  cardBorder: string; // 卡左脊色（值钱的朱砂重，空头淡）
  cardBorderOpacity: number;
  weight: number; // 徽章字重
}

const SUBSTANCE_STYLE: Record<Substance, SubstanceStyle> = {
  真金白银: {
    fg: "#9a3a2e",
    bg: "rgba(154, 58, 46, 0.12)",
    border: "rgba(154, 58, 46, 0.55)",
    cardOpacity: 1,
    cardBorder: "var(--color-seal)",
    cardBorderOpacity: 0.65,
    weight: 700,
  },
  有条件兑现: {
    fg: "var(--color-ink)",
    bg: "rgba(58, 99, 120, 0.08)",
    border: "rgba(58, 99, 120, 0.35)",
    cardOpacity: 1,
    cardBorder: "var(--color-ink-muted)",
    cardBorderOpacity: 0.4,
    weight: 600,
  },
  空头倡导: {
    fg: "var(--color-ink-muted)",
    bg: "rgba(0, 0, 0, 0.03)",
    border: "var(--color-rule)",
    cardOpacity: 0.72, // 降调——一眼看出别太当真
    cardBorder: "var(--color-rule)",
    cardBorderOpacity: 1,
    weight: 500,
  },
};

function substanceStyle(s: string): SubstanceStyle {
  return (
    SUBSTANCE_STYLE[s as Substance] ?? {
      fg: "var(--color-ink-muted)",
      bg: "var(--color-seal-soft)",
      border: "var(--color-rule)",
      cardOpacity: 1,
      cardBorder: "var(--color-ink-muted)",
      cardBorderOpacity: 0.3,
      weight: 500,
    }
  );
}

// 含金量一句注脚（徽章 hover / 旁注，点破闭环 vs 开环）。
const SUBSTANCE_HINT: Record<Substance, string> = {
  真金白银: "有指令、主体、时限、考核——会兑现",
  有条件兑现: "满足条件才落地，看后续配套",
  空头倡导: "只发号召、无问责，多半漂没",
};

// 时效小标的注脚。
const HORIZON_HINT: Record<Horizon, string> = {
  近: "近期",
  远: "远期",
  无期: "无明确时限",
};

// 置信度徽章样式（评估层专用——刻意不用朱砂，免得跟核验态撞色误导）。
const CONFIDENCE_STYLE: Record<Confidence, { fg: string; bg: string }> = {
  高: { fg: "#3a6378", bg: "rgba(58, 99, 120, 0.12)" },
  中: { fg: "#8a6b3f", bg: "rgba(138, 107, 63, 0.12)" },
  低: { fg: "var(--color-ink-muted)", bg: "rgba(0, 0, 0, 0.04)" },
};

function confidenceStyle(c: string): { fg: string; bg: string } {
  return (
    CONFIDENCE_STYLE[c as Confidence] ?? {
      fg: "var(--color-ink-muted)",
      bg: "rgba(0, 0, 0, 0.04)",
    }
  );
}

function hasText(v: string | undefined): boolean {
  return !!v && v.trim().length > 0;
}

// 含金量徽章——评级语义的视觉权重。真金白银描重、空头描淡。
function SubstanceBadge({ substance }: { substance: string }) {
  const st = substanceStyle(substance);
  return (
    <span
      className="inline-flex items-center text-[11px] px-2 py-0.5 rounded-full whitespace-nowrap shrink-0"
      title={SUBSTANCE_HINT[substance as Substance] ?? ""}
      style={{
        color: st.fg,
        background: st.bg,
        border: `0.5px solid ${st.border}`,
        fontWeight: st.weight,
        fontFamily: "var(--font-display)",
      }}
    >
      {substance}
    </span>
  );
}

// 时效小标——含金量旁一枚素净的期次标（不抢含金量的视觉权重）。
function HorizonTag({ horizon }: { horizon: string }) {
  if (!hasText(horizon)) return null;
  return (
    <span
      className="text-[10px] text-[var(--color-ink-muted)] whitespace-nowrap"
      title={HORIZON_HINT[horizon as Horizon] ?? ""}
    >
      {horizon}期
    </span>
  );
}

export function RedheadStakes({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadStakesProps) {
  const [role, setRole] = useState("");
  const [result, setResult] = useState<StakesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 机会/风险逐条点「看原文出处」展开 evidence（键 = "o3" / "r1"），保卡片清爽
  const [openEvidence, setOpenEvidence] = useState<Record<string, boolean>>({});
  // 信号逐条点「看原文基础」展开 basis（键 = 信号下标）
  const [openBasis, setOpenBasis] = useState<Record<number, boolean>>({});

  const roleTrimmed = role.trim();

  async function load() {
    if (!roleTrimmed) return;
    setLoading(true);
    setError(null);
    setOpenEvidence({});
    setOpenBasis({});
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
        role: roleTrimmed,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/stakes", {
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
      const data = (await resp.json()) as StakesResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const opportunities = result?.opportunities ?? [];
  const risks = result?.risks ?? [];
  const signals = result?.signals ?? [];
  const scanned = !!result && result.scanned;
  const gotSomething =
    scanned &&
    (opportunities.length > 0 ||
      risks.length > 0 ||
      signals.length > 0 ||
      hasText(result?.recommendation));

  const verifiedCount = useMemo(
    () =>
      [...opportunities, ...risks].filter(
        (it) => it.verified && hasText(it.evidence),
      ).length,
    [opportunities, risks],
  );
  const evidenceTotal = opportunities.length + risks.length;
  const realMoneyCount = useMemo(
    () =>
      [...opportunities, ...risks].filter((it) => it.substance === "真金白银")
        .length,
    [opportunities, risks],
  );

  // ---- 身份输入区（永远在顶上，换身份重判一遍） ----
  const identityBar = (
    <div className="mb-4">
      <label
        className="block text-sm font-bold text-[var(--color-ink)] mb-1.5"
        style={{ fontFamily: "var(--font-display)" }}
      >
        你是谁？
      </label>
      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        报上你的身份——同一份公文，个体户的机会和投资人看到的风向不是一回事。
      </p>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        {ROLE_PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            onClick={() => setRole(preset)}
            disabled={loading}
            className={`text-xs px-2.5 py-1 rounded-full border transition-colors disabled:opacity-50 ${
              roleTrimmed === preset
                ? "border-[var(--color-seal)] text-[var(--color-seal)]"
                : "border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:border-[var(--color-seal)] hover:text-[var(--color-seal)]"
            }`}
          >
            {preset}
          </button>
        ))}
      </div>
      <div className="flex items-stretch gap-2">
        <input
          type="text"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && roleTrimmed && !loading && apiKey) load();
          }}
          placeholder="也可以自己写，比如「一家做餐饮的小公司」"
          disabled={loading}
          className="flex-1 text-sm px-3 py-2 rounded border border-[var(--color-rule)] bg-white text-[var(--color-ink)] placeholder:text-[var(--color-ink-muted)] focus:outline-none focus:border-[var(--color-seal)] disabled:opacity-50"
          style={{ fontFamily: "var(--font-display)" }}
        />
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey || !roleTrimmed}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors whitespace-nowrap"
        >
          {loading ? "研判中…" : "判利害与风向"}
        </button>
      </div>
      {error && (
        <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}
      {!apiKey && (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
          填了 API key 才能生成。
        </p>
      )}
    </div>
  );

  // ---- 标题行 ----
  const header = (
    <h3
      className="text-base font-bold text-[var(--color-ink)] mb-1 flex items-center gap-2"
      style={{ fontFamily: "var(--font-display)" }}
    >
      {/* 红头点缀：标题前一道朱砂短脊，预告这是红头公文视图 */}
      <span
        className="h-4 w-[3px] rounded-full bg-[var(--color-seal)]"
        aria-hidden="true"
      />
      利害与风向
    </h3>
  );

  // ---- 未生成：入口 + 身份输入 ----
  if (!result) {
    return (
      <div className="pt-4">
        {header}
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          读公文真正想知道的不是字面意思，是「这份文件对我藏着什么机会、什么风险、透出什么风向」。报上你的身份，按身份给你判三段：能争取的<b>机会</b>、要当心的<b>风险</b>（都锚原文、评含金量——真金白银还是空头倡导），外加弦外之音的<b>信号</b>（标研判、不冒充事实），最后给一句带立场的建议。适合党政公文
          / 红头文件。
        </p>
        {identityBar}
        {loading && (
          <RunningProcess
            label="替你研判利害与风向"
            hint="整份公文 + 你的身份喂进模型，研判机会 / 风险 / 信号，并按原文里的承诺强度评含金量——机会 / 风险回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没研判出：优雅退场 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        {header}
        {identityBar}
        {loading ? (
          <RunningProcess label="替你研判利害与风向" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            {scanned
              ? `这份公文没研判出明显冲「${result.role}」来的机会 / 风险 / 风向——可能它不直接管到你这类身份，或者偏叙述、没有分条式的实质内容。换个身份再判一遍，或换一份公文。`
              : "没读出可研判的实质内容——这份可能不是党政公文 / 红头文件，或格式太特殊。换一份规范公文，或稍后重试。"}
          </p>
        )}
      </div>
    );
  }

  // ---- 已研判出：建议（判语）+ 机会/风险（证据层）+ 信号（评估层） ----
  return (
    <div className="pt-4">
      {header}
      {identityBar}

      {/* 题署一行：替「身份」判出几机会几风险 · 真金白银几条 · 原文核验几条 */}
      <div className="mb-3 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          替「{result.role}」研判
        </span>
        {opportunities.length > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            机会 {opportunities.length}
          </span>
        )}
        {risks.length > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            风险 {risks.length}
          </span>
        )}
        {signals.length > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            信号 {signals.length}
          </span>
        )}
        {realMoneyCount > 0 && (
          <span
            className="text-xs tabular-nums"
            style={{ color: "#9a3a2e" }}
          >
            真金白银 {realMoneyCount}
          </span>
        )}
        {evidenceTotal > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            原文核验 {verifiedCount}/{evidenceTotal}
          </span>
        )}
      </div>

      {/* ── 建议（recommendation）：先生的总批，做成朱砂判语框，最显眼 ── */}
      {hasText(result.recommendation) && (
        <div
          className="relative mb-6 rounded-r px-4 py-3.5 pl-5"
          style={{
            background: "var(--color-seal-soft)",
            borderLeft: "3px solid var(--color-seal)",
          }}
        >
          {/* 判语签：右上一枚朱砂「判」字签，点破这是带立场的总批不是中立罗列 */}
          <span
            className="absolute -top-2.5 left-4 inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-bold rounded"
            style={{
              color: "var(--color-paper)",
              background: "var(--color-seal)",
              fontFamily: "var(--font-display)",
              transform: "rotate(-1.5deg)",
            }}
          >
            判语 · 一句话建议
          </span>
          <p
            className="text-[15px] leading-7 text-[var(--color-ink)] mt-1"
            style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
          >
            {result.recommendation}
          </p>
        </div>
      )}

      {/* ── 机会（证据层）── */}
      {opportunities.length > 0 && (
        <section className="mb-6">
          <SectionHead
            title="机会"
            sub="可争取的红利"
            count={opportunities.length}
          />
          <div className="space-y-3">
            {opportunities.map((o, i) => (
              <StakeCard
                key={`o${i}`}
                kind="opp"
                what={o.what}
                detailLabel="为何是机会"
                detail={o.why}
                action={o.action}
                substance={o.substance}
                substanceReason={o.substance_reason}
                horizon={o.horizon}
                evidence={o.evidence}
                verified={o.verified}
                open={!!openEvidence[`o${i}`]}
                onToggle={() =>
                  setOpenEvidence((cur) => ({
                    ...cur,
                    [`o${i}`]: !cur[`o${i}`],
                  }))
                }
              />
            ))}
          </div>
        </section>
      )}

      {/* ── 风险（证据层）── */}
      {risks.length > 0 && (
        <section className="mb-6">
          <SectionHead title="风险" sub="暴露面 / 代价" count={risks.length} />
          <div className="space-y-3">
            {risks.map((r, i) => (
              <StakeCard
                key={`r${i}`}
                kind="risk"
                what={r.what}
                detailLabel="代价 / 后果"
                detail={r.cost}
                substance={r.substance}
                substanceReason={r.substance_reason}
                horizon={r.horizon}
                evidence={r.evidence}
                verified={r.verified}
                open={!!openEvidence[`r${i}`]}
                onToggle={() =>
                  setOpenEvidence((cur) => ({
                    ...cur,
                    [`r${i}`]: !cur[`r${i}`],
                  }))
                }
              />
            ))}
          </div>
        </section>
      )}

      {/* ── 信号（评估层）：视觉必须和证据层区隔——虚线框 + 降调底 + 研判标，绝不盖鉴印 ── */}
      {signals.length > 0 && (
        <section className="mb-2">
          {/* 区隔分界：一道虚线 + 「以下是研判，非核验事实」的明说 */}
          <div className="flex items-center gap-2.5 mb-1">
            <span className="h-3.5 w-[3px] rounded-full bg-[var(--color-ink-muted)] opacity-60" />
            <span
              className="text-sm font-bold text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              信号
            </span>
            <span className="text-xs text-[var(--color-ink-muted)]">
              弦外之音 / 政策风向
            </span>
            <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
              {signals.length}
            </span>
          </div>
          <p className="text-xs text-[var(--color-ink-muted)] mb-3 leading-relaxed">
            以下是<b>研判</b>，不是核验过的事实——每条都标了置信度、挂着引发它的原文，<b>不盖鉴印</b>。看它的方向就好，别当板上钉钉。
          </p>
          <div className="space-y-3">
            {signals.map((s, i) => {
              const cf = confidenceStyle(s.confidence);
              const basis = (s.basis ?? []).filter(hasText);
              const isOpen = !!openBasis[i];
              return (
                <div
                  key={`s${i}`}
                  className="relative rounded p-3 pl-4"
                  style={{
                    // 区隔做法：虚线框 + 略凹降调底——和证据层的实线卡 + 盖印明显两样
                    border: "1px dashed var(--color-rule)",
                    background: "var(--color-paper-sunken)",
                  }}
                >
                  {/* 研判标：左上一枚虚线降调小签——「研判·非核验」，跟鉴印对立的视觉语言 */}
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <span
                      className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded text-[var(--color-ink-muted)] whitespace-nowrap shrink-0"
                      style={{
                        border: "1px dashed var(--color-ink-muted)",
                        opacity: 0.85,
                      }}
                    >
                      研判 · 非核验
                    </span>
                    {/* 置信度徽章（刻意非朱砂，免得跟核验态撞色） */}
                    {hasText(s.confidence) && (
                      <span
                        className="text-[11px] px-2 py-0.5 rounded-full whitespace-nowrap shrink-0"
                        style={{ color: cf.fg, background: cf.bg }}
                      >
                        置信 {s.confidence}
                      </span>
                    )}
                  </div>

                  {/* 研判出的方向（评估层的结论，墨字但不盖印） */}
                  <p
                    className="text-[15px] leading-7 text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {hasText(s.direction) ? s.direction : "（这条没研判出方向）"}
                  </p>

                  {/* 原文基础：可展开——评估层也必须有据，连推断都挂着原文 */}
                  {basis.length > 0 && (
                    <div className="mt-2">
                      <button
                        type="button"
                        onClick={() =>
                          setOpenBasis((cur) => ({ ...cur, [i]: !cur[i] }))
                        }
                        className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                      >
                        {isOpen
                          ? "收起原文基础"
                          : `看原文基础（${basis.length}）`}
                      </button>
                      {isOpen && (
                        <ul className="mt-2 space-y-1.5">
                          {basis.map((b, bi) => (
                            <li
                              key={bi}
                              className="text-[13px] leading-relaxed text-[var(--color-ink-muted)] pl-3"
                              style={{
                                fontFamily: "var(--font-display)",
                                borderLeft: "1px dashed var(--color-rule)",
                              }}
                            >
                              <span
                                className="text-[10px] mr-1.5 align-top text-[var(--color-ink-muted)]"
                                style={{ opacity: 0.7 }}
                              >
                                引
                              </span>
                              {b}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {!loading && (
        <RunStats
          trace={trace}
          note={`替「${result.role}」机会 ${opportunities.length} · 风险 ${risks.length} · 信号 ${signals.length}`}
        />
      )}
    </div>
  );
}

// ---- 证据层段标（机会 / 风险共用）：朱砂短脊 + 段名 + 副名 + 条数 ----
function SectionHead({
  title,
  sub,
  count,
}: {
  title: string;
  sub: string;
  count: number;
}) {
  return (
    <div className="mb-3 flex items-center gap-2.5">
      <span className="h-3.5 w-[3px] rounded-full bg-[var(--color-seal)] opacity-70" />
      <span
        className="text-sm font-bold text-[var(--color-ink)]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        {title}
      </span>
      <span className="text-xs text-[var(--color-ink-muted)]">{sub}</span>
      <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
        {count}
      </span>
    </div>
  );
}

// ---- 证据层卡片（机会 / 风险共用）----
// 视觉权重跟着含金量走：真金白银朱砂重脊、空头倡导整条降调。
// 核过的盖「鉴」印 + 可展开原文；核不过老实标待核。
function StakeCard({
  kind,
  what,
  detailLabel,
  detail,
  action,
  substance,
  substanceReason,
  horizon,
  evidence,
  verified,
  open,
  onToggle,
}: {
  kind: "opp" | "risk";
  what: string;
  detailLabel: string;
  detail: string;
  action?: string;
  substance: string;
  substanceReason: string;
  horizon: string;
  evidence: string;
  verified: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  const st = substanceStyle(substance);
  const isVerified = verified && hasText(evidence);
  const canOpen = hasText(evidence);
  return (
    <article
      className="relative rounded border border-[var(--color-rule)] bg-white p-3 pl-4"
      style={{ opacity: st.cardOpacity }}
    >
      {/* 含金量脊：卡左一道竖脊，值钱的朱砂重、空头淡——视觉权重的主体 */}
      <span
        className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full"
        style={{
          background: st.cardBorder,
          opacity: st.cardBorderOpacity,
        }}
        aria-hidden="true"
      />

      {/* 标题行：what（主体）+ 右上含金量徽章 + 时效小标 */}
      <div className="flex items-start justify-between gap-2">
        <p className="text-[15px] font-bold text-[var(--color-ink)] leading-snug flex-1 min-w-0">
          {hasText(what)
            ? what
            : kind === "opp"
              ? "（这条没说清是什么机会）"
              : "（这条没说清是什么风险）"}
        </p>
        <div className="flex items-center gap-1.5 shrink-0 pt-0.5">
          <HorizonTag horizon={horizon} />
          <SubstanceBadge substance={substance} />
        </div>
      </div>

      {/* why / cost：这条对你为何是机会 / 代价是什么 */}
      {hasText(detail) && (
        <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--color-ink-muted)]">
          <span className="text-[var(--color-ink)]">{detailLabel}</span> ·{" "}
          {detail}
        </p>
      )}

      {/* action：可采取的动作（仅机会有）——朱砂细标领格，是「能去争取」的落点 */}
      {hasText(action) && (
        <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--color-ink)]">
          <span
            className="text-[11px] mr-1.5 align-top"
            style={{ color: "var(--color-seal)" }}
          >
            可争取
          </span>
          {action}
        </p>
      )}

      {/* 含金量凭据：凭哪些 marker 判的（锚原文里的约束词/时限/主体/罚则）——评级也要有据 */}
      {hasText(substanceReason) && (
        <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--color-ink-muted)] italic">
          含金量凭据 · {substanceReason}
        </p>
      )}

      {/* 原文：核过盖印 + 可展开；核不过老实标待核 */}
      <div className="mt-2">
        {isVerified ? (
          <div className="flex items-center gap-2 flex-wrap">
            <SealMark size={17} title="原文已核验" />
            {canOpen && (
              <button
                type="button"
                onClick={onToggle}
                className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
              >
                {open ? "收起原文" : "看原文出处"}
              </button>
            )}
          </div>
        ) : (
          <p className="text-xs text-[var(--color-ink-muted)] italic">
            {canOpen
              ? "未在原文比对命中·仅供参考"
              : "暂无贴切原文（待核）"}
          </p>
        )}
        {canOpen && open && (
          <p
            className="mt-2 text-[13px] leading-relaxed text-[var(--color-ink)] border-l-2 pl-3"
            style={{
              fontFamily: "var(--font-display)",
              borderColor: "var(--color-seal)",
            }}
          >
            <span
              className="text-[11px] mr-1.5 align-top"
              style={{ color: "var(--color-seal)" }}
            >
              原文
            </span>
            {evidence}
          </p>
        )}
      </div>
    </article>
  );
}
