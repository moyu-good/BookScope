// ---------------------------------------------------------------------------
// StanceSubtext — 立场与弦外（1.7 会议垂直·最后一块）
//
// 前面四块（行动项台账 / 我的行动项 / 悬而未决 / 跨会承诺）回答「这场会定了什么、谁要办
// 什么」；这块回答「大家心里到底怎么想、这些表态有几分真」。会议里的真实立场常不在字面上：
// 「再研究研究」往往是不想办，「我理解但是」往往是软反对，「我尽量争取」往往是没底的敷衍。
// 这块替读者把字面底下的真实态度挖出来——谁真同意、谁附条件、谁嘴上应付实则拖延、谁在踢皮球。
//
// 这是会议比公文多出来的一维（公文单向下达没有多方角力），也是读者光靠自己读最难读出来的一层。
//
// evidence-first（这里红线最硬）：立场和弦外**整个是评估层**，没有一条是「盖鉴印的事实」，
// 全是带原话基础的推断。所以视觉跟公文「利害与风向」的信号段同一个契约——标「研判」、引原话、
// 给把握，**绝不盖「鉴」印**（鉴印 = 核过的事实，立场不配）。立场「Eng-B 软反对」是研判，
// 底下引的逐字稿原话才是事实，两者分开。后端 basis 核不到的整条丢、纪要里不硬编弦外。
//
// 三态空值（确证无 ≠ 抽不到）：一议题大家是真一致、没有暗流，这是好事不是漏读——明确显
// 「这件事大家是真一致」，甚至是个正面信号。纪要读不出现场语气就老实说「建议传逐字稿」。
//
// 设计语言（数字善本案头）：朱墨双色、宋体 var(--font-display)、留白克制——不堆古风、无 emoji。
// 视觉上跟证据层（钤印核验那套）刻意区隔：虚线框 + 降调底 + 研判标，复用 RunningProcess /
// RunStats，不引新依赖、不盖 SealMark。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";

// ---- 后端契约（对着 /agent/meeting/stance 的 schema 写，照设计稿 WP-1.7 §1） ----

// 形态：逐字稿（带说话人标记的流水）/ 纪要（已整理的编辑稿，读不出现场语气）。
type Form = "逐字稿" | "纪要";

// 立场方向五态（封闭集）：支持 / 反对 / 保留 / 摇摆 / 回避。判不准退「摇摆」（最中性）。
type Position = "支持" | "反对" | "保留" | "摇摆" | "回避";

// 表态含金量三档（同公文 / 行动项那把钱学森开环闭环尺）：
// 真金白银（接了活 + 给了时限）/ 有条件兑现（介于）/ 空头表态（纯姿态、没下文）。
type Substance = "真金白银" | "有条件兑现" | "空头表态";

// 弦外六类（封闭集）：会议口语特有的几种言下之意。落不进六类就不输出（不设兜底类）。
type SubtextKind =
  | "表面同意实则保留"
  | "拖延搁置"
  | "甩锅推责"
  | "回避问题"
  | "留口子"
  | "口头答应没底";

// 把握高 / 中 / 低（评估层专用，绝不是核验态）。判不准退「低」（最保守）。
type Confidence = "高" | "中" | "低";

// 议题三态：有立场张力（正常显示）/ 确证一致无弦外（笃定的好事）/ 读不出（纪要待核）。
type Verdict = "有立场张力" | "确证一致无弦外" | "读不出（纪要/待核）";

interface Stance {
  person: string; // 谁（抽不到这条不输出）
  topic: string; // 对哪个议题（跟所属 topic 一致，冗余存）
  position: Position | string;
  reading: string; // 这态度的人话解读（直接说「他其实是…」）
  substance: Substance | string;
  substance_reason: string; // 凭哪些 marker 判含金量（锚原话）
  basis: string[]; // 引发这判断的发言原话（逐字、过核验、确在文里）
  confidence: Confidence | string;
}

interface Subtext {
  kind: SubtextKind | string;
  person: string; // 谁（抽不到这条不输出）
  topic: string; // 这弦外出现在哪个议题上
  subtext: string; // 言下之意是什么（说清「他这话真正想说的是…」）
  basis: string[]; // 引发这判断的发言原话
  confidence: Confidence | string;
}

