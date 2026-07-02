// ---------------------------------------------------------------------------
// CommitmentTracker — 跨会承诺—兑现追踪（1.7 会议垂直·杀手价值）
//
// 单场会的行动项台账只看一场会派了什么活；这块把一卷宗的好几场会摆一起，沿时间线追一条
// 承诺的下落：张三 6 月说「下周交鉴权」，到 7 月的会还没影——这种「承诺了没兑现 / 逾期」
// 追出来。这是会议分析真正比「记纪要」强的地方，跟公文跨文件的依据链网一个道理：价值不在
// 单份，在跨单元的连线。
//
// 怎么读：承诺按人分组（谁答应的归一堆），每条带一个状态——兑现 / 未兑现 / 逾期 / 进行中 /
// 未知。逾期、未兑现的描朱砂、捞到最前（这是最该追的）；点开看「在哪场会承诺的（原话）→
// 哪场更晚的会坐实的（原话）」。
//
// evidence-first（全站一个规矩，这里红线最硬）：状态必须有原文支撑。判不出兑现没就标
// 「进行中 / 未知」，绝不猜「兑现」——猜错等于骗用户说做完了，最坏。「兑现」只在更晚的会里
// 有原话坐实、且核过才给（后端守的）；核过的原话角上盖「鉴」印。逾期由后端据时限纯算，不
// 是模型拍的。
//
// 复用：跟依据链网一样吃「卷宗」（一组 session_id），从 Dossier 选；卡片风格、含金量 / 朱砂
// 视觉、SealMark 钤印都沿用 ActionLedger 那套。设计语言（数字善本案头）：朱墨双色、宋体
// var(--font-display)、留白克制——不堆古风、无 emoji。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（对着 MeetingCommitmentsResponse 写，别改后端） ----

// 兑现状态五档：兑现（更晚的会坐实做完了）/ 未兑现（坐实没做）/ 逾期（时限过了没兑现，
// 后端据 due 纯算）/ 进行中（在做没说完）/ 未知（更晚的会没再提，判不出）。
type Status = "兑现" | "未兑现" | "逾期" | "进行中" | "未知";

interface Commitment {
  cid: number;
  from_mid: number; // 哪场会承诺的（会议下标）
  from_meeting: string; // 那场会的主题
  from_date: string; // 那场会的日期
  owner: string; // 谁承诺的（空 = 没点名，绝不替它编人）
  task: string; // 答应要做的事
  due: string; // 时限（空 = 没说）
  substance: string; // 承诺当时的含金量（真金白银 / 有条件兑现 / 空头表态）
  status: Status | string;
  status_note: string; // 后端凭什么这么判（线索，不是核过的原文）
  evidence_mid: number | null; // 哪场更晚的会坐实的
  evidence_meeting: string; // 那场会的主题
  evidence: string; // 坐实状态那句原话
  evidence_verified: boolean; // 那句原话核过没
  from_evidence: string; // 承诺那句原话
  from_verified: boolean; // 承诺那句核过没
}

interface MeetingRef {
  mid: number;
  label: string;
  date: string;
}

interface CommitmentsResponse {
  commitments: Commitment[];
  meetings: MeetingRef[];
  owners: string[];
  owner: string | null; // 回显请求的 owner（我的承诺时）
  scanned: boolean;
  trace?: RunTrace;
}

