// ---------------------------------------------------------------------------
// ActionLedger — 行动项台账 / 我的行动项（1.7 会议垂直·首炮前端）
//
// 一份会议记录精读一次出「会脉」（会议头要素 + 决议 + 行动项），这块把它派生成两件事：
//   行动项台账 —— 这场会派下去的活全列出来：谁负责、几号前办完、含金量几何、有没有落空。
//   我的行动项 —— 填一个名字，只看冲你来的那几条。
//
// 会议的命根子不是「谁说了什么」（几百轮口水话），是「定了什么、谁要去做什么」。所以台账
// 把没人接、没定时限的活（loose_end）捞到最前——这是会议最大的黑洞，开完会没人管的就是这些。
//
// 含金量沿用公文那套钱学森开环/闭环判（后端读原文判好、排好序，前端照序渲染）：
//   闭环（拍板 + 有人接 + 有时限 + 有验收）= 真金白银，会兑现；
//   开环（只表个态、回头弄）= 空头表态，多半漂没。叶子档名是会议版「空头表态」。
//
// evidence-first（全站一个规矩）：核过的原文角上盖「鉴」印；核不过老实标待核；owner / due
// 抽不到留空、绝不替它编人编时间——空着是信号（这活没落实到人），不是缺陷。
//
// 设计语言（数字善本案头）：朱墨双色、宋体 var(--font-display)、留白、古籍克制——不堆古风、
// 无 emoji。复用 SealMark（钤印）/ RunningProcess / RunStats，不引新依赖。窄屏单列、卡片化。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（对着 MeetingActionLedgerResponse 写，别改后端） ----

// 含金量三档（会议版）：真金白银（闭环·会兑现）/ 有条件兑现（半闭环）/ 空头表态（开环·必漂）。
type Substance = "真金白银" | "有条件兑现" | "空头表态";
// 形态：逐字稿（带说话人标记的流水）/ 纪要（已整理的编辑稿）。
type Form = "逐字稿" | "纪要";

interface HeadElement {
  field: string; // 六项之一：会议主题/会议时间/主持人/参会人/缺席列席/记录范围
  value: string; // 抽到的值；抽不到留空
  evidence: string;
  verified: boolean;
  match_score: number;
  not_applicable?: boolean; // 该形态天生没有的（纪要的缺席列席 / 逐字稿的记录范围）
}

