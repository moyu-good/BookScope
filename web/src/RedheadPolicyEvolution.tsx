// ---------------------------------------------------------------------------
// RedheadPolicyEvolution — 政策演变（1.6 红头文件垂直·跨文件二炮）
//
// 一项政策很少一份文件定死——先出个意见、再出实施办法、过两年又修订。一卷宗里好几份
// 公文摆一起，这块按成文日期排出**政策怎么一步步变的**：哪份先出、改了什么、再哪份接着改，
// 每个阶段钉一句那份文件的原话。一眼看清这项政策的来龙去脉。
//
// 意象 = 政策编年 / 案卷纪年（官府办事的政策沿革），不套小说的叙事曲线、不做通用甘特图：
//   一道竖直朱砂纪年轴贯穿全程，每个阶段一枚朱砂年轮墨钉钉在轴上（编年的纪年点），
//   左边「成文日期」走日晷牌（朱砂描边纪时牌），右边「这份文件改了什么」+ 真实发文字号
//   +（核得到的）那份文件原话。阶段按成文先后从上往下排（后端排好序），轴距按成文日期的
//   真实间隔撑开（隔得久拉得开、缺日期退回均匀排），顶「起」底「讫」收束。
//   可另指定一个政策主题，只排这条线的演变。
//
// evidence-first（全站一个规矩）：阶段是后端按成文日期排的，每阶段 snippet 取那份文脉里
// 已核的原文（锚不到原文的阶段后端直接丢）。主题不在这摞文件 → 空 + scanned=true（老实说
// 「这卷宗里没这条政策线」）；一次推理失败 / 没可锚文件 → scanned=false，优雅退场。
//
// 设计语言（数字善本案头）：朱墨双色、宋体 var(--font-display)、留白克制——不堆古风、
// 无 emoji、不做成通用时间线组件。verified 的原话盖一枚「鉴」印（SealMark）。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";
import { SealButton } from "./SealButton";
import { DossierHint } from "./RedheadDependencyGraph";

// ---- 后端契约（对着 /api/agent/redhead/policy-evolution 写，别改后端） ----

interface PolicyStage {
  order: number; // 排序序（后端按成文日期排好）
  doc: string; // 真实发文字号
  date?: string; // 成文日期原文（"2024年5月8日" / "2024年5月" / "2024年"，缺则为空）
  change: string; // 这份文件改了什么 / 推进了什么
  snippet: string; // 那份文脉里已核的原文片段（锚不到的阶段后端会丢）
  verified: boolean;
}

// 措辞 diff（逐字比）——政策的新闻藏在措辞变化的 delta 里：鼓励→应当（升格）、
// 严格→合理（松绑）、某提法删了（转向）。before/after 是后端逐字核过的原话（对不上的丢），
// direction 是研判口径（套约束力阶梯判方向）。后端新增字段，老后端没有则为空、不渲染这层。
interface PolicyDiff {
  topic_point: string; // 这条 diff 针对的同一件事 / 同一提法
  before: string; // 旧措辞（逐字原话；「新增」时为空）
  before_doc: string; // 旧措辞来自哪份文件
  after: string; // 新措辞（逐字原话；「删除」时为空）
  after_doc: string; // 新措辞来自哪份文件
  direction: string; // 升格 / 松绑 / 收紧 / 转向 / 新增 / 删除
  basis: string; // 凭措辞里哪个词判的方向
  verified: boolean;
}

interface PolicyEvolutionResponse {
  stages: PolicyStage[];
  wording_diffs?: PolicyDiff[]; // 措辞 diff 层（后端新增；老后端无此字段）
  scanned: boolean;
  trace?: RunTrace;
}

// 方向标签的朱墨配色：升格 / 收紧 = 实心朱印（要紧的方向，动真格 / 加严）；
// 松绑 = 朱描边（放宽）；转向 / 新增 / 删除 = 墨描边（中性事实）。不堆色，朱墨两系。
const DIRECTION_STYLE: Record<
  string,
  { fill: boolean; tone: "seal" | "ink"; hint: string }
> = {
  升格: { fill: true, tone: "seal", hint: "约束力升：要动真格了" },
  收紧: { fill: true, tone: "seal", hint: "门槛 / 标准收窄" },
  松绑: { fill: false, tone: "seal", hint: "约束力降：放宽了" },
  转向: { fill: false, tone: "ink", hint: "提法换了方向 / 口径" },
  新增: { fill: false, tone: "ink", hint: "旧版没有、新版加上" },
  删除: { fill: false, tone: "ink", hint: "旧版有、新版删掉" },
};