interface CommitmentTrackerProps {
  bookSessionIds: string[];
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// ---- 状态徽章样式：视觉权重跟着「要不要追」走 ----
// 逾期 / 未兑现 = 朱红重（最该追）；进行中 = 中性墨；兑现 = 安定绿调；未知 = 灰弱。
// 写死语义色（状态是评级语义不是主题色），fallback 走墨色避免未知值炸掉。
interface StatusStyle {
  fg: string;
  bg: string;
  border: string;
  rail: string; // 卡左竖脊色
  railOpacity: number;
}

const STATUS_STYLE: Record<Status, StatusStyle> = {
  逾期: {
    fg: "#9a3a2e",
    bg: "rgba(154, 58, 46, 0.14)",
    border: "rgba(154, 58, 46, 0.6)",
    rail: "var(--color-seal)",
    railOpacity: 0.75,
  },
  未兑现: {
    fg: "#9a3a2e",
    bg: "rgba(154, 58, 46, 0.1)",
    border: "rgba(154, 58, 46, 0.5)",
    rail: "var(--color-seal)",
    railOpacity: 0.55,
  },
  进行中: {
    fg: "var(--color-ink)",
    bg: "rgba(58, 99, 120, 0.08)",
    border: "rgba(58, 99, 120, 0.35)",
    rail: "var(--color-ink-muted)",
    railOpacity: 0.4,
  },
  兑现: {
    fg: "#3f6f4a",
    bg: "rgba(63, 111, 74, 0.1)",
    border: "rgba(63, 111, 74, 0.45)",
    rail: "#3f6f4a",
    railOpacity: 0.5,
  },
  未知: {
    fg: "var(--color-ink-muted)",
    bg: "rgba(0, 0, 0, 0.03)",
    border: "var(--color-rule)",
    rail: "var(--color-rule)",
    railOpacity: 1,
  },
};

function statusStyle(s: string): StatusStyle {
  return (
    STATUS_STYLE[s as Status] ?? {
      fg: "var(--color-ink-muted)",
      bg: "var(--color-seal-soft)",
      border: "var(--color-rule)",
      rail: "var(--color-ink-muted)",
      railOpacity: 0.3,
    }
  );
}

// 状态一句注脚（徽章悬停），点破这条该不该追、凭什么这么判。
const STATUS_HINT: Record<Status, string> = {
  逾期: "时限过了还没兑现——最该追的一条",
  未兑现: "更晚的会里有原话说还没做 / 又被当没解决重提",
  进行中: "更晚的会里提到在做、做了一部分，但没说做完",
  兑现: "更晚的会里有原话坐实做完了（核过）",
  未知: "更晚的会里没再提，判不出下落——没硬猜成兑现",
};

// 逾期 / 未兑现是要追的黑洞（描朱砂强标）。
const NEEDS_CHASE = new Set<string>(["逾期", "未兑现"]);

function hasText(v: string | undefined | null): boolean {
  return !!v && v.trim().length > 0;
}

// 状态徽章——逾期 / 未兑现描重、兑现安定、未知淡。
function StatusBadge({ status }: { status: string }) {
  const st = statusStyle(status);
  return (
    <span
      className="inline-flex items-center text-caption px-2 py-0.5 rounded-full whitespace-nowrap shrink-0"
      title={STATUS_HINT[status as Status] ?? ""}
      style={{
        color: st.fg,
        background: st.bg,
        border: `0.5px solid ${st.border}`,
        fontWeight: NEEDS_CHASE.has(status) ? 700 : 600,
        fontFamily: "var(--font-display)",
      }}
    >
      {status}
    </span>
  );
}

export function CommitmentTracker({
  bookSessionIds,
  provider,
  apiKey,
  model,
  baseUrl,
}: CommitmentTrackerProps) {
  // 「我的承诺」输入框；空 = 看全部人的承诺。提交时随请求带给后端按身份筛。
  const [ownerInput, setOwnerInput] = useState("");
  const [result, setResult] = useState<CommitmentsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 逐条点「看是哪场会的原文」展开（键 = cid）。
  const [openEvidence, setOpenEvidence] = useState<Record<number, boolean>>({});

  const ownerTrimmed = ownerInput.trim();
  const canRun = bookSessionIds.length >= 2 && !!apiKey;

  async function load() {
    if (bookSessionIds.length < 2) return;
    setLoading(true);
    setError(null);
    setOpenEvidence({});
    try {
      const body: Record<string, unknown> = {
        book_session_ids: bookSessionIds,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      if (ownerTrimmed) body.owner = ownerTrimmed;
      const resp = await fetch("/api/agent/meeting/commitments", {
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
      const data = (await resp.json()) as CommitmentsResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const commitments = result?.commitments ?? [];
  const scanned = !!result && result.scanned;
  const filteredOwner = result?.owner ?? null;
  const meetingCount = result?.meetings?.length ?? 0;
  const gotSomething = scanned && commitments.length > 0;

  // 统计：要追的几条（逾期 + 未兑现）、兑现几条、核过几条。
  const chaseCount = useMemo(
    () => commitments.filter((c) => NEEDS_CHASE.has(c.status)).length,
    [commitments],
  );
  const fulfilledCount = useMemo(
    () => commitments.filter((c) => c.status === "兑现").length,
    [commitments],
  );
  const overdueCount = useMemo(
    () => commitments.filter((c) => c.status === "逾期").length,
    [commitments],
  );

  // 按人分组：每个 owner 一堆承诺（保持后端排序——要追的在前）。没点名 owner 的归「未指派」。
  const grouped = useMemo(() => {
    const map = new Map<string, Commitment[]>();
    for (const c of commitments) {
      const key = hasText(c.owner) ? c.owner.trim() : "（未指派）";
      const arr = map.get(key) ?? [];
      arr.push(c);
      map.set(key, arr);
    }
    // 组顺序：先按「这组有没有要追的」+ 承诺数排，未指派排末尾。
    return [...map.entries()].sort(([ka, va], [kb, vb]) => {
      if (ka === "（未指派）") return 1;
      if (kb === "（未指派）") return -1;
      const ca = va.filter((c) => NEEDS_CHASE.has(c.status)).length;
      const cb = vb.filter((c) => NEEDS_CHASE.has(c.status)).length;
      if (ca !== cb) return cb - ca;
      return vb.length - va.length;
    });
  }, [commitments]);

  // ---- 标题行 ----
  const header = (
    <h3
      className="text-base font-bold text-[var(--color-ink)] mb-1 flex items-center gap-2"
      style={{ fontFamily: "var(--font-display)" }}
    >
      <span
        className="h-4 w-[3px] rounded-full bg-[var(--color-seal)]"
        aria-hidden="true"
      />
      跨会承诺追踪
    </h3>
  );

  // ---- 我的承诺输入区 ----
  const ownerBar = (
    <div className="mb-4">
      <label
        className="block text-sm font-bold text-[var(--color-ink)] mb-1.5"
        style={{ fontFamily: "var(--font-display)" }}
      >
        我的承诺
      </label>
      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        填上你的名字，只看你答应过的事兑现没；留空就是所有人的承诺台账。
      </p>
      <div className="flex items-stretch gap-2">
        <input
          type="text"
          value={ownerInput}
          onChange={(e) => setOwnerInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canRun) load();
          }}
          placeholder="留空看全部，或填一个名字（如「作者」）"
          disabled={loading}
          className="flex-1 text-sm px-3 py-2 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] placeholder:text-[var(--color-ink-muted)] focus:outline-none focus:border-[var(--color-seal)] disabled:opacity-50"
          style={{ fontFamily: "var(--font-display)" }}
        />
        <button
          type="button"
          onClick={load}
          disabled={!canRun || loading}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors whitespace-nowrap"
        >
          {loading ? "跨会追踪中…" : result ? "重新追踪" : "开始追踪"}
        </button>
      </div>
      {error && (
        <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}
      {bookSessionIds.length < 2 && (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
          跨会追踪至少要选 2 场会。先去「卷宗」把同一条线上的几场会勾进来（如同一项目的几次周会）。
        </p>
      )}
      {bookSessionIds.length >= 2 && !apiKey && (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
          填了 API key 才能追踪。
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
          把同一条线上的好几场会摆一起，沿时间线追每条承诺的下落：谁在哪场会答应了什么、到后来的会兑现没。逾期、没兑现的捞到最前，点开能看是在哪场会承诺的、又是哪场更晚的会坐实的，都钉原文。判不出兑现没的标「进行中 / 未知」，绝不替它猜成做完了。先去「卷宗」选一组会（≥2 场）。
        </p>
        {ownerBar}
        {loading && (
          <RunningProcess
            label="逐场精读 + 跨会追承诺"
            hint="先把每场会精读成台账，再把同一个人的承诺按时间串起来，到更晚的会里找它兑现没，每条回原文核验。场次越多越慢。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没追到：优雅退场 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        {header}
        {ownerBar}
        {loading ? (
          <RunningProcess label="逐场精读 + 跨会追承诺" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            {filteredOwner
              ? `这组会里没有「${filteredOwner}」答应过的事——换个名字，或留空看所有人的承诺。`
              : scanned
                ? "读过了，但这组会里没淘出能追的承诺——可能几场会派的活太少、或彼此不是一条线上的。换一组相关的会（同一项目 / 同一议题的连续几次会），或稍后重试。"
                : "没追出可梳理的承诺——这几份可能不都是会议记录，或彼此没关联。先去「卷宗」选同一条线上的几场会（≥2 场），或稍后重试。"}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="pt-4">
      {header}
      {ownerBar}

      {/* 题署一行：几场会 · 承诺几条 · 要追几条 · 逾期几条 · 兑现几条 */}
      <div className="mb-4 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          {meetingCount} 场会
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
        <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
          承诺 {commitments.length}
        </span>
        {chaseCount > 0 && (
          <span className="text-xs tabular-nums" style={{ color: "#9a3a2e" }}>
            要追 {chaseCount}
          </span>
        )}
        {overdueCount > 0 && (
          <span className="text-xs tabular-nums" style={{ color: "#9a3a2e" }}>
            逾期 {overdueCount}
          </span>
        )}
        {fulfilledCount > 0 && (
          <span className="text-xs tabular-nums" style={{ color: "#3f6f4a" }}>
            兑现 {fulfilledCount}
          </span>
        )}
      </div>

      {/* 时间线一条：这组会按时间排（让读者知道追的是哪几场会） */}
      {result.meetings.length > 0 && (
        <div className="mb-5 flex items-center gap-1.5 flex-wrap text-caption text-[var(--color-ink-muted)]">
          {result.meetings.map((m, i) => (
            <span key={m.mid} className="inline-flex items-center gap-1.5">
              {i > 0 && <span aria-hidden>→</span>}
              <span
                className="px-1.5 py-0.5 rounded"
                style={{ background: "var(--color-paper-sunken)" }}
                title={m.label}
              >
                {hasText(m.date) ? m.date : m.label}
              </span>
            </span>
          ))}
        </div>
      )}

      {/* 按人分组：每个 owner 一段，要追的在前 */}
      <div className="space-y-6">
        {grouped.map(([owner, items]) => {
          const chase = items.filter((c) => NEEDS_CHASE.has(c.status)).length;
          return (
            <section key={owner}>
              <div className="mb-3 flex items-center gap-2.5 flex-wrap">
                <span className="h-3.5 w-[3px] rounded-full bg-[var(--color-seal)] opacity-70" />
                <span
                  className="text-sm font-bold text-[var(--color-ink)]"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {owner}
                </span>
                <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
                  承诺 {items.length}
                </span>
                {chase > 0 && (
                  <span className="text-xs tabular-nums" style={{ color: "#9a3a2e" }}>
                    要追 {chase}
                  </span>
                )}
              </div>
              <div className="space-y-3">
                {items.map((c) => (
                  <CommitmentCard
                    key={c.cid}
                    item={c}
                    open={!!openEvidence[c.cid]}
                    onToggle={() =>
                      setOpenEvidence((cur) => ({ ...cur, [c.cid]: !cur[c.cid] }))
                    }
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>

      {!loading && (
        <RunStats
          trace={trace}
          note={`承诺 ${commitments.length}${
            chaseCount > 0 ? ` · 要追 ${chaseCount}` : ""
          }${fulfilledCount > 0 ? ` · 兑现 ${fulfilledCount}` : ""}`}
        />
      )}
    </div>
  );
}

// ---- 承诺卡片：答应了什么 + 状态 + 在哪场会承诺 / 哪场坐实 + 两头原文 ----
// 要追的（逾期 / 未兑现）描朱砂虚边强标；左脊跟着状态轻重。
function CommitmentCard({
  item,
  open,
  onToggle,
}: {
  item: Commitment;
  open: boolean;
  onToggle: () => void;
}) {
  const st = statusStyle(item.status);
  const chase = NEEDS_CHASE.has(item.status);
  const canOpen = hasText(item.from_evidence) || hasText(item.evidence);
  return (
    <article
      className="relative rounded border bg-white p-3 pl-4"
      style={{
        borderColor: chase ? "rgba(154, 58, 46, 0.45)" : "var(--color-rule)",
        borderStyle: chase ? "dashed" : "solid",
      }}
    >
      {/* 状态脊 */}
      <span
        className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full"
        style={{ background: st.rail, opacity: st.railOpacity }}
        aria-hidden="true"
      />
      {/* 任务行 + 状态徽章 */}
      <div className="flex items-start justify-between gap-2">
        <p className="text-body font-bold text-[var(--color-ink)] leading-snug flex-1 min-w-0">
          {hasText(item.task) ? item.task : "（这条没说清答应做什么）"}
        </p>
        <StatusBadge status={item.status} />
      </div>

      {/* 哪场会承诺的 · 时限 */}
      <p className="mt-1.5 text-body-sm leading-relaxed text-[var(--color-ink-muted)]">
        {hasText(item.from_meeting) && (
          <>
            <span className="text-[var(--color-ink)]">承诺于</span> · {item.from_meeting}
            {hasText(item.from_date) ? `（${item.from_date}）` : ""}
          </>
        )}
        {hasText(item.from_meeting) && hasText(item.due) && "　"}
        {hasText(item.due) ? (
          <>
            <span className="text-[var(--color-ink)]">时限</span> · {item.due}
          </>
        ) : (
          <span
            className="inline-flex items-center text-caption px-1.5 py-0.5 rounded-full ml-1"
            style={{
              color: "var(--color-ink-muted)",
              border: "0.5px dashed var(--color-rule)",
            }}
          >
            没说时限
          </span>
        )}
      </p>

      {/* 后端凭什么这么判（线索，非核过原文，老实标「研判」） */}
      {hasText(item.status_note) && (
        <p className="mt-1.5 text-caption leading-relaxed text-[var(--color-ink-muted)] italic">
          研判 · {item.status_note}
        </p>
      )}

      {/* 坐实于哪场更晚的会（兑现 / 未兑现 / 进行中才有） */}
      {hasText(item.evidence_meeting) && (
        <p className="mt-1.5 text-caption leading-relaxed text-[var(--color-ink-muted)]">
          <span className="text-[var(--color-ink)]">后续见于</span> · {item.evidence_meeting}
        </p>
      )}

      {/* 原文脚：承诺那句 + 坐实那句，各自核过盖印 */}
      <div className="mt-2">
        {canOpen ? (
          <button
            type="button"
            onClick={onToggle}
            className="text-caption text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors flex items-center gap-1.5"
          >
            {(item.from_verified || item.evidence_verified) && (
              <SealMark size={15} title="原文已核验" />
            )}
            {open ? "收起原文" : "看原文出处"}
          </button>
        ) : (
          <p className="text-xs text-[var(--color-ink-muted)] italic">
            暂无贴切原文
          </p>
        )}
        {open && (
          <div className="mt-2 space-y-2.5">
            {hasText(item.from_evidence) && (
              <EvidenceLine
                tag="承诺"
                meeting={item.from_meeting}
                text={item.from_evidence}
                verified={item.from_verified}
              />
            )}
            {hasText(item.evidence) && (
              <EvidenceLine
                tag="后续"
                meeting={item.evidence_meeting}
                text={item.evidence}
                verified={item.evidence_verified}
              />
            )}
          </div>
        )}
      </div>
    </article>
  );
}

// ---- 一条原文：标这是哪场会的「承诺 / 后续」原话 + 核过盖印 ----
function EvidenceLine({
  tag,
  meeting,
  text,
  verified,
}: {
  tag: string;
  meeting: string;
  text: string;
  verified: boolean;
}) {
  return (
    <div
      className="text-body-sm leading-relaxed text-[var(--color-ink)] border-l-2 pl-3"
      style={{
        fontFamily: "var(--font-display)",
        borderColor: "var(--color-seal)",
      }}
    >
      <div className="flex items-center gap-1.5 mb-0.5">
        <span className="text-caption" style={{ color: "var(--color-seal)" }}>
          {tag}
        </span>
        {hasText(meeting) && (
          <span className="text-caption text-[var(--color-ink-muted)]">· {meeting}</span>
        )}
        {verified ? (
          <SealMark size={14} title="原文已核验" />
        ) : (
          <span className="text-caption text-[var(--color-ink-muted)]">未核验</span>
        )}
      </div>
      {text}
    </div>
  );
}
