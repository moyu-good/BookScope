// ---------------------------------------------------------------------------
// 改稿清单 · 纯 localStorage 持久化 + 诊断发现聚合
//
// 把各诊断面板（一致性 / 伏笔 / 节奏 / 文体）跑出来的发现，归一成一份带三态
// （待改 / 已改 / 不改）的修改清单，每条挂原文证据，可导出 markdown。
//
// 存储 key：bookscope_revision_list_v1
// 结构：{ [bookSessionId]: RevisionItem[] }
//
// evidence-first 硬约束（见 WP-revision-loop §4）：
// - 每条清单项必须挂至少一处原文证据（evidence[0].snippet 非空）
// - 核不过证据的诊断发现不进清单（聚合时按 verified 过滤）
//
// 容错原则（沿用 historyStorage.ts）：
// - localStorage 不可用（SSR / 隐私模式 / quota 满）时所有方法返默认值不抛错
// - JSON 损坏 → 视为空对象重新开始
// ---------------------------------------------------------------------------

/** 三态：待改 / 已改 / 不改——纯前端状态，WP 未要求后端持久化 */
export type RevisionStatus = "todo" | "done" | "wontfix";

/** 发现来源类型——决定清单里的分类标签 */
export type FindingCategory =
  | "consistency" // 设定矛盾
  | "foreshadow" // 断掉的伏笔
  | "pacing" // 节奏塌陷段
  | "style"; // 文体毛病

/** 一处原文证据：章号 + 摘录 + 是否核验过 */
export interface Evidence {
  chapter: number;
  snippet: string;
  /** 来源诊断的核验位（verify_citations 给）；跨章发现可能两处都带 */
  verified?: boolean;
  /** 这处证据是「问题处」还是它牵连的「另一处」（伏笔回收点 / 矛盾对照面） */
  role?: "primary" | "counterpart";
}

export interface RevisionItem {
  id: string;
  category: FindingCategory;
  /** 一句话问题描述 */
  problem: string;
  /** 原文证据，至少一处；跨章类（矛盾 / 伏笔）带两处 */
  evidence: Evidence[];
  status: RevisionStatus;
  /** ISO 8601 UTC 加入清单的时间戳 */
  created_at: string;
  /**
   * 去重指纹：同一发现重复加入时不再生成新条目（按 category + 章号 + 问题前缀）。
   * 聚合「3 次取众数」的稳定性闸落在调用方，这里只防同一条重复入列。
   */
  fingerprint: string;
}

export type RevisionMap = Record<string, RevisionItem[]>;

const STORAGE_KEY = "bookscope_revision_list_v1";

export const CATEGORY_LABEL: Record<FindingCategory, string> = {
  consistency: "矛盾",
  foreshadow: "伏笔",
  pacing: "节奏",
  style: "文体",
};

function getStorage(): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    const ls = window.localStorage;
    const probe = "__bookscope_probe__";
    ls.setItem(probe, "1");
    ls.removeItem(probe);
    return ls;
  } catch {
    return null;
  }
}

function isEvidence(value: unknown): value is Evidence {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.chapter === "number" && typeof v.snippet === "string";
}

function isRevisionItem(value: unknown): value is RevisionItem {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === "string" &&
    typeof v.category === "string" &&
    typeof v.problem === "string" &&
    Array.isArray(v.evidence) &&
    v.evidence.length > 0 &&
    v.evidence.every(isEvidence) &&
    (v.status === "todo" || v.status === "done" || v.status === "wontfix") &&
    typeof v.created_at === "string" &&
    typeof v.fingerprint === "string"
  );
}

export function loadRevision(): RevisionMap {
  const ls = getStorage();
  if (!ls) return {};
  try {
    const raw = ls.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const result: RevisionMap = {};
    for (const [key, value] of Object.entries(
      parsed as Record<string, unknown>,
    )) {
      if (!Array.isArray(value)) continue;
      const items = value.filter(isRevisionItem);
      if (items.length > 0) result[key] = items;
    }
    return result;
  } catch {
    return {};
  }
}

export function saveRevision(data: RevisionMap): void {
  const ls = getStorage();
  if (!ls) return;
  try {
    ls.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // quota 满或其他异常 → 静默放弃，不影响主流程
  }
}

export function getItems(bookSessionId: string): RevisionItem[] {
  if (!bookSessionId) return [];
  return loadRevision()[bookSessionId] ?? [];
}

export function saveItems(bookSessionId: string, items: RevisionItem[]): void {
  if (!bookSessionId) return;
  const data = loadRevision();
  if (items.length === 0) {
    const { [bookSessionId]: _omit, ...rest } = data;
    void _omit;
    saveRevision(rest);
  } else {
    saveRevision({ ...data, [bookSessionId]: items });
  }
}

