// ---------------------------------------------------------------------------
// 阅读标注 · 数据模型 + 锚定 + 本地存储（WP-reading-workspace §3、§4，Phase A）
//
// 一条标注钉在原文哪个位置，是个自带冗余、能自我校验的值对象（锚点），不是指向某个
// chunk_id 的外键。这样原文重新分块 / 微调后还能把位置重新找回来——直接对应
// verify_citations 锚错 60% 的坑（reference_verify_citations_anchoring_limit）。
//
// 存储照 historyStorage.ts 的成熟范式：一个总 key，按 book_session_id 分桶，
// localStorage 不可用 / JSON 坏了一律返默认值不抛。
//
// Phase A 只实现 local 这一支；hosted（走账号 DB）是 Phase C，接口先留好。
// 这条链全程纯前端 + 纯计算：不调 LLM、不碰 key（设计稿红线，免费守住）。
// ---------------------------------------------------------------------------

export type AnnotationKind = "bookmark" | "highlight" | "note" | "emphasis";

/** 高亮 / 重点的颜色档——汉风 2~3 档，别做成一堆荧光笔（善本克制）。
 *  用户批注偏墨、AI 批注偏朱（设计稿 §2.4），所以默认色是 ink。 */
export type AnnotationColor = "seal" | "ink" | "neutral";

/**
 * 锚点：多重冗余、可降级的值对象。精确信息漂了，还能靠粗信息把位置找回来。
 *
 * 字段冗余度从精到粗：char_start（快路）→ quote（文字主键）→ prefix/suffix
 * （上下文窗口，多命中时消歧）→ para_index/chapter（粗定位，章是最稳的锚）。
 */
export interface Anchor {
  /** 章号。Reader 按章取正文，章是一等公民、最稳的锚，一般不漂。 */
  chapter: number;
  /** 章内第几段（text 按 \n 切段后的序号）。重新解析可能漂，靠下面两个救。 */
  para_index: number;
  /** 选中的那截原文（精确文字）——文字级定位的主键。 */
  quote: string;
  /** quote 前面约 24 字窗口——同样文字跨章 / 跨段复现时靠它消歧。 */
  prefix: string;
  /** quote 后面约 24 字窗口——同上。 */
  suffix: string;
  /** 在该段里的字符偏移，定位用的快捷线索。漂了不致命，走慢路重找。
   *  书签可粗到段 / 章级，没有精确选区时为 null。 */
  char_start: number | null;
}

/** 一条标注。用 kind 区分四类，anchor 是载重字段。 */
export interface Annotation {
  id: string;
  /** 属于哪本书（沿用 session_id）。 */
  book_session_id: string;
  kind: AnnotationKind;
  anchor: Anchor;
  /** 用户写的笔记正文；note 类必有，其余可空。 */
  note_text: string | null;
  /** 高亮 / 重点的颜色档；书签 / 笔记可空。 */
  color: AnnotationColor | null;
  /** ISO 8601 UTC。 */
  created_at: string;
  /** 改笔记 / 颜色时更新。 */
  updated_at: string;
}

/** 改一条标注时能改的字段（id / 归属 / 创建时间不动）。 */
export type AnnotationPatch = Partial<
  Pick<Annotation, "kind" | "anchor" | "note_text" | "color">
>;

// ---------------------------------------------------------------------------
// 锚点抽取 —— 从一次选区造一个锚点（前后文各取约 24 字窗口）
// ---------------------------------------------------------------------------

const CONTEXT_WINDOW = 24;

/**
 * 从「段全文 + 选区在段内的字符区间」造一个锚点。
 *
 * 选区起止由调用方（划词工具条）从 DOM Selection 换算成段内偏移后传进来。
 * prefix / suffix 各取 CONTEXT_WINDOW 字，用于二次定位时消歧。
 */