interface StanceTopic {
  topic: string;
  verdict: Verdict | string;
  stances: Stance[]; // verdict=确证一致无弦外 时为空，verdict 本身是答案
  subtexts: Subtext[];
}

interface StanceResponse {
  schema_version?: string;
  form: Form | string;
  form_note: string; // 纪要降级提示（逐字稿为空串）
  topics: StanceTopic[];
  summary: string; // 系统一句话总览（带立场，谁在推谁在拖）
  scanned?: boolean;
  book_session_id?: string;
  trace?: RunTrace;
}

interface StanceSubtextProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

function hasText(v: string | undefined | null): boolean {
  return !!v && v.trim().length > 0;
}

// ---- 立场方向徽章样式 ----
// 反对 = 朱红重（最该当心的态度）；保留 / 回避 = 中性墨（打了折 / 没正面接）；
// 摇摆 = 灰弱（没准主意）；支持 = 安定墨（正面）。写死语义色，fallback 走墨色避免未知值炸掉。
interface PositionStyle {
  fg: string;
  bg: string;
  border: string;
}

const POSITION_STYLE: Record<Position, PositionStyle> = {
  支持: {
    fg: "#3f6f4a",
    bg: "rgba(63, 111, 74, 0.1)",
    border: "rgba(63, 111, 74, 0.45)",
  },
  反对: {
    fg: "#9a3a2e",
    bg: "rgba(154, 58, 46, 0.12)",
    border: "rgba(154, 58, 46, 0.55)",
  },
  保留: {
    fg: "#8a6b3f",
    bg: "rgba(138, 107, 63, 0.12)",
    border: "rgba(138, 107, 63, 0.4)",
  },
  摇摆: {
    fg: "var(--color-ink-muted)",
    bg: "rgba(0, 0, 0, 0.03)",
    border: "var(--color-rule)",
  },
  回避: {
    fg: "var(--color-ink)",
    bg: "rgba(58, 99, 120, 0.08)",
    border: "rgba(58, 99, 120, 0.35)",
  },
};

function positionStyle(p: string): PositionStyle {
  return (
    POSITION_STYLE[p as Position] ?? {
      fg: "var(--color-ink-muted)",
      bg: "rgba(0, 0, 0, 0.04)",
      border: "var(--color-rule)",
    }
  );
}

// 立场方向一句注脚（徽章悬停），点破这态度读者要怎么看。
const POSITION_HINT: Record<Position, string> = {
  支持: "明确赞成、愿意推",
  反对: "明确不赞成，含软反对（一直挑刺 / 提替代方案 / 强调风险）",
  保留: "附了条件、同意里打了折（原则上同意 / 可以但是…）",
  摇摆: "没拿定主意、模棱两可、前后不一",
  回避: "不正面表态、岔开话题、被点名却只说别的",
};

// ---- 表态含金量徽章样式（同行动项 / 公文那把开环闭环尺）----
// 真金白银 = 朱红重（动真格）；有条件兑现 = 中性墨；空头表态 = 灰弱降调（嘴上说说）。
const SUBSTANCE_STYLE: Record<Substance, PositionStyle & { weight: number }> = {
  真金白银: {
    fg: "#9a3a2e",
    bg: "rgba(154, 58, 46, 0.12)",
    border: "rgba(154, 58, 46, 0.55)",
    weight: 700,
  },
  有条件兑现: {
    fg: "var(--color-ink)",
    bg: "rgba(58, 99, 120, 0.08)",
    border: "rgba(58, 99, 120, 0.35)",
    weight: 600,
  },
  空头表态: {
    fg: "var(--color-ink-muted)",
    bg: "rgba(0, 0, 0, 0.03)",
    border: "var(--color-rule)",
    weight: 500,
  },
};

function substanceStyle(s: string): PositionStyle & { weight: number } {
  return (
    SUBSTANCE_STYLE[s as Substance] ?? {
      fg: "var(--color-ink-muted)",
      bg: "rgba(0, 0, 0, 0.04)",
      border: "var(--color-rule)",
      weight: 500,
    }
  );
}