interface Decision {
  chapter: number; // 序号
  decision: string; // 定了什么
  decided_by: string; // 谁拍的板
  background: string; // 为什么定 / 依据
  substance: Substance;
  substance_reason: string; // 凭哪些 marker 判的（锚原文）
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface ActionItem {
  chapter: number; // 序号
  task: string; // 要做的事
  owner: string; // 谁负责（空 = 没人接，是信号）
  due: string; // 几号前完成（空 = 没定时限，是信号）
  from_decision: number | null; // 落实哪条决议（决议序号，可空）
  source: string; // 谁交代的 / 谁认领的
  substance: Substance;
  substance_reason: string;
  loose_end: boolean; // owner 空或 due 空 = true（BE 纯计算）
  evidence: string;
  verified: boolean;
  match_score: number;
}

// 议而未决「为何悬着」四档：未拍板（讨论了没人拍）/ 没人接（提议没人认领）/
// 待外部（卡在会场外，等上级或别的部门）/ 待下次（已约下次会再议）。
type OpenIssueReason = "未拍板" | "没人接" | "待外部" | "待下次";

interface OpenIssue {
  chapter: number; // 序号
  issue: string; // 悬着的议题
  raised_by: string; // 谁提的（空 = 没点明，绝不替它编人）
  why_open: OpenIssueReason | string; // 为何悬着（四档之一）
  background: string; // 卡在哪 / 争论的点
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface LedgerResponse {
  form: Form | string;
  head: HeadElement[];
  decisions: Decision[];
  action_items: ActionItem[];
  open_issues: OpenIssue[]; // 议而未决（讨论了没结论的黑洞）
  owner: string | null; // 回显请求的 owner（我的行动项时）
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface ActionLedgerProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// ---- 含金量徽章样式：视觉权重跟着含金量走（同公文利害与风向那套） ----
// 真金白银 = 朱红重（值钱）；有条件兑现 = 中性墨；空头表态 = 灰弱降调。
// 写死语义色（含金量是评级语义不是主题色），fallback 走墨色避免未知值炸掉。
interface SubstanceStyle {
  fg: string;
  bg: string;
  border: string;
  rail: string; // 卡左竖脊色
  railOpacity: number;
  weight: number;
}

const SUBSTANCE_STYLE: Record<Substance, SubstanceStyle> = {
  真金白银: {
    fg: "#9a3a2e",
    bg: "rgba(154, 58, 46, 0.12)",
    border: "rgba(154, 58, 46, 0.55)",
    rail: "var(--color-seal)",
    railOpacity: 0.65,
    weight: 700,
  },
  有条件兑现: {
    fg: "var(--color-ink)",
    bg: "rgba(58, 99, 120, 0.08)",
    border: "rgba(58, 99, 120, 0.35)",
    rail: "var(--color-ink-muted)",
    railOpacity: 0.4,
    weight: 600,
  },
  空头表态: {
    fg: "var(--color-ink-muted)",
    bg: "rgba(0, 0, 0, 0.03)",
    border: "var(--color-rule)",
    rail: "var(--color-rule)",
    railOpacity: 1,
    weight: 500,
  },
};

function substanceStyle(s: string): SubstanceStyle {
  return (
    SUBSTANCE_STYLE[s as Substance] ?? {
      fg: "var(--color-ink-muted)",
      bg: "var(--color-seal-soft)",
      border: "var(--color-rule)",
      rail: "var(--color-ink-muted)",
      railOpacity: 0.3,
      weight: 500,
    }
  );
}

// 含金量一句注脚（徽章悬停），点破闭环 vs 开环。
const SUBSTANCE_HINT: Record<Substance, string> = {
  真金白银: "拍了板、有人接、有时限、有验收，会兑现",
  有条件兑现: "方向定了、人也接了，但缺时限或验收",
  空头表态: "只表了个态、回头弄，没人接没时限，多半漂没",
};

// 「为何悬着」徽章样式：会场内能立刻追的（未拍板 / 没人接）描朱砂、催一催就有下文；
// 已经有去向的（待外部 / 待下次）用中性墨，相对没那么急。fallback 走墨色避免未知值炸掉。
interface ReasonStyle {
  fg: string;
  bg: string;
  border: string;
}

const OPEN_ISSUE_REASON_STYLE: Record<OpenIssueReason, ReasonStyle> = {
  未拍板: {
    fg: "#9a3a2e",
    bg: "rgba(154, 58, 46, 0.1)",
    border: "rgba(154, 58, 46, 0.5)",
  },
  没人接: {
    fg: "#9a3a2e",
    bg: "rgba(154, 58, 46, 0.1)",
    border: "rgba(154, 58, 46, 0.5)",
  },
  待外部: {
    fg: "var(--color-ink)",
    bg: "rgba(58, 99, 120, 0.08)",
    border: "rgba(58, 99, 120, 0.35)",
  },
  待下次: {
    fg: "var(--color-ink-muted)",
    bg: "rgba(0, 0, 0, 0.03)",
    border: "var(--color-rule)",
  },
};

function reasonStyle(r: string): ReasonStyle {
  return (
    OPEN_ISSUE_REASON_STYLE[r as OpenIssueReason] ?? {
      fg: "var(--color-ink-muted)",
      bg: "var(--color-seal-soft)",
      border: "var(--color-rule)",
    }
  );
}

// 「为何悬着」一句注脚（徽章悬停），点破这议题卡在哪、下一步该谁动。
const OPEN_ISSUE_REASON_HINT: Record<OpenIssueReason, string> = {
  未拍板: "讨论了没人拍板，要找人定下来",
  没人接: "提议本身没问题，但没人认领去推",
  待外部: "卡在会场外，等上级或别的部门先动",
  待下次: "明确推到下次会再议，已有去向",
};

function hasText(v: string | undefined | null): boolean {
  return !!v && v.trim().length > 0;
}

// 含金量徽章——评级语义的视觉权重。真金白银描重、空头表态描淡。
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

// 「为何悬着」徽章——会场内能追的描朱砂、有去向的描淡。
function ReasonBadge({ reason }: { reason: string }) {
  const st = reasonStyle(reason);
  return (
    <span
      className="inline-flex items-center text-[11px] px-2 py-0.5 rounded-full whitespace-nowrap shrink-0"
      title={OPEN_ISSUE_REASON_HINT[reason as OpenIssueReason] ?? ""}
      style={{
        color: st.fg,
        background: st.bg,
        border: `0.5px solid ${st.border}`,
        fontWeight: 600,
        fontFamily: "var(--font-display)",
      }}
    >
      {reason}
    </span>
  );
}

// loose_end 客观标：owner 空标「未派到人」、due 空标「未定时限」。两者都空两个都标。
// 这是客观事实标记（后端纯计算），不替会议编人编时间——指出黑洞在哪，不替它填上。
function LooseEndTags({ owner, due }: { owner: string; due: string }) {
  const tags: string[] = [];
  if (!hasText(owner)) tags.push("未派到人");
  if (!hasText(due)) tags.push("未定时限");
  if (tags.length === 0) return null;
  return (
    <>
      {tags.map((t) => (
        <span
          key={t}
          className="inline-flex items-center text-[11px] px-2 py-0.5 rounded-full whitespace-nowrap shrink-0"
          style={{
            color: "#9a3a2e",
            background: "rgba(154, 58, 46, 0.08)",
            border: "0.5px dashed rgba(154, 58, 46, 0.5)",
          }}
        >
          {t}
        </span>
      ))}
    </>
  );
}

export function ActionLedger({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: ActionLedgerProps) {
  // 「我的行动项」输入框；空 = 看全部台账。提交时随请求带给后端按身份筛。
  const [ownerInput, setOwnerInput] = useState("");
  // 后端实际筛过的 owner（回显），用来判当前看的是台账还是某人的。
  const [result, setResult] = useState<LedgerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 决议 / 行动项逐条点「看原文出处」展开 evidence（键 = "d1" / "a3"），保卡片清爽。
  const [openEvidence, setOpenEvidence] = useState<Record<string, boolean>>({});

  const ownerTrimmed = ownerInput.trim();

  async function load() {
    setLoading(true);
    setError(null);
    setOpenEvidence({});
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      // 带了名字就让后端按身份筛（我的行动项）；空就返全部台账。form 留空让后端自动判形态。
      if (ownerTrimmed) body.owner = ownerTrimmed;
      const resp = await fetch("/api/agent/meeting/action-ledger", {
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
      const data = (await resp.json()) as LedgerResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const head = result?.head ?? [];
  const decisions = result?.decisions ?? [];
  const actionItems = result?.action_items ?? [];
  // 我的行动项（传了 owner）只看行动项，议而未决是整场会的、不按身份筛——只在台账模式显示。
  const openIssues = result?.owner ? [] : (result?.open_issues ?? []);
  const scanned = !!result && result.scanned;
  const filteredOwner = result?.owner ?? null; // 后端回显的筛选身份
  // 头要素里抽到值的那些（N/A 和待核都不算「抽到了」）。
  const headFilled = useMemo(
    () => head.filter((h) => hasText(h.value)),
    [head],
  );
  const gotSomething =
    scanned &&
    (actionItems.length > 0 ||
      decisions.length > 0 ||
      openIssues.length > 0 ||
      headFilled.length > 0);

  const looseCount = useMemo(
    () => actionItems.filter((a) => a.loose_end).length,
    [actionItems],
  );
  const realMoneyCount = useMemo(
    () => actionItems.filter((a) => a.substance === "真金白银").length,
    [actionItems],
  );
  const verifiedCount = useMemo(
    () => actionItems.filter((a) => a.verified && hasText(a.evidence)).length,
    [actionItems],
  );
  const openCount = openIssues.length;

  // ---- 标题行 ----
  const header = (
    <h3
      className="text-base font-bold text-[var(--color-ink)] mb-1 flex items-center gap-2"
      style={{ fontFamily: "var(--font-display)" }}
    >
      {/* 会议点缀：标题前一道朱砂短脊，预告这是会议视图 */}
      <span
        className="h-4 w-[3px] rounded-full bg-[var(--color-seal)]"
        aria-hidden="true"
      />
      行动项台账
    </h3>
  );

  // ---- 我的行动项输入区（永远在顶上，填名字只看冲你来的那几条） ----
  const ownerBar = (
    <div className="mb-4">
      <label
        className="block text-sm font-bold text-[var(--color-ink)] mb-1.5"
        style={{ fontFamily: "var(--font-display)" }}
      >
        我的行动项
      </label>
      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        填上你的名字，只看派到你头上的活；留空就是整场会的台账。
      </p>
      <div className="flex items-stretch gap-2">
        <input
          type="text"
          value={ownerInput}
          onChange={(e) => setOwnerInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !loading && apiKey) load();
          }}
          placeholder="留空看全部，或填一个名字（如「作者」）"
          disabled={loading}
          className="flex-1 text-sm px-3 py-2 rounded border border-[var(--color-rule)] bg-white text-[var(--color-ink)] placeholder:text-[var(--color-ink-muted)] focus:outline-none focus:border-[var(--color-seal)] disabled:opacity-50"
          style={{ fontFamily: "var(--font-display)" }}
        />
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors whitespace-nowrap"
        >
          {loading ? "精读中…" : result ? "重新生成" : "生成台账"}
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

  // ---- 未生成：入口 + 输入区 ----
  if (!result) {
    return (
      <div className="pt-4">
        {header}
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          一份会议记录精读一次，把这场会派下去的活全列成一张能勾的台账：每条说清做什么、谁负责、几号前办完、落实哪条决议，还标含金量（真金白银还是空头表态）、钉原文。没人接、没定时限的活排最前，那是开完会最容易没下文的黑洞。台账下面再单列一份悬而未决：提了却没拍板、没人接、要等外部或留到下次的议题，散会最容易被忘掉的就是这些。逐字稿、纪要都能读。
        </p>
        {ownerBar}
        {loading && (
          <RunningProcess
            label="精读这份会议记录"
            hint="整份记录喂进模型，从发言流水里淘出定了什么、谁要去做什么、哪些还悬着没定，每条回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没抽到：优雅退场 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        {header}
        {ownerBar}
        {loading ? (
          <RunningProcess label="精读这份会议记录" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            {filteredOwner
              ? `这场会没派到「${filteredOwner}」头上的活——换个名字，或留空看整场台账。`
              : scanned
                ? "读过了，但没淘出能钉在原文的决议、行动项或悬而未决——这份可能是偏务虚的讨论、没拍下具体的活，或者不是会议记录。换一份会议记录，或稍后重试。"
                : "没读出可梳理的内容——这份可能不是会议记录，或格式太特殊。换一份逐字稿 / 纪要，或稍后重试。"}
          </p>
        )}
      </div>
    );
  }

  const formLabel = result.form === "逐字稿" ? "逐字稿" : "纪要";

  // ---- 已抽到：会议头 + 决议 + 行动项台账 ----
  return (
    <div className="pt-4">
      {header}
      {ownerBar}

      {/* 题署一行：形态 · 行动项几条 · 真金白银几条 · 落空几条 · 原文核验几条 */}
      <div className="mb-4 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          {formLabel}
        </span>
        {filteredOwner && (
          <span
            className="inline-block text-xs px-2 py-0.5 rounded-full"
            style={{
              color: "var(--color-seal)",
              border: "0.5px solid var(--color-seal)",
            }}
          >
            只看「{filteredOwner}」
          </span>
        )}
        {actionItems.length > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            行动项 {actionItems.length}
          </span>
        )}
        {decisions.length > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            决议 {decisions.length}
          </span>
        )}
        {openCount > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            悬而未决 {openCount}
          </span>
        )}
        {realMoneyCount > 0 && (
          <span className="text-xs tabular-nums" style={{ color: "#9a3a2e" }}>
            真金白银 {realMoneyCount}
          </span>
        )}
        {looseCount > 0 && (
          <span className="text-xs tabular-nums" style={{ color: "#9a3a2e" }}>
            落空 {looseCount}
          </span>
        )}
        {actionItems.length > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            原文核验 {verifiedCount}/{actionItems.length}
          </span>
        )}
      </div>

      {/* ── 会议头要素：题署六项，缺的标待核 / 本形态无此项，绝不编 ── */}
      {head.length > 0 && (
        <section className="mb-6">
          <SectionHead title="会议头" sub="这场会的基本要素" count={headFilled.length} />
          <dl className="rounded border border-[var(--color-rule)] bg-[var(--color-paper-sunken)] divide-y divide-[var(--color-rule)]">
            {head.map((h) => (
              <HeadRow key={h.field} el={h} />
            ))}
          </dl>
        </section>
      )}

      {/* ── 决议：这场会真定下来的事 ── */}
      {decisions.length > 0 && (
        <section className="mb-6">
          <SectionHead title="决议" sub="这场会真定下来的事" count={decisions.length} />
          <div className="space-y-3">
            {decisions.map((d) => (
              <DecisionCard
                key={`d${d.chapter}`}
                decision={d}
                open={!!openEvidence[`d${d.chapter}`]}
                onToggle={() =>
                  setOpenEvidence((cur) => ({
                    ...cur,
                    [`d${d.chapter}`]: !cur[`d${d.chapter}`],
                  }))
                }
              />
            ))}
          </div>
        </section>
      )}

      {/* ── 行动项台账：谁·做什么·何时·落实哪条决议；落空的置顶 ── */}
      {actionItems.length > 0 && (
        <section className="mb-6">
          <SectionHead
            title={filteredOwner ? "我的行动项" : "行动项台账"}
            sub="没人接 / 没时限的排最前"
            count={actionItems.length}
          />
          <div className="space-y-3">
            {actionItems.map((a) => (
              <ActionCard
                key={`a${a.chapter}`}
                item={a}
                open={!!openEvidence[`a${a.chapter}`]}
                onToggle={() =>
                  setOpenEvidence((cur) => ({
                    ...cur,
                    [`a${a.chapter}`]: !cur[`a${a.chapter}`],
                  }))
                }
              />
            ))}
          </div>
        </section>
      )}

      {/* ── 悬而未决：讨论了没拍板 / 没人接 / 等外部 / 留下次的议题（会议最大的黑洞） ── */}
      {openIssues.length > 0 && (
        <section className="mb-2">
          <SectionHead
            title="悬而未决"
            sub="提了却没定论的议题，散会最容易没下文"
            count={openIssues.length}
          />
          <div className="space-y-3">
            {openIssues.map((o) => (
              <OpenIssueCard
                key={`o${o.chapter}`}
                item={o}
                open={!!openEvidence[`o${o.chapter}`]}
                onToggle={() =>
                  setOpenEvidence((cur) => ({
                    ...cur,
                    [`o${o.chapter}`]: !cur[`o${o.chapter}`],
                  }))
                }
              />
            ))}
          </div>
        </section>
      )}

      {!loading && (
        <RunStats
          trace={trace}
          note={`行动项 ${actionItems.length} · 决议 ${decisions.length}${
            openCount > 0 ? ` · 悬而未决 ${openCount}` : ""
          }${looseCount > 0 ? ` · 落空 ${looseCount}` : ""}`}
        />
      )}
    </div>
  );
}

// ---- 段标（会议头 / 决议 / 行动项共用）：朱砂短脊 + 段名 + 副名 + 条数 ----
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
    <div className="mb-3 flex items-center gap-2.5 flex-wrap">
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

// ---- 会议头一行：要素名 + 值（缺的标待核 / 本形态无此项）+ 核过盖印 ----
function HeadRow({ el }: { el: HeadElement }) {
  const filled = hasText(el.value);
  const verifiedOrigin = el.verified && hasText(el.evidence);
  return (
    <div className="flex items-baseline gap-3 px-3 py-2">
      <dt
        className="text-xs text-[var(--color-ink-muted)] shrink-0 w-[5.5rem]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        {el.field}
      </dt>
      <dd className="flex-1 min-w-0 flex items-center gap-2 flex-wrap">
        {filled ? (
          <>
            <span
              className="text-sm text-[var(--color-ink)] leading-snug break-words"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {el.value}
            </span>
            {verifiedOrigin ? (
              <SealMark size={15} title="原文已核验" />
            ) : (
              <span
                className="text-[11px] text-[var(--color-ink-muted)]"
                title={el.evidence ? "未在原文比对命中" : undefined}
              >
                未核验
              </span>
            )}
          </>
        ) : el.not_applicable ? (
          <span className="text-xs text-[var(--color-ink-muted)] italic">
            本形态无此项
          </span>
        ) : (
          <span className="text-xs text-[var(--color-ink-muted)] italic">
            待核（原文里没抽到）
          </span>
        )}
      </dd>
    </div>
  );
}

// ---- 决议卡片：定了什么 + 谁拍的 + 含金量 + 凭据 + 原文 ----
function DecisionCard({
  decision,
  open,
  onToggle,
}: {
  decision: Decision;
  open: boolean;
  onToggle: () => void;
}) {
  const st = substanceStyle(decision.substance);
  const verifiedOrigin = decision.verified && hasText(decision.evidence);
  const canOpen = hasText(decision.evidence);
  return (
    <article className="relative rounded border border-[var(--color-rule)] bg-white p-3 pl-4">
      {/* 含金量脊：卡左一道竖脊，值钱的朱砂重、空头淡 */}
      <span
        className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full"
        style={{ background: st.rail, opacity: st.railOpacity }}
        aria-hidden="true"
      />
      <div className="flex items-start justify-between gap-2">
        <p className="text-[15px] font-bold text-[var(--color-ink)] leading-snug flex-1 min-w-0">
          <span
            className="text-[11px] mr-1.5 align-top text-[var(--color-ink-muted)] tabular-nums"
            aria-hidden="true"
          >
            {decision.chapter}
          </span>
          {hasText(decision.decision)
            ? decision.decision
            : "（这条没说清定了什么）"}
        </p>
        <SubstanceBadge substance={decision.substance} />
      </div>

      {(hasText(decision.decided_by) || hasText(decision.background)) && (
        <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--color-ink-muted)]">
          {hasText(decision.decided_by) && (
            <>
              <span className="text-[var(--color-ink)]">谁拍的</span> ·{" "}
              {decision.decided_by}
            </>
          )}
          {hasText(decision.decided_by) && hasText(decision.background) && "　"}
          {hasText(decision.background) && (
            <>
              <span className="text-[var(--color-ink)]">背景</span> ·{" "}
              {decision.background}
            </>
          )}
        </p>
      )}

      {hasText(decision.substance_reason) && (
        <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--color-ink-muted)] italic">
          含金量凭据 · {decision.substance_reason}
        </p>
      )}