// 把六种 direction 收成三类走势：收紧（约束力升——收紧 / 升格）、松绑（约束力降）、
// 中性（转向 / 新增 / 删除，或没归到前两类的）。这是政策变没变紧的**真实信号**，
// 全程只认后端逐字比出来的 direction 字段，不另发明。
type DirClass = "收紧" | "松绑" | "中性";
function classifyDirection(dir: string): DirClass {
  if (dir === "收紧" || dir === "升格") return "收紧";
  if (dir === "松绑") return "松绑";
  return "中性";
}

interface RedheadPolicyEvolutionProps {
  bookSessionIds: string[];
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

function hasText(v: string | null | undefined): boolean {
  return !!v && v.trim().length > 0;
}

// 把中文成文日期解析成一个可比较的时间数值（毫秒，Date.UTC 折算——月份长短不一也算得对）。
// 认「2024年5月8日」「2024年5月」「2024年」三种写法：缺月按当年 1 月、缺日按当月 1 日补。
// 解析不了的（空串、中文数字写法、别的格式）返回 null，交给上层按先后均匀排兜底——绝不硬猜。
function parseDocDate(raw: string | null | undefined): number | null {
  if (!raw) return null;
  const s = raw.trim();
  if (!s) return null;
  const m = s.match(/(\d{4})\s*年(?:\s*(\d{1,2})\s*月)?(?:\s*(\d{1,2})\s*日)?/);
  if (!m) return null;
  const year = parseInt(m[1], 10);
  const month = m[2] ? parseInt(m[2], 10) : 1;
  const day = m[3] ? parseInt(m[3], 10) : 1;
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return Date.UTC(year, month - 1, day);
}

export function RedheadPolicyEvolution({
  bookSessionIds,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadPolicyEvolutionProps) {
  const [result, setResult] = useState<PolicyEvolutionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [topic, setTopic] = useState("");
  // 默认收起原文，点开看撑这个阶段的那句原话
  const [openOrigin, setOpenOrigin] = useState<Record<number, boolean>>({});
  // 这次结果是不是带主题跑的——空态文案据此区分（主题没命中 vs 整卷宗没政策线）
  const [ranWithTopic, setRanWithTopic] = useState(false);

  const canRun = bookSessionIds.length >= 2 && !!apiKey;

  async function load() {
    if (bookSessionIds.length < 2) return;
    setLoading(true);
    setError(null);
    setOpenOrigin({});
    const t = topic.trim();
    setRanWithTopic(!!t);
    try {
      const body: Record<string, unknown> = {
        book_session_ids: bookSessionIds,
        provider,
        api_key: apiKey,
      };
      if (t) body.topic = t;
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/policy-evolution", {
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
      const data = (await resp.json()) as PolicyEvolutionResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const stages = result?.stages ?? [];
  const diffs = useMemo(
    () => (result?.wording_diffs ?? []).filter((d) => d.verified),
    [result],
  );
  const scanned = !!result && result.scanned;
  // 排出了阶段、或抓到了措辞 diff，都算「有料」——diff 层独立，可能阶段没排出但 diff 有
  const gotSomething = scanned && (stages.length > 0 || diffs.length > 0);
  const verifiedCount = useMemo(
    () => stages.filter((s) => s.verified && hasText(s.snippet)).length,
    [stages],
  );

  // ── 成文日期 → 真日期轴 ──
  // 先把每个阶段的成文日期解析成时间数值（解析不了为 null）。够两个能解析的，就按相邻两阶段的
  // 真实日期间隔成比例撑开轴距（隔得越久，拉得越开）；不够就退回均匀排、全没日期时另挂一句说明。
  const stageDates = useMemo(
    () => stages.map((s) => parseDocDate(s.date)),
    [stages],
  );
  const datedCount = useMemo(
    () => stageDates.filter((d) => d !== null).length,
    [stageDates],
  );
  const useDateAxis = datedCount >= 2;
  // 每个阶段头顶的间距（px）：gaps[0] 恒为 0。用真日期时按最大间隔归一到 [MIN,MAX]；
  // 相邻缺日期的一段退回均匀间距——缺数据既不崩、也不假装轴上有它的位置。
  const stageGaps = useMemo(() => {
    const EVEN = 20; // ≈ 原 space-y-5(1.25rem) 的均匀间距
    const MIN = 16;
    const MAX = 132;
    if (!useDateAxis) return stages.map((_, i) => (i === 0 ? 0 : EVEN));
    let maxDelta = 0;
    for (let i = 1; i < stages.length; i++) {
      const a = stageDates[i - 1];
      const b = stageDates[i];
      if (a !== null && b !== null) {
        const d = Math.abs(b - a);
        if (d > maxDelta) maxDelta = d;
      }
    }
    return stages.map((_, i) => {
      if (i === 0) return 0;
      const a = stageDates[i - 1];
      const b = stageDates[i];
      if (a === null || b === null || maxDelta === 0) return EVEN;
      const ratio = Math.abs(b - a) / maxDelta;
      return Math.round(MIN + ratio * (MAX - MIN));
    });
  }, [stages, stageDates, useDateAxis]);

  // 措辞变化按走势分三组（收紧 / 中性 / 松绑），既给下方分带排布，也给上方走势条数数。
  const diffByClass = useMemo(() => {
    const g: Record<DirClass, PolicyDiff[]> = { 收紧: [], 中性: [], 松绑: [] };
    for (const d of diffs) g[classifyDirection(d.direction)].push(d);
    return g;
  }, [diffs]);

  // 每份文件（按发文字号）收到的措辞变化归到它名下——after_doc 是「新措辞来自哪份」，
  // 所以一条 diff 记在它落地的那份文件头上。timeline 上每个阶段据此标它相对上一份是收还是松。
  const dirByDoc = useMemo(() => {
    const m = new Map<string, { 收紧: number; 松绑: number; 中性: number }>();
    for (const d of diffs) {
      const doc = (d.after_doc || "").trim();
      if (!doc) continue;
      const cls = classifyDirection(d.direction);
      const cur = m.get(doc) ?? { 收紧: 0, 松绑: 0, 中性: 0 };
      cur[cls] += 1;
      m.set(doc, cur);
    }
    return m;
  }, [diffs]);

  // 某份文件的净走势：收紧多于松绑记「收紧」、反之「松绑」、两头相当或只有转向增删记「中性」。
  // 取不到（这份没匹配的 diff）返回 null——不硬凑箭头，没数据就不标。
  function netDirOfDoc(
    doc: string,
  ): { cls: DirClass; mixed: boolean } | null {
    const c = dirByDoc.get((doc || "").trim());
    if (!c) return null;
    if (c.收紧 + c.松绑 + c.中性 === 0) return null;
    if (c.收紧 > c.松绑) return { cls: "收紧", mixed: c.松绑 > 0 };
    if (c.松绑 > c.收紧) return { cls: "松绑", mixed: c.收紧 > 0 };
    if (c.收紧 > 0) return { cls: "中性", mixed: true }; // 收松相当 = 有紧有松
    return { cls: "中性", mixed: false };
  }

  // ---- 未生成：入口卡片（带主题输入框） ----
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
          政策演变
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          把一卷宗里好几份公文按成文日期排成一条线——哪份先出、改了什么、再哪份接着改，看一项政策是怎么一步步演变到现在的，每个阶段钉一句那份文件的原话。可以只盯一个主题排（比如「补贴标准」），也可整卷宗排。阶段是按成文日期排的、原话从原文锚出来的，绝不替你脑补先后。适合一组同主题、有先后的党政公文。
        </p>
        <DossierHint count={bookSessionIds.length} />
        <div className="mt-3 mb-1">
          <label className="block text-xs text-[var(--color-ink-muted)] mb-1.5">
            盯一个政策主题（可空，空则整卷宗排）
          </label>
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="如：补贴标准 / 审批流程 / 适用范围"
            className="w-full max-w-md text-sm px-3 py-2 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] focus:border-[var(--color-seal)] focus:outline-none"
            style={{ fontFamily: "var(--font-display)" }}
          />
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading || !canRun}
          className="mt-2 text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读这卷宗排政策演变中（约 1-2 分钟）…" : "排出政策演变"}
        </button>
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {loading && (
          <RunningProcess
            label="读这卷宗排政策演变"
            hint="卷宗里每份公文各建文脉，再按成文日期排出演变阶段，每阶段标改了什么、钉一句原话，约 1-2 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没排出：优雅退场，区分「主题没命中」和「整卷宗没政策线」 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        <ViewHeader title="政策演变" loading={loading} onReload={load} />
        {loading ? (
          <RunningProcess label="读这卷宗排政策演变" />
        ) : scanned ? (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            {ranWithTopic
              ? "这卷宗里没排出这个主题的演变线，可能这几份文件没都谈到它，或者主题换个说法再试（比如把「补贴」换成原文里的准确叫法）。也可以清空主题、整卷宗排一遍看看。"
              : "没排出政策演变，这卷宗里的公文可能不是同一项政策的不同阶段，或者彼此没有先后承继关系。挑一组同主题、有先后的公文（比如意见 + 实施办法 + 修订版），再试一次。"}
          </p>
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            没排出政策演变——没有能锚回原文的真实文件，或者这几份文件凑不出一条政策线。挑一组同主题、有先后的公文再试一次。
          </p>
        )}
      </div>
    );
  }

  // ---- 已排出：政策编年时序 ----
  return (
    <div className="pt-4">
      <ViewHeader title="政策演变" loading={loading} onReload={load} />

      {/* 题署：编年 · 几个阶段 · 原文核验几个 · 措辞变化几处 */}
      <div className="mb-4 flex items-center gap-2 flex-wrap">
        {stages.length > 0 && (
          <>
            <span
              className="inline-block text-xs px-2 py-0.5 rounded-full"
              style={{
                color: "var(--color-seal)",
                border: "0.5px solid var(--color-seal)",
              }}
            >
              政策编年 · {stages.length} 个阶段
            </span>
            <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
              原文核验 {verifiedCount}/{stages.length}
            </span>
          </>
        )}
        {diffs.length > 0 && (
          <span
            className="inline-block text-xs px-2 py-0.5 rounded-full"
            style={{ color: "var(--color-seal)", border: "0.5px solid var(--color-seal)" }}
          >
            措辞变化 · {diffs.length} 处
          </span>
        )}
        {ranWithTopic && hasText(topic) && (
          <span className="text-xs text-[var(--color-ink-muted)]">
            主题 ·{" "}
            <span className="text-[var(--color-ink)]">{topic.trim()}</span>
          </span>
        )}
      </div>

      {/* ── 政策编年：竖直朱砂纪年轴 + 每阶段年轮墨钉 ── */}
      {stages.length > 0 && (
      <>
      {/* 轴距怎么排的，据成文日期有没有如实告诉读者，绝不假装有真日期 */}
      <p className="text-xs text-[var(--color-ink-muted)] mb-3 leading-relaxed">
        {useDateAxis
          ? "轴距按成文日期的真实间隔排——两份文件隔得越久，在轴上拉得越开。"
          : datedCount === 0
            ? "这组文件没标成文日期，按公文先后顺序均匀排（不代表真实时间间隔）。"
            : "只有一份标了成文日期，排不出时间间隔，按先后顺序均匀排。"}
      </p>
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

        <ol>
          {stages.map((s, i) => {
            const verified = s.verified && hasText(s.snippet);
            const isOpen = !!openOrigin[i];
            const canOpenOrigin = hasText(s.snippet);
            const first = i === 0;
            const last = i === stages.length - 1;
            // 这份相对上一份是收紧还是松绑——只在下方措辞变化真给出方向时才标。
            const dir = netDirOfDoc(s.doc);
            return (
              <li
                key={i}
                className="relative flex items-stretch gap-0"
                style={{ marginTop: i === 0 ? undefined : stageGaps[i] }}
              >
                {/* 左栏：日晷牌——有成文日期就把日期当纪时牌主角、字号缩小垫底；没日期退回拿字号当纪年牌 */}
                <div className="shrink-0 pt-0.5" style={{ width: "6rem" }}>
                  <div
                    className="inline-flex flex-col items-end text-right rounded px-2 py-1 leading-tight"
                    style={{
                      border: "0.5px solid var(--color-seal)",
                      background: "var(--color-seal-soft)",
                      fontFamily: "var(--font-display)",
                    }}
                  >
                    {hasText(s.date) ? (
                      <>
                        <span
                          className="text-caption font-bold tabular-nums break-all"
                          style={{ color: "var(--color-seal)" }}
                        >
                          {s.date}
                        </span>
                        {hasText(s.doc) && (
                          <span className="mt-0.5 text-caption text-[var(--color-ink-muted)] break-all leading-tight">
                            {s.doc}
                          </span>
                        )}
                      </>
                    ) : (
                      <span
                        className="text-caption font-bold tabular-nums break-all"
                        style={{ color: "var(--color-seal)" }}
                      >
                        {hasText(s.doc) ? s.doc : `第 ${s.order ?? i + 1} 阶段`}
                      </span>
                    )}
                  </div>
                </div>

                {/* 中栏：年轮墨钉钉在轴上。起 / 讫两端加横规。 */}
                <div className="w-4 shrink-0 flex flex-col items-center relative">
                  {first && (
                    <span
                      aria-hidden
                      className="absolute -top-1 h-px w-3"
                      style={{ background: "var(--color-seal)", opacity: 0.6 }}
                    />
                  )}
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
                  {last && (
                    <span
                      aria-hidden
                      className="absolute -bottom-1 h-px w-3"
                      style={{ background: "var(--color-seal)", opacity: 0.6 }}
                    />
                  )}
                </div>

                {/* 右栏：这份文件改了什么 + 原话（默认收起） */}
                <div className="flex-1 min-w-0 pl-3 pb-1">
                  <div className="flex items-start gap-2">
                    {verified && <SealMark size={17} title="原文已核验" />}
                    <p
                      className="text-body leading-7 text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {hasText(s.change)
                        ? s.change
                        : "（这一阶段没说改了什么）"}
                    </p>
                  </div>

                  {dir && !first && (
                    <div className="mt-1.5">
                      <DirChip cls={dir.cls} mixed={dir.mixed} />
                    </div>
                  )}

                  {!verified && (
                    <p className="mt-1 text-xs text-[var(--color-ink-muted)] italic">
                      {hasText(s.snippet)
                        ? "未在原文比对命中·仅供参考"
                        : "暂无贴切原文（待核）"}
                    </p>
                  )}

                  {canOpenOrigin && (
                    <div className="mt-1.5">
                      <button
                        type="button"
                        onClick={() =>
                          setOpenOrigin((cur) => ({ ...cur, [i]: !cur[i] }))
                        }
                        className="text-caption text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                      >
                        {isOpen ? "收起原文" : "看原文出处"}
                      </button>
                      {isOpen && (
                        <p
                          className="mt-1.5 text-body-sm leading-relaxed text-[var(--color-ink)] border-l-2 pl-3"
                          style={{
                            borderColor:
                              "color-mix(in oklch, var(--color-seal) 40%, transparent)",
                            fontFamily: "var(--font-display)",
                          }}
                        >
                          {s.snippet}
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
      </>
      )}

      {/* ── 措辞 diff（逐字比）：政策的新闻在 delta 里 ── */}
      {diffs.length > 0 && (
        <div className={stages.length > 0 ? "mt-7" : ""}>
          <div className="flex items-baseline gap-2 mb-1">
            <h4
              className="text-sm font-bold text-[var(--color-ink)] flex items-center gap-2"
              style={{ fontFamily: "var(--font-display)" }}
            >
              <span
                className="h-3.5 w-[3px] rounded-full bg-[var(--color-seal)]"
                aria-hidden="true"
              />
              措辞变化
            </h4>
            <span className="text-xs text-[var(--color-ink-muted)]">
              逐字比，新闻在改了的词里
            </span>
          </div>
          <p className="text-xs text-[var(--color-ink-muted)] mb-3 leading-relaxed">
            同一件事跨文件措辞变了的地方——旧措辞、新措辞逐字摆出来。按走势分三层排：往上是
            <b style={{ color: "var(--color-seal)" }}>收紧</b>（约束力升，动真格），往下是{" "}
            <b>松绑</b>（约束力降，放宽了），中间是转向 / 增删。两边的原话都从原文逐字锚出来、核过才留。
          </p>
          <TrendBar
            tighten={diffByClass.收紧.length}
            loosen={diffByClass.松绑.length}
            neutral={diffByClass.中性.length}
          />
          <div className="mt-4 space-y-4">
            <DiffBand cls="收紧" diffs={diffByClass.收紧} />
            <DiffBand cls="中性" diffs={diffByClass.中性} />
            <DiffBand cls="松绑" diffs={diffByClass.松绑} />
          </div>
        </div>
      )}

      {!loading && (
        <RunStats
          trace={trace}
          note={
            `政策编年 ${stages.length} 个阶段 · 原文核验 ${verifiedCount}` +
            (diffs.length > 0 ? ` · 措辞变化 ${diffs.length} 处` : "")
          }
        />
      )}
    </div>
  );
}

// 一条措辞 diff：topic_point + 方向印 + 旧措辞 →(朱砂) 新措辞（逐字、盖鉴印）+ basis。
function DiffCard({ diff }: { diff: PolicyDiff }) {
  const ds = DIRECTION_STYLE[diff.direction] ?? {
    fill: false,
    tone: "ink" as const,
    hint: "",
  };
  const hasBefore = hasText(diff.before);
  const hasAfter = hasText(diff.after);
  return (
    <li
      className="rounded border p-3"
      style={{
        borderColor: "var(--color-rule)",
        background: "var(--color-paper)",
      }}
    >
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <DirectionBadge direction={diff.direction} style={ds} />
        {hasText(diff.topic_point) && (
          <span
            className="text-body-sm font-bold text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {diff.topic_point}
          </span>
        )}
      </div>

      {/* 旧措辞 → 新措辞：逐字原话，各盖鉴印 + 标来自哪份 */}
      <div className="space-y-1.5">
        {hasBefore && (
          <WordingLine
            tag="旧"
            text={diff.before}
            doc={diff.before_doc}
            tone="muted"
          />
        )}
        {hasAfter && (
          <WordingLine
            tag="新"
            text={diff.after}
            doc={diff.after_doc}
            tone="ink"
          />
        )}
      </div>

      {hasText(diff.basis) && (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)] leading-relaxed">
          {diff.basis}
        </p>
      )}
    </li>
  );
}

// 时序上一枚方向签：↑ 朱 = 较上一份收紧，↓ 墨 = 松绑，→ 淡墨 = 转向 / 增删（或有紧有松）。
function DirChip({ cls, mixed }: { cls: DirClass; mixed: boolean }) {
  const tight = cls === "收紧";
  const loose = cls === "松绑";
  const color = tight
    ? "var(--color-seal)"
    : loose
      ? "var(--color-ink)"
      : "var(--color-ink-muted)";
  const arrow = tight ? "↑" : loose ? "↓" : "→";
  const label =
    cls === "中性"
      ? mixed
        ? "较上一份有紧有松"
        : "较上一份转向 / 增删"
      : `较上一份${cls}${mixed ? "为主" : ""}`;
  return (
    <span
      className="inline-flex items-center gap-1 text-caption px-1.5 py-0.5 rounded"
      title="据下方「措辞变化」逐字比研判：约束力升记收紧、降记松绑"
      style={{
        color,
        border: `0.5px solid ${color}`,
        fontFamily: "var(--font-display)",
      }}
    >
      <span aria-hidden style={{ fontWeight: 700 }}>
        {arrow}
      </span>
      {label}
    </span>
  );
}

// 走势条：一根中线，松绑往左（墨）、收紧往右（朱），条长按条数归一。
// 一眼看这项政策整体在收还是在松——数的是下面三带各有几条 diff，不另造分。
function TrendBar({
  tighten,
  loosen,
  neutral,
}: {
  tighten: number;
  loosen: number;
  neutral: number;
}) {
  const max = Math.max(1, tighten, loosen);
  const verdict =
    tighten > loosen
      ? "整体在收紧"
      : loosen > tighten
        ? "整体在松绑"
        : tighten > 0
          ? "有紧有松"
          : "多为转向 / 增删";
  return (
    <div className="mb-1">
      <div className="flex items-center gap-2.5 mb-1.5 text-caption text-[var(--color-ink-muted)] flex-wrap tabular-nums">
        <span>松绑 {loosen}</span>
        <span style={{ color: "var(--color-seal)" }}>收紧 {tighten}</span>
        {neutral > 0 && <span>转向 / 增删 {neutral}</span>}
        <span className="text-[var(--color-ink)] font-bold not-italic">
          {verdict}
        </span>
      </div>
      <div
        className="relative h-3 rounded overflow-hidden"
        style={{ background: "var(--color-paper-sunken)" }}
      >
        {/* 松绑：从中线往左长 */}
        <div
          className="absolute top-0 bottom-0 flex justify-end"
          style={{ left: 0, width: "50%" }}
        >
          <div
            style={{
              width: `${(loosen / max) * 100}%`,
              background: "var(--color-ink)",
              opacity: 0.5,
            }}
          />
        </div>
        {/* 收紧：从中线往右长 */}
        <div
          className="absolute top-0 bottom-0"
          style={{ left: "50%", width: "50%" }}
        >
          <div
            style={{
              height: "100%",
              width: `${(tighten / max) * 100}%`,
              background: "var(--color-seal)",
              opacity: 0.72,
            }}
          />
        </div>
        {/* 中线 */}
        <div
          className="absolute top-0 bottom-0 left-1/2 w-px"
          style={{ background: "var(--color-rule)" }}
        />
      </div>
    </div>
  );
}

// 一条走势带：左侧方向轨（↑ 收紧朱 / ↓ 松绑墨 / → 中性淡墨）+ 右侧这一走势下的逐条 diff。
// 收紧带排最上、松绑最下——位置本身就是「政策往哪个方向走」的编码。
function DiffBand({ cls, diffs }: { cls: DirClass; diffs: PolicyDiff[] }) {
  if (diffs.length === 0) return null;
  const tight = cls === "收紧";
  const loose = cls === "松绑";
  const color = tight
    ? "var(--color-seal)"
    : loose
      ? "var(--color-ink)"
      : "var(--color-ink-muted)";
  const arrow = tight ? "↑" : loose ? "↓" : "→";
  const title = tight ? "收紧 / 升格" : loose ? "松绑" : "转向 · 增删";
  const sub = tight
    ? "约束力升，要动真格 / 门槛收窄"
    : loose
      ? "约束力降，放宽了"
      : "换了方向或增删提法";
  return (
    <div className="flex gap-3">
      <div
        className="shrink-0 flex flex-col items-center"
        style={{ width: "1.75rem" }}
      >
        <span
          aria-hidden
          style={{ color, fontWeight: 700, fontSize: 18, lineHeight: 1 }}
        >
          {arrow}
        </span>
        <span
          className="flex-1 rounded-full mt-1"
          style={{
            width: "2px",
            background: color,
            opacity: tight || loose ? 0.5 : 0.3,
          }}
        />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-2 flex-wrap">
          <span
            className="text-body-sm font-bold"
            style={{
              color: tight || loose ? color : "var(--color-ink)",
              fontFamily: "var(--font-display)",
            }}
          >
            {title}
          </span>
          <span className="text-caption text-[var(--color-ink-muted)]">
            {sub}
          </span>
          <span className="text-caption text-[var(--color-ink-muted)] tabular-nums">
            {diffs.length}
          </span>
        </div>
        <ul className="space-y-3">
          {diffs.map((d, i) => (
            <DiffCard key={i} diff={d} />
          ))}
        </ul>
      </div>
    </div>
  );
}

function DirectionBadge({
  direction,
  style,
}: {
  direction: string;
  style: { fill: boolean; tone: "seal" | "ink"; hint: string };
}) {
  const accent =
    style.tone === "seal" ? "var(--color-seal)" : "var(--color-ink)";
  return (
    <span
      title={style.hint || undefined}
      className="inline-flex items-center text-caption px-1.5 py-0.5 rounded font-bold shrink-0"
      style={{
        fontFamily: "var(--font-display)",
        color: style.fill ? "var(--color-paper)" : accent,
        background: style.fill ? accent : "transparent",
        border: `0.5px solid ${accent}`,
      }}
    >
      {direction}
    </span>
  );
}

function WordingLine({
  tag,
  text,
  doc,
  tone,
}: {
  tag: string;
  text: string;
  doc: string;
  tone: "muted" | "ink";
}) {
  return (
    <div className="flex items-start gap-2">
      <span
        className="text-caption mt-1 px-1 rounded shrink-0 leading-tight"
        style={{
          color: "var(--color-ink-muted)",
          border: "0.5px solid var(--color-rule)",
          fontFamily: "var(--font-display)",
        }}
      >
        {tag}
      </span>
      <SealMark size={15} title="原文逐字已核验" className="mt-0.5" />
      <div className="min-w-0">
        <span
          className="text-body-sm leading-relaxed"
          style={{
            fontFamily: "var(--font-display)",
            color:
              tone === "ink" ? "var(--color-ink)" : "var(--color-ink-muted)",
          }}
        >
          {text}
        </span>
        {hasText(doc) && (
          <span className="ml-2 text-caption text-[var(--color-ink-muted)] tabular-nums break-all">
            — {doc}
          </span>
        )}
      </div>
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
      <SealButton
        size="sm"
        label="重新生成"
        loadingLabel="重出中…"
        loading={loading}
        onClick={onReload}
      />
    </div>
  );
}