const SUBSTANCE_HINT: Record<Substance, string> = {
  真金白银: "接了活、给了时限，动真格",
  有条件兑现: "方向认了，但缺时限或只是半应承",
  空头表态: "只表了个态、没接活没下文，多半是场面话",
};

// ---- 弦外类别徽章注脚：点破这类言下之意读者要警惕什么 ----
const SUBTEXT_HINT: Record<SubtextKind, string> = {
  表面同意实则保留: "这个同意打了折，别当真共识",
  拖延搁置: "这事被请出会议室了，大概率没下文",
  甩锅推责: "责任没落地，谁来办多半落空",
  回避问题: "他不想正面表态，问题被绕过去了",
  留口子: "给自己留了退路，不是硬承诺",
  口头答应没底: "嘴上答应但自己也没把握，可能再次落空",
};

// ---- 把握徽章样式（评估层专用——刻意不用朱砂，免得跟核验态撞色误导）----
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

// 方向徽章。
function PositionBadge({ position }: { position: string }) {
  const st = positionStyle(position);
  return (
    <span
      className="inline-flex items-center text-caption px-2 py-0.5 rounded-full whitespace-nowrap shrink-0"
      title={POSITION_HINT[position as Position] ?? ""}
      style={{
        color: st.fg,
        background: st.bg,
        border: `0.5px solid ${st.border}`,
        fontWeight: 600,
        fontFamily: "var(--font-display)",
      }}
    >
      {position}
    </span>
  );
}