export function buildAnchor(args: {
  chapter: number;
  paraIndex: number;
  paraText: string;
  selStart: number;
  selEnd: number;
}): Anchor {
  const { chapter, paraIndex, paraText, selStart, selEnd } = args;
  const start = Math.max(0, Math.min(selStart, paraText.length));
  const end = Math.max(start, Math.min(selEnd, paraText.length));
  return {
    chapter,
    para_index: paraIndex,
    quote: paraText.slice(start, end),
    prefix: paraText.slice(Math.max(0, start - CONTEXT_WINDOW), start),
    suffix: paraText.slice(end, end + CONTEXT_WINDOW),
    char_start: start,
  };
}

// ---------------------------------------------------------------------------
// 二次定位 —— 从精确到粗放逐级回退（WP §3.3，纯计算、不调 LLM）
//
// 核心原则（写死）：宁可降级显示并明确告诉用户「位置可能不准」，也绝不把标注静默
// 贴到错的地方。错贴比降级更糟，这是 verify_citations 坑留下的硬教训。
// ---------------------------------------------------------------------------

/** 定位结果：命中段内一个字符区间，或降级到章级。 */
export type Resolved =
  | {
      kind: "located";
      paraIndex: number;
      start: number;
      end: number;
      /** 走了哪一级：exact=快路命中 / refind=段内重找 / disambiguated=上下文消歧。 */
      via: "exact" | "refind" | "disambiguated";
    }
  | {
      kind: "chapter";
      /** 降级到章级——原文找不到了，标注不丢、不乱贴，打「位置可能不准」标。 */
      reason: "not_found" | "no_quote";
    };

/** 在一段文字里找出 quote 的所有起始位置。 */
function allOccurrences(haystack: string, needle: string): number[] {
  if (!needle) return [];
  const out: number[] = [];
  let from = 0;
  for (;;) {
    const i = haystack.indexOf(needle, from);
    if (i < 0) break;
    out.push(i);
    from = i + 1; // +1 而非 +needle.length：容许重叠复现也全找出来
  }
  return out;
}

/** 给一处候选打上下文吻合分：prefix 末尾、suffix 开头各比多少字相符（越高越像）。 */
function contextScore(
  paraText: string,
  pos: number,
  quoteLen: number,
  prefix: string,
  suffix: string,
): number {
  let score = 0;
  // 往前逐字比 prefix（从紧贴 quote 的那头往外）
  for (let k = 1; k <= prefix.length; k += 1) {
    const a = paraText[pos - k];
    const b = prefix[prefix.length - k];
    if (a !== undefined && a === b) score += 1;
    else break;
  }
  // 往后逐字比 suffix
  const afterStart = pos + quoteLen;
  for (let k = 0; k < suffix.length; k += 1) {
    const a = paraText[afterStart + k];
    const b = suffix[k];
    if (a !== undefined && a === b) score += 1;
    else break;
  }
  return score;
}

/**
 * 把一条锚点定位回当前这章的段落数组。
 *
 * paras = 当前章 text 按 Reader 同一套规则切出来的段（见 splitParas）。逐级回退：
 *   1. 快路：para_index 段里按 char_start 取一截，比对 quote 一致 → 命中。
 *   2. 段内重找：char_start 对不上 → 在该段搜 quote，只有一处 → 命中。
 *   3. 上下文消歧：该段 / 全章 quote 多处 → prefix+suffix 选前后文最吻合的一处。
 *   4. 降级：quote 在全章找不到 → 退章级，打「位置可能不准」标，绝不静默贴错。
 */