      <EvidenceFoot
        verifiedOrigin={verifiedOrigin}
        canOpen={canOpen}
        open={open}
        onToggle={onToggle}
        evidence={decision.evidence}
      />
    </article>
  );
}

// ---- 行动项卡片：任务 + 负责人 / 时限（落空标 loose_end）+ 含金量 + 原文 ----
function ActionCard({
  item,
  open,
  onToggle,
}: {
  item: ActionItem;
  open: boolean;
  onToggle: () => void;
}) {
  const st = substanceStyle(item.substance);
  const verifiedOrigin = item.verified && hasText(item.evidence);
  const canOpen = hasText(item.evidence);
  return (
    <article
      className="relative rounded border bg-white p-3 pl-4"
      style={{
        // 落空的活描一道朱砂虚边提醒（这是黑洞）；落实的活素净。
        borderColor: item.loose_end
          ? "rgba(154, 58, 46, 0.45)"
          : "var(--color-rule)",
        borderStyle: item.loose_end ? "dashed" : "solid",
      }}
    >
      {/* 含金量脊 */}
      <span
        className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full"
        style={{ background: st.rail, opacity: st.railOpacity }}
        aria-hidden="true"
      />
      {/* 任务行 + 含金量徽章 */}
      <div className="flex items-start justify-between gap-2">
        <p className="text-[15px] font-bold text-[var(--color-ink)] leading-snug flex-1 min-w-0">
          <span
            className="text-[11px] mr-1.5 align-top text-[var(--color-ink-muted)] tabular-nums"
            aria-hidden="true"
          >
            {item.chapter}
          </span>
          {hasText(item.task) ? item.task : "（这条没说清要做什么）"}
        </p>
        <SubstanceBadge substance={item.substance} />
      </div>

      {/* 负责人 / 时限：抽到了正常显示，空了显客观落空标——绝不替它编人编时间 */}
      <div className="mt-2 flex items-center gap-2 flex-wrap text-[13px]">
        {hasText(item.owner) ? (
          <span className="text-[var(--color-ink)]">
            <span className="text-[var(--color-ink-muted)]">负责人</span>{" "}
            {item.owner}
          </span>
        ) : null}
        {hasText(item.due) ? (
          <span className="text-[var(--color-ink)]">
            <span className="text-[var(--color-ink-muted)]">时限</span>{" "}
            {item.due}
          </span>
        ) : null}
        <LooseEndTags owner={item.owner} due={item.due} />
      </div>

      {/* source / 落实哪条决议 */}
      {(hasText(item.source) || item.from_decision !== null) && (
        <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--color-ink-muted)]">
          {hasText(item.source) && (
            <>
              <span className="text-[var(--color-ink)]">谁交代的</span> ·{" "}
              {item.source}
            </>
          )}
          {hasText(item.source) && item.from_decision !== null && "　"}
          {item.from_decision !== null && (
            <>落实决议第 {item.from_decision} 条</>
          )}
        </p>
      )}

      {hasText(item.substance_reason) && (
        <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--color-ink-muted)] italic">
          含金量凭据 · {item.substance_reason}
        </p>
      )}

      <EvidenceFoot
        verifiedOrigin={verifiedOrigin}
        canOpen={canOpen}
        open={open}
        onToggle={onToggle}
        evidence={item.evidence}
      />
    </article>
  );
}