// 含金量徽章——动真格的描重、场面话描淡。
function SubstanceBadge({ substance }: { substance: string }) {
  const st = substanceStyle(substance);
  return (
    <span
      className="inline-flex items-center text-caption px-2 py-0.5 rounded-full whitespace-nowrap shrink-0"
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

// 把握徽章。
function ConfidenceBadge({ confidence }: { confidence: string }) {
  if (!hasText(confidence)) return null;
  const cf = confidenceStyle(confidence);
  return (
    <span
      className="text-caption px-2 py-0.5 rounded-full whitespace-nowrap shrink-0"
      style={{ color: cf.fg, background: cf.bg }}
      title="这是研判的把握，不是核验过的事实"
    >
      把握 {confidence}
    </span>
  );
}

// ---- 原话基础（立场 / 弦外共用）：可展开，连推断都挂着引发它的原话 ----
// 视觉刻意走「引」字 + 虚线左边线，跟证据层的「原文」+ 钤印两样——这是评估层的据，不是核验态。
function BasisBlock({
  basis,
  open,
  onToggle,
}: {
  basis: string[];
  open: boolean;
  onToggle: () => void;
}) {
  const items = (basis ?? []).filter(hasText);
  if (items.length === 0) return null;
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={onToggle}
        className="text-caption text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
      >
        {open ? "收起原话" : `看引的原话（${items.length}）`}
      </button>
      {open && (
        <ul className="mt-2 space-y-1.5">
          {items.map((b, bi) => (
            <li
              key={bi}
              className="text-body-sm leading-relaxed text-[var(--color-ink-muted)] pl-3"
              style={{
                fontFamily: "var(--font-display)",
                borderLeft: "1px dashed var(--color-rule)",
              }}
            >
              <span
                className="text-caption mr-1.5 align-top text-[var(--color-ink-muted)]"
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
  );
}

export function StanceSubtext({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: StanceSubtextProps) {
  const [result, setResult] = useState<StanceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 立场 / 弦外逐条点「看引的原话」展开 basis（键 = "s_2_1" 立场 / "x_2_1" 弦外）。
  const [openBasis, setOpenBasis] = useState<Record<string, boolean>>({});

  async function load() {
    setLoading(true);
    setError(null);
    setOpenBasis({});
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/meeting/stance", {
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
      const data = (await resp.json()) as StanceResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const topics = result?.topics ?? [];
  const formNote = result?.form_note ?? "";
  // 读出了立场 / 弦外的议题，跟确证一致的议题分开统计。
  const stanceCount = useMemo(
    () => topics.reduce((n, t) => n + (t.stances?.length ?? 0), 0),
    [topics],
  );
  const subtextCount = useMemo(
    () => topics.reduce((n, t) => n + (t.subtexts?.length ?? 0), 0),
    [topics],
  );
  const calmCount = useMemo(
    () => topics.filter((t) => t.verdict === "确证一致无弦外").length,
    [topics],
  );
  // 抽到任一立场 / 弦外，或任一议题确证一致（确证无也是读过了），就算有内容。
  const gotSomething =
    topics.length > 0 && (stanceCount > 0 || subtextCount > 0 || calmCount > 0);
  // 纪要降级：form_note 非空 = 整块走降级提示，不硬显空卡。
  const degraded = hasText(formNote);

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
      立场与弦外
    </h3>
  );

  // ---- 生成按钮区（永远在顶上） ----
  const runBar = (
    <div className="mb-4">
      <button
        type="button"
        onClick={load}
        disabled={loading || !apiKey}
        className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors whitespace-nowrap"
      >
        {loading ? "研判中…" : result ? "重新研判" : "读立场与弦外"}
      </button>
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

  // ---- 评估层抬头：这一整块是研判，不是核实过的事实（护栏，最关键的一句） ----
  const judgeNote = (
    <p className="text-xs text-[var(--color-ink-muted)] mb-4 leading-relaxed">
      下面是从原话里读出来的<b>研判</b>，不是核实过的事实；底下引的原话才是事实。看它的方向就好，别当板上钉钉。
    </p>
  );

  // ---- 未生成：入口 + 按钮 ----
  if (!result) {
    return (
      <div className="pt-4">
        {header}
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          会议里大家心里怎么想，常常不写在脸上：「再研究研究」往往是不想办，「我理解但是」往往是软反对，「我尽量争取」往往是没底的敷衍。这块替你把字面底下的真实态度挖出来——谁真同意、谁附条件、谁嘴上应付实则拖延、谁在打太极。每条都钉发言原话、标把握。读出来的是研判不是核实结论，对不对你看着原话自己判。一议题大家是真一致、没有暗流，也会明说是好事。只读逐字稿；纪要读不出现场语气，会建议你传逐字稿。
        </p>
        {runBar}
        {loading && (
          <RunningProcess
            label="替你读这场会的立场与弦外"
            hint="整份会议记录喂进模型，按议题挖每个人的真实态度和言下之意，每条回原话核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没读出 + 没降级提示：优雅退场 ----
  if (!gotSomething && !degraded) {
    return (
      <div className="pt-4">
        {header}
        {runBar}
        {loading ? (
          <RunningProcess label="替你读这场会的立场与弦外" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            读过了，但没读出能钉在原话上的立场或弦外——这份可能是偏通报、没多少角力的会，或者不是会议记录。换一份逐字稿，或稍后重试。
          </p>
        )}
      </div>
    );
  }

  // ---- 已生成：总览 + 评估层抬头 + 按议题分组（立场卡 + 弦外卡） ----
  return (
    <div className="pt-4">
      {header}
      {runBar}

      {/* 题署一行：形态 · 立场几条 · 弦外几条 · 真一致几个议题 */}
      <div className="mb-3 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          {result.form === "逐字稿" ? "逐字稿" : "纪要"}
        </span>
        {stanceCount > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            立场 {stanceCount}
          </span>
        )}
        {subtextCount > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            弦外 {subtextCount}
          </span>
        )}
        {calmCount > 0 && (
          <span className="text-xs tabular-nums" style={{ color: "#3f6f4a" }}>
            真一致 {calmCount}
          </span>
        )}
      </div>

      {/* 纪要降级提示：form_note 非空就整块走这条，不硬显空卡 */}
      {degraded && (
        <div
          className="mb-5 rounded px-4 py-3 text-body-sm leading-relaxed text-[var(--color-ink)]"
          style={{
            background: "var(--color-paper-sunken)",
            border: "1px dashed var(--color-rule)",
          }}
        >
          {formNote}
        </div>
      )}

      {/* ── 总览（summary）：系统一句话，谁在推谁在拖，带立场 ── */}
      {hasText(result.summary) && (
        <div
          className="relative mb-6 rounded-r px-4 py-3.5 pl-5"
          style={{
            background: "var(--color-seal-soft)",
            borderLeft: "3px solid var(--color-seal)",
          }}
        >
          {/* 总览签：右上一枚朱砂签，点破这是带立场的总览不是中立罗列 */}
          <span
            className="absolute -top-2.5 left-4 inline-flex items-center gap-1 px-2 py-0.5 text-caption font-bold rounded"
            style={{
              color: "var(--color-paper)",
              background: "var(--color-seal)",
              fontFamily: "var(--font-display)",
              transform: "rotate(-1.5deg)",
            }}
          >
            总览 · 谁在推谁在拖
          </span>
          <p
            className="text-body leading-7 text-[var(--color-ink)] mt-1"
            style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
          >
            {result.summary}
          </p>
        </div>
      )}

      {/* 评估层抬头：整块标研判，绝不是核实结论（护栏最关键一句）。只在有卡片时显。 */}
      {gotSomething && judgeNote}

      {/* ── 按议题分组 ── */}
      <div className="space-y-6">
        {topics.map((t, ti) => (
          <TopicSection
            key={ti}
            topic={t}
            topicIndex={ti}
            openBasis={openBasis}
            onToggleBasis={(key) =>
              setOpenBasis((cur) => ({ ...cur, [key]: !cur[key] }))
            }
          />
        ))}
      </div>

      {!loading && (
        <RunStats
          trace={trace}
          note={`立场 ${stanceCount} · 弦外 ${subtextCount}${
            calmCount > 0 ? ` · 真一致 ${calmCount}` : ""
          }`}
        />
      )}
    </div>
  );
}

// ---- 一个议题：题名 + 三态分支（有张力显卡片 / 确证一致显正面 / 读不出显待核） ----
function TopicSection({
  topic,
  topicIndex,
  openBasis,
  onToggleBasis,
}: {
  topic: StanceTopic;
  topicIndex: number;
  openBasis: Record<string, boolean>;
  onToggleBasis: (key: string) => void;
}) {
  const stances = topic.stances ?? [];
  const subtexts = topic.subtexts ?? [];
  const verdict = topic.verdict;

  return (
    <section>
      {/* 议题题头：朱砂短脊 + 议题名 */}
      <div className="mb-3 flex items-baseline gap-2.5 flex-wrap">
        <span className="h-3.5 w-[3px] rounded-full bg-[var(--color-seal)] opacity-70 self-center" />
        <span
          className="text-sm font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {hasText(topic.topic) ? topic.topic : "（这条没说清是哪个议题）"}
        </span>
      </div>

      {/* 确证一致无弦外：笃定的好事，不能显得像系统漏读 */}
      {verdict === "确证一致无弦外" && stances.length === 0 && subtexts.length === 0 ? (
        <div
          className="rounded px-4 py-3 text-body-sm leading-relaxed"
          style={{
            background: "rgba(63, 111, 74, 0.07)",
            border: "0.5px solid rgba(63, 111, 74, 0.35)",
            color: "var(--color-ink)",
          }}
        >
          这件事大家是真一致，没有暗流——会开得清爽，不是没读出来。
        </div>
      ) : verdict === "读不出（纪要/待核）" &&
        stances.length === 0 &&
        subtexts.length === 0 ? (
        <p className="text-body-sm leading-relaxed text-[var(--color-ink-muted)] italic">
          这份是整理稿，读不出现场语气，立场与弦外要逐字稿才能判，建议传逐字稿。
        </p>
      ) : (
        <div className="space-y-3">
          {/* 立场卡：谁 · 态度 · 含金量 · 人话解读 · 引原话 · 把握 */}
          {stances.map((s, si) => (
            <StanceCard
              key={`s${topicIndex}_${si}`}
              stance={s}
              open={!!openBasis[`s_${topicIndex}_${si}`]}
              onToggle={() => onToggleBasis(`s_${topicIndex}_${si}`)}
            />
          ))}
          {/* 弦外卡：类别 · 谁 · 言下之意 · 引原话 · 把握 */}
          {subtexts.map((x, xi) => (
            <SubtextCard
              key={`x${topicIndex}_${xi}`}
              subtext={x}
              open={!!openBasis[`x_${topicIndex}_${xi}`]}
              onToggle={() => onToggleBasis(`x_${topicIndex}_${xi}`)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

// ---- 立场卡（评估层）：虚线框 + 降调底 + 研判标，绝不盖鉴印——跟证据层视觉两样 ----
function StanceCard({
  stance,
  open,
  onToggle,
}: {
  stance: Stance;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <article
      className="relative rounded p-3 pl-4"
      style={{
        // 评估层做法：虚线框 + 略凹降调底——和证据层的实线卡 + 盖印明显两样
        border: "1px dashed var(--color-rule)",
        background: "var(--color-paper-sunken)",
      }}
    >
      {/* 顶行：研判标 + 把握徽章 */}
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <span
          className="inline-flex items-center text-caption px-1.5 py-0.5 rounded text-[var(--color-ink-muted)] whitespace-nowrap shrink-0"
          style={{ border: "1px dashed var(--color-ink-muted)", opacity: 0.85 }}
        >
          研判 · 非核验
        </span>
        <ConfidenceBadge confidence={stance.confidence} />
      </div>

      {/* 谁 + 方向徽章 + 含金量徽章 */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span
          className="text-body font-bold text-[var(--color-ink)] leading-snug"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {hasText(stance.person) ? stance.person : "（没读出是谁）"}
        </span>
        <div className="flex items-center gap-1.5 shrink-0">
          <PositionBadge position={stance.position} />
          <SubstanceBadge substance={stance.substance} />
        </div>
      </div>

      {/* 人话解读：他其实是… */}
      {hasText(stance.reading) && (
        <p
          className="mt-2 text-body leading-relaxed text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {stance.reading}
        </p>
      )}

      {/* 含金量凭据：凭原话里哪些 marker 判这档（有没有接活 / 给时限） */}
      {hasText(stance.substance_reason) && (
        <p className="mt-1.5 text-caption leading-relaxed text-[var(--color-ink-muted)] italic">
          含金量凭据 · {stance.substance_reason}
        </p>
      )}

      {/* 引的原话：评估层也必须有据，连研判都挂着原话 */}
      <BasisBlock basis={stance.basis} open={open} onToggle={onToggle} />
    </article>
  );
}

// ---- 弦外卡（评估层）：同立场卡的虚线降调视觉，类别徽章描朱提醒「这话有弦外」 ----
function SubtextCard({
  subtext,
  open,
  onToggle,
}: {
  subtext: Subtext;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <article
      className="relative rounded p-3 pl-4"
      style={{
        border: "1px dashed var(--color-rule)",
        background: "var(--color-paper-sunken)",
      }}
    >
      {/* 顶行：研判标 + 把握徽章 */}
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <span
          className="inline-flex items-center text-caption px-1.5 py-0.5 rounded text-[var(--color-ink-muted)] whitespace-nowrap shrink-0"
          style={{ border: "1px dashed var(--color-ink-muted)", opacity: 0.85 }}
        >
          研判 · 非核验
        </span>
        <ConfidenceBadge confidence={subtext.confidence} />
      </div>

      {/* 弦外类别徽章（描朱提醒「这话有弦外」）+ 谁说的 */}
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className="inline-flex items-center text-caption px-2 py-0.5 rounded-full whitespace-nowrap shrink-0"
          title={SUBTEXT_HINT[subtext.kind as SubtextKind] ?? ""}
          style={{
            color: "#9a3a2e",
            background: "rgba(154, 58, 46, 0.1)",
            border: "0.5px solid rgba(154, 58, 46, 0.45)",
            fontWeight: 600,
            fontFamily: "var(--font-display)",
          }}
        >
          {hasText(subtext.kind) ? subtext.kind : "弦外"}
        </span>
        {hasText(subtext.person) && (
          <span
            className="text-body-sm text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {subtext.person}
          </span>
        )}
      </div>

      {/* 言下之意：他这话真正想说的是… */}
      {hasText(subtext.subtext) && (
        <p
          className="mt-2 text-body leading-relaxed text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {subtext.subtext}
        </p>
      )}

      {/* 引的原话 */}
      <BasisBlock basis={subtext.basis} open={open} onToggle={onToggle} />
    </article>
  );
}