export function resolveAnchor(anchor: Anchor, paras: string[]): Resolved {
  const { para_index, quote, char_start, prefix, suffix } = anchor;
  if (!quote) return { kind: "chapter", reason: "no_quote" };

  const para = paras[para_index];

  // ── 1. 快路：原段 + 原偏移直接命中 ──
  if (
    para !== undefined &&
    char_start !== null &&
    para.slice(char_start, char_start + quote.length) === quote
  ) {
    return {
      kind: "located",
      paraIndex: para_index,
      start: char_start,
      end: char_start + quote.length,
      via: "exact",
    };
  }

  // ── 2. 段内重找：原段里搜 quote ──
  if (para !== undefined) {
    const hits = allOccurrences(para, quote);
    if (hits.length === 1) {
      return {
        kind: "located",
        paraIndex: para_index,
        start: hits[0],
        end: hits[0] + quote.length,
        via: "refind",
      };
    }
    if (hits.length > 1) {
      // 原段内多处 → 上下文消歧
      const best = pickByContext(para, hits, quote.length, prefix, suffix);
      return {
        kind: "located",
        paraIndex: para_index,
        start: best,
        end: best + quote.length,
        via: "disambiguated",
      };
    }
  }

  // ── 3. 全章重找 + 消歧：原段被删 / 重排，扫所有段 ──
  const chapterHits: { paraIndex: number; pos: number }[] = [];
  for (let pi = 0; pi < paras.length; pi += 1) {
    for (const pos of allOccurrences(paras[pi], quote)) {
      chapterHits.push({ paraIndex: pi, pos });
    }
  }
  if (chapterHits.length === 1) {
    const h = chapterHits[0];
    return {
      kind: "located",
      paraIndex: h.paraIndex,
      start: h.pos,
      end: h.pos + quote.length,
      via: "refind",
    };
  }
  if (chapterHits.length > 1) {
    // 多段多处都命中 → 用 prefix+suffix 选前后文最吻合的那处（正面解 60% 锚错坑）
    let best = chapterHits[0];
    let bestScore = -1;
    for (const h of chapterHits) {
      const s = contextScore(paras[h.paraIndex], h.pos, quote.length, prefix, suffix);
      if (s > bestScore) {
        bestScore = s;
        best = h;
      }
    }
    return {
      kind: "located",
      paraIndex: best.paraIndex,
      start: best.pos,
      end: best.pos + quote.length,
      via: "disambiguated",
    };
  }

  // ── 4. 彻底找不到 → 降级章级，绝不乱贴 ──
  return { kind: "chapter", reason: "not_found" };
}

/** 段内多处命中时，按上下文吻合分选最佳；并列取第一处（保守、稳定）。 */
function pickByContext(
  para: string,
  positions: number[],
  quoteLen: number,
  prefix: string,
  suffix: string,
): number {
  let best = positions[0];
  let bestScore = -1;
  for (const pos of positions) {
    const s = contextScore(para, pos, quoteLen, prefix, suffix);
    if (s > bestScore) {
      bestScore = s;
      best = pos;
    }
  }
  return best;
}

/**
 * 把一章 text 切成段——必须和 Reader 的 ChapterProse 用同一套规则，否则段序对不上。
 * Reader: text.split(/\n{1,}/).map(trim).filter(Boolean)
 */
export function splitParas(text: string): string[] {
  return text
    .split(/\n{1,}/)
    .map((p) => p.trim())
    .filter(Boolean);
}

// ---------------------------------------------------------------------------
// 存储接口 —— 一层接口、两个实现（WP §4，钱学森「一套受控对象两种工况」）
//
// 上层 UI 只认接口，由部署形态决定注入哪个。Phase A 只有 Local 一支；
// HostedAnnotationStore（走 /api/annotations）是 Phase C。
// ---------------------------------------------------------------------------

export interface AnnotationStore {
  /** 列这本书的所有标注。 */
  list(bookSessionId: string): Annotation[];
  /** 加一条，返回落库后的完整标注。 */
  add(annotation: Annotation): Annotation;
  /** 改一条；改不到返 null。 */
  update(id: string, patch: AnnotationPatch): Annotation | null;
  /** 删一条。 */
  remove(id: string): void;
  /** 跨书汇总「我写过的所有标注」（Phase B「我的案头」用）。 */
  listAllForUser(): Annotation[];
}

// ── localStorage 实现 ──────────────────────────────────────────────────

const STORAGE_KEY = "bookscope_annotations_v1";

type AnnotationMap = Record<string, Annotation[]>;