// ---- 议而未决卡片：议题 + 谁提的 + 为何悬着 + 背景 + 原文 ----
// 卡片描朱砂虚边提醒这是悬着的黑洞（同落空行动项的视觉语言）；左脊跟着「为何悬着」的轻重。
function OpenIssueCard({
  item,
  open,
  onToggle,
}: {
  item: OpenIssue;
  open: boolean;
  onToggle: () => void;
}) {
  const st = reasonStyle(item.why_open);
  const verifiedOrigin = item.verified && hasText(item.evidence);
  const canOpen = hasText(item.evidence);
  return (
    <article
      className="relative rounded border bg-white p-3 pl-4"
      style={{
        borderColor: "rgba(154, 58, 46, 0.4)",
        borderStyle: "dashed",
      }}
    >
      {/* 为何悬着脊：会场内能追的朱砂重、有去向的淡 */}
      <span
        className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full"
        style={{ background: st.fg, opacity: 0.55 }}
        aria-hidden="true"
      />
      {/* 议题行 + 为何悬着徽章 */}
      <div className="flex items-start justify-between gap-2">
        <p className="text-[15px] font-bold text-[var(--color-ink)] leading-snug flex-1 min-w-0">
          <span
            className="text-[11px] mr-1.5 align-top text-[var(--color-ink-muted)] tabular-nums"
            aria-hidden="true"
          >
            {item.chapter}
          </span>
          {hasText(item.issue) ? item.issue : "（这条没说清悬的是什么）"}
        </p>
        <ReasonBadge reason={item.why_open} />
      </div>

      {/* 谁提的：抽到了显示，空了不替它编人 */}
      {hasText(item.raised_by) && (
        <p className="mt-2 text-[13px] text-[var(--color-ink)]">
          <span className="text-[var(--color-ink-muted)]">谁提的</span>{" "}
          {item.raised_by}
        </p>
      )}

      {hasText(item.background) && (
        <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--color-ink-muted)]">
          <span className="text-[var(--color-ink)]">卡在哪</span> ·{" "}
          {item.background}
        </p>
      )}

      <EvidenceFoot
        verifiedOrigin={verifiedOrigin}
        canOpen={canOpen}
        open={open}
        onToggle={onToggle}
        evidence={item.evidence}
      />
    </article>
  );
}

// ---- 原文脚（决议 / 行动项 / 议而未决共用）：核过盖印 + 可展开；核不过老实标待核 ----
function EvidenceFoot({
  verifiedOrigin,
  canOpen,
  open,
  onToggle,
  evidence,
}: {
  verifiedOrigin: boolean;
  canOpen: boolean;
  open: boolean;
  onToggle: () => void;
  evidence: string;
}) {
  return (
    <div className="mt-2">
      {verifiedOrigin ? (
        <div className="flex items-center gap-2 flex-wrap">
          <SealMark size={17} title="原文已核验" />
          <button
            type="button"
            onClick={onToggle}
            className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
          >
            {open ? "收起原文" : "看原文出处"}
          </button>
        </div>
      ) : (
        <p className="text-xs text-[var(--color-ink-muted)] italic">
          {canOpen ? "未在原文比对命中·仅供参考" : "暂无贴切原文（待核）"}
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
  );
}
