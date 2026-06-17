// ---------------------------------------------------------------------------
// 每本书独立的问答历史 · 纯 localStorage 持久化
//
// 存储 key：bookscope_qa_history_v1
// 结构：{ [bookSessionId]: QAEntry[] }
//
// 容错原则：
// - localStorage 不可用（SSR / 隐私模式 / quota 满）时所有方法返默认值不抛错
// - JSON 损坏 → 视为空对象重新开始
// ---------------------------------------------------------------------------

export interface Citation {
  chapter: number;
  snippet: string;
}

export interface QAEntry {
  id: string;
  question: string;
  answer: string;
  citations: Citation[];
  /** ISO 8601 UTC 时间戳 */
  created_at: string;
}

export type HistoryMap = Record<string, QAEntry[]>;

const STORAGE_KEY = "bookscope_qa_history_v1";

function getStorage(): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    const ls = window.localStorage;
    // probe：某些浏览器隐私模式 quota=0，setItem 立刻抛
    const probe = "__bookscope_probe__";
    ls.setItem(probe, "1");
    ls.removeItem(probe);
    return ls;
  } catch {
    return null;
  }
}

function isQAEntry(value: unknown): value is QAEntry {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === "string" &&
    typeof v.question === "string" &&
    typeof v.answer === "string" &&
    Array.isArray(v.citations) &&
    typeof v.created_at === "string"
  );
}

export function loadHistory(): HistoryMap {
  const ls = getStorage();
  if (!ls) return {};
  try {
    const raw = ls.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    // 浅校验：每个 bucket 必须是 array，里面的 entry 必须长得像 QAEntry
    const result: HistoryMap = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!Array.isArray(value)) continue;
      const entries = value.filter(isQAEntry);
      if (entries.length > 0) {
        result[key] = entries;
      }
    }
    return result;
  } catch {
    return {};
  }
}

export function saveHistory(data: HistoryMap): void {
  const ls = getStorage();
  if (!ls) return;
  try {
    ls.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // quota 满或其他异常 → 静默放弃，不影响主流程
  }
}

export function getEntries(bookSessionId: string): QAEntry[] {
  if (!bookSessionId) return [];
  const data = loadHistory();
  return data[bookSessionId] ?? [];
}

export function appendEntry(bookSessionId: string, entry: QAEntry): void {
  if (!bookSessionId) return;
  const data = loadHistory();
  const bucket = data[bookSessionId] ?? [];
  saveHistory({
    ...data,
    [bookSessionId]: [...bucket, entry],
  });
}

export function deleteEntry(bookSessionId: string, entryId: string): void {
  if (!bookSessionId || !entryId) return;
  const data = loadHistory();
  const bucket = data[bookSessionId];
  if (!bucket) return;
  const next = bucket.filter((e) => e.id !== entryId);
  if (next.length === bucket.length) return;
  if (next.length === 0) {
    const { [bookSessionId]: _omit, ...rest } = data;
    void _omit;
    saveHistory(rest);
  } else {
    saveHistory({ ...data, [bookSessionId]: next });
  }
}

/**
 * 相对时间：5 分钟内 → "刚刚"；今天 → "X 分钟前 / X 小时前"；
 * 昨天 → "昨天 HH:MM"；7 天内 → "X 天前"；其余 → "M 月 D 日"。
 *
 * 解析失败时回落到原字符串。
 */
export function formatRelativeTime(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;

  const now = Date.now();
  const diffMs = now - t;
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);

  if (diffSec < 60) return "刚刚";
  if (diffMin < 60) return `${diffMin} 分钟前`;

  const date = new Date(t);
  const today = startOfDay(new Date(now));
  const that = startOfDay(date);
  const dayDiff = Math.round((today.getTime() - that.getTime()) / 86_400_000);

  if (dayDiff === 0) return `${diffHour} 小时前`;
  if (dayDiff === 1) {
    return `昨天 ${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
  }
  if (dayDiff < 7) return `${dayDiff} 天前`;

  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

/**
 * 生成新的 entry id。优先 crypto.randomUUID()；不可用时回落到时间戳 + 随机数。
 */
export function newEntryId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch {
    // 个别老浏览器在非安全上下文里访问 crypto 会抛
  }
  return `qa_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}