export function newItemId(): string {
  try {
    if (
      typeof crypto !== "undefined" &&
      typeof crypto.randomUUID === "function"
    ) {
      return crypto.randomUUID();
    }
  } catch {
    // 非安全上下文里访问 crypto 会抛
  }
  return `rev_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * 去重指纹：同一发现（同类 + 同首章 + 同问题前缀）再次加入时不另起新条目。
 * 不区分大小写空白——靠 category 把不同维度的发现隔开。
 */
function fingerprintOf(category: FindingCategory, item: NewFinding): string {
  const firstChapter = item.evidence[0]?.chapter ?? 0;
  const head = item.problem.replace(/\s+/g, "").slice(0, 40);
  return `${category}:${firstChapter}:${head}`;
}

// ---------------------------------------------------------------------------
// 聚合：把诊断端点的原始返回，归一成「过证据」的清单项候选
//
// 各诊断的返回形态（与 ConsistencyScan / ForeshadowArcs / PacingCurve /
// StyleIssues 组件里的 interface 对齐）：
//   - consistency-scan : { contradictions: [{ topic, conflict, a, b }] }
//   - foreshadow-arcs  : { arcs: [{ description, setup_*, payoff_*, status }] }
//   - pacing-curve     : { points: [{ chapter, tension, note }] }
//   - style-issues     : { issues: [{ type, what, chapter, snippet, verified }] }
//
// evidence-first：核不过原文的发现一律不进候选。
//   - 一致性 / 文体：要求 verified 为 true（BE 已把编的滤掉，这里再焊一道）
//   - 伏笔：只收「断弧」（埋了没回收 = 真要补的坑），且埋点要 verified
//   - 节奏：只收张力塌陷段（tension <= PACING_SLUMP_TENSION），note 当证据，章号即原文出处
// ---------------------------------------------------------------------------

/** 还没落盘的发现候选——交给 mergeFindings 去重 + 配 id/时间戳 */
export interface NewFinding {
  category: FindingCategory;
  problem: string;
  evidence: Evidence[];
}

/** 节奏塌陷阈值：张力 <= 此值算「松到该看一眼」——保守取 1，只挑最塌的 */
export const PACING_SLUMP_TENSION = 1;

interface ConsistencySide {
  snippet: string;
  chapter: number;
  verified?: boolean;
}
interface RawContradiction {
  topic?: string;
  conflict?: string;
  a?: ConsistencySide;
  b?: ConsistencySide;
}
interface RawArc {
  description?: string;
  setup_chapter?: number;
  payoff_chapter?: number | null;
  setup_evidence?: string;
  payoff_evidence?: string;
  status?: string;
  setup_verified?: boolean;
  payoff_verified?: boolean;
}
interface RawPacingPoint {
  chapter?: number;
  tension?: number;
  note?: string;
}
interface RawStyleIssue {
  type?: string;
  what?: string;
  chapter?: number;
  snippet?: string;
  verified?: boolean;
}

const STYLE_TYPE_LABEL: Record<string, string> = {
  repetition: "用词重复",
  pov: "视角越界",
  dropped_thread: "支线失踪",
};

function hasSnippet(s?: string): s is string {
  return typeof s === "string" && s.trim().length > 0;
}

/** 一致性矛盾 → 候选：两面都要核验过 + 都有原文，否则丢 */
export function findingsFromConsistency(
  contradictions: RawContradiction[],
): NewFinding[] {
  const out: NewFinding[] = [];
  for (const c of contradictions) {
    const a = c.a;
    const b = c.b;
    if (!a || !b) continue;
    if (!a.verified || !b.verified) continue; // 核不过不进清单
    if (!hasSnippet(a.snippet) || !hasSnippet(b.snippet)) continue;
    const problem = c.conflict?.trim() || c.topic?.trim() || "前后设定矛盾";
    out.push({
      category: "consistency",
      problem,
      evidence: [
        { chapter: a.chapter, snippet: a.snippet, verified: true, role: "primary" },
        {
          chapter: b.chapter,
          snippet: b.snippet,
          verified: true,
          role: "counterpart",
        },
      ],
    });
  }
  return out;
}

/** 伏笔 → 候选：只收断弧（埋了没回收），埋点要核验过 + 有原文 */
export function findingsFromForeshadow(arcs: RawArc[]): NewFinding[] {
  const out: NewFinding[] = [];
  for (const arc of arcs) {
    if (arc.status !== "dangling") continue; // 已回收的不是要改的坑
    if (!arc.setup_verified) continue; // 埋点核不过不进清单
    if (!hasSnippet(arc.setup_evidence)) continue;
    if (typeof arc.setup_chapter !== "number") continue;
    const desc = arc.description?.trim() || "一条伏笔";
    out.push({
      category: "foreshadow",
      problem: `埋了没回收的伏笔：${desc}`,
      evidence: [
        {
          chapter: arc.setup_chapter,
          snippet: arc.setup_evidence,
          verified: true,
          role: "primary",
        },
      ],
    });
  }
  return out;
}

/**
 * 节奏 → 候选：只挑张力塌陷段（tension <= PACING_SLUMP_TENSION）。
 * note 即逐章判断依据，章号即原文出处——节奏曲线本身就是逐章过原文跑出来的，
 * 这里把「最松的那几章」拎出来当待审项，不灌中等张力的章。
 */
export function findingsFromPacing(points: RawPacingPoint[]): NewFinding[] {
  const out: NewFinding[] = [];
  for (const p of points) {
    if (typeof p.chapter !== "number" || typeof p.tension !== "number") continue;
    if (p.tension > PACING_SLUMP_TENSION) continue;
    if (!hasSnippet(p.note)) continue; // 没依据不进清单
    out.push({
      category: "pacing",
      problem: `节奏偏松（张力 ${p.tension}/5）：${p.note}`,
      evidence: [
        { chapter: p.chapter, snippet: p.note, verified: true, role: "primary" },
      ],
    });
  }
  return out;
}

/** 文体毛病 → 候选：要核验过 + 有原文 */
export function findingsFromStyle(issues: RawStyleIssue[]): NewFinding[] {
  const out: NewFinding[] = [];
  for (const it of issues) {
    if (!it.verified) continue; // 核不过不进清单
    if (!hasSnippet(it.snippet)) continue;
    if (typeof it.chapter !== "number") continue;
    const typeLabel = it.type ? STYLE_TYPE_LABEL[it.type] ?? it.type : "文体毛病";
    const what = it.what?.trim() || typeLabel;
    out.push({
      category: "style",
      problem: `${typeLabel}：${what}`,
      evidence: [
        { chapter: it.chapter, snippet: it.snippet, verified: true, role: "primary" },
      ],
    });
  }
  return out;
}

/**
 * 把一批候选并入已有清单：去重（按指纹）、配 id + 时间戳、保留旧条目的三态。
 *
 * 返回 { items, added } —— added 是真正新增的条数，给 UI 报「加了 N 条」。
 * 已在清单里的同一发现不重复加（指纹命中即跳过，保留用户在旧条目上勾的三态）。
 */
export function mergeFindings(
  existing: RevisionItem[],
  findings: NewFinding[],
): { items: RevisionItem[]; added: number } {
  const seen = new Set(existing.map((it) => it.fingerprint));
  const now = new Date().toISOString();
  const additions: RevisionItem[] = [];
  for (const f of findings) {
    if (!f.evidence.length || !hasSnippet(f.evidence[0]?.snippet)) continue; // evidence-first 兜底
    const fp = fingerprintOf(f.category, f);
    if (seen.has(fp)) continue;
    seen.add(fp);
    additions.push({
      id: newItemId(),
      category: f.category,
      problem: f.problem,
      evidence: f.evidence,
      status: "todo",
      created_at: now,
      fingerprint: fp,
    });
  }
  return { items: [...existing, ...additions], added: additions.length };
}

// ---------------------------------------------------------------------------
// 导出 markdown：标题 = 书名 + 日期，正文按类分组，每条带章号 + 原文 + 三态。
// 复用 AnswerBlock.exportMarkdown 的 blob 下载机制（调用方触发），这里只拼正文。
// ---------------------------------------------------------------------------

const STATUS_LABEL: Record<RevisionStatus, string> = {
  todo: "待改",
  done: "已改",
  wontfix: "不改",
};

const CATEGORY_ORDER: FindingCategory[] = [
  "consistency",
  "foreshadow",
  "pacing",
  "style",
];

const CATEGORY_SECTION: Record<FindingCategory, string> = {
  consistency: "前后矛盾",
  foreshadow: "断掉的伏笔",
  pacing: "节奏偏松",
  style: "文体毛病",
};

/** 把清单拼成可带走的 markdown 文本（不含下载动作）。 */
export function buildRevisionMarkdown(
  bookTitle: string,
  items: RevisionItem[],
): string {
  const lines: string[] = [];
  const today = new Date();
  const dateStr = `${today.getFullYear()}-${pad2(today.getMonth() + 1)}-${pad2(today.getDate())}`;
  lines.push(`# 改稿清单 · 《${bookTitle}》 · ${dateStr}`);
  lines.push("");

  const todo = items.filter((it) => it.status === "todo").length;
  const done = items.filter((it) => it.status === "done").length;
  const wont = items.filter((it) => it.status === "wontfix").length;
  lines.push(`共 ${items.length} 条 · 待改 ${todo} · 已改 ${done} · 不改 ${wont}`);
  lines.push("");

  for (const cat of CATEGORY_ORDER) {
    const group = items.filter((it) => it.category === cat);
    if (group.length === 0) continue;
    lines.push(`## ${CATEGORY_SECTION[cat]}（${group.length}）`);
    lines.push("");
    group.forEach((it, i) => {
      lines.push(`### ${i + 1}. [${STATUS_LABEL[it.status]}] ${it.problem}`);
      it.evidence.forEach((ev) => {
        const tag = ev.role === "counterpart" ? "另一处" : "原文";
        lines.push(`> 【第 ${ev.chapter} 章 · ${tag}】${ev.snippet}`);
      });
      lines.push("");
    });
  }
  return lines.join("\n").trimEnd() + "\n";
}

function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}