function getStorage(): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    const ls = window.localStorage;
    const probe = "__bookscope_anno_probe__";
    ls.setItem(probe, "1");
    ls.removeItem(probe);
    return ls;
  } catch {
    return null;
  }
}

function isAnchor(v: unknown): v is Anchor {
  if (!v || typeof v !== "object") return false;
  const a = v as Record<string, unknown>;
  return (
    typeof a.chapter === "number" &&
    typeof a.para_index === "number" &&
    typeof a.quote === "string" &&
    typeof a.prefix === "string" &&
    typeof a.suffix === "string" &&
    (a.char_start === null || typeof a.char_start === "number")
  );
}

const KINDS: AnnotationKind[] = ["bookmark", "highlight", "note", "emphasis"];

function isAnnotation(v: unknown): v is Annotation {
  if (!v || typeof v !== "object") return false;
  const a = v as Record<string, unknown>;
  return (
    typeof a.id === "string" &&
    typeof a.book_session_id === "string" &&
    typeof a.kind === "string" &&
    KINDS.includes(a.kind as AnnotationKind) &&
    isAnchor(a.anchor) &&
    (a.note_text === null || typeof a.note_text === "string") &&
    (a.color === null || typeof a.color === "string") &&
    typeof a.created_at === "string" &&
    typeof a.updated_at === "string"
  );
}

function loadMap(): AnnotationMap {
  const ls = getStorage();
  if (!ls) return {};
  try {
    const raw = ls.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const result: AnnotationMap = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!Array.isArray(value)) continue;
      const entries = value.filter(isAnnotation);
      if (entries.length > 0) result[key] = entries;
    }
    return result;
  } catch {
    return {};
  }
}

function saveMap(data: AnnotationMap): void {
  const ls = getStorage();
  if (!ls) return;
  try {
    ls.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // quota 满 / 隐私模式 → 静默放弃，不阻断主流程
  }
}

export class LocalAnnotationStore implements AnnotationStore {
  list(bookSessionId: string): Annotation[] {
    if (!bookSessionId) return [];
    return loadMap()[bookSessionId] ?? [];
  }

  add(annotation: Annotation): Annotation {
    const { book_session_id } = annotation;
    if (!book_session_id) return annotation;
    const data = loadMap();
    const bucket = data[book_session_id] ?? [];
    saveMap({ ...data, [book_session_id]: [...bucket, annotation] });
    return annotation;
  }

  update(id: string, patch: AnnotationPatch): Annotation | null {
    if (!id) return null;
    const data = loadMap();
    let updated: Annotation | null = null;
    const next: AnnotationMap = {};
    for (const [key, bucket] of Object.entries(data)) {
      next[key] = bucket.map((a) => {
        if (a.id !== id) return a;
        updated = { ...a, ...patch, updated_at: new Date().toISOString() };
        return updated;
      });
    }
    if (updated) saveMap(next);
    return updated;
  }

  remove(id: string): void {
    if (!id) return;
    const data = loadMap();
    const next: AnnotationMap = {};
    let changed = false;
    for (const [key, bucket] of Object.entries(data)) {
      const filtered = bucket.filter((a) => a.id !== id);
      if (filtered.length !== bucket.length) changed = true;
      if (filtered.length > 0) next[key] = filtered;
    }
    if (changed) saveMap(next);
  }

  listAllForUser(): Annotation[] {
    const data = loadMap();
    const all: Annotation[] = [];
    for (const bucket of Object.values(data)) all.push(...bucket);
    return all;
  }
}

/** 生成新标注 id。优先 crypto.randomUUID()，不可用回落时间戳 + 随机数
 *  （照 historyStorage.newEntryId 的兜底链）。 */
export function newAnnotationId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch {
    // 个别老浏览器在非安全上下文访问 crypto 会抛
  }
  return `anno_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

/** Phase A 全局只用 local 这一支；Phase C 据部署形态在这里改注入 Hosted。 */
export const annotationStore: AnnotationStore = new LocalAnnotationStore();
