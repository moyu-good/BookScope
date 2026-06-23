// ---------------------------------------------------------------------------
// bookScale —— 全书结构类分析在大书上会 token 爆炸的预先估算（纯函数，可单测）
//
// 关系 / 叙事流 / 逐章曲线 / 伏笔 / 支线 / 时间线 / 论点这类「读完整本出结构」的功能走
// map-reduce:按字符预算把全书切成若干段,每段一次 LLM 调用。段数 = 调用数 = 慢和贵的来源;
// 段太多时单段还可能把输出撑爆被截断,只抽到一部分。书一上传(TOC 每章带 word_count,中文按
// 字符)前端就能算出总字数 → 预估段数 → 提前告诉用户,别让他点下去干等又花冤枉钱。
//
// CHAR_BUDGET 必须跟后端 _internal/exhaustive.py 的 DEFAULT_CHAR_BUDGET 对齐。
// ---------------------------------------------------------------------------

/** 每段字符预算,对齐后端 DEFAULT_CHAR_BUDGET。 */
export const CHAR_BUDGET = 40000;

/** 50 万字起算「体量不小」——头回跑得分十几段,等几分钟、按段计费。 */
const LARGE_CHARS = 500_000;
/** 150 万字起算「非常大」——几十段,单段超长很可能被截断、只抽到一部分。 */
const HUGE_CHARS = 1_500_000;

export type ScaleTier = "ok" | "large" | "huge";

export interface BookScale {
  /** ok=不提醒;large=慢和贵但通常跑得全;huge=很可能有章节被截断只抽到一部分。 */
  tier: ScaleTier;
  /** 全书结构类分析预估要分多少段(= LLM 调用数)。 */
  segments: number;
  /** 约多少万字(中文按字符)。 */
  wan: number;
  /** 章数。 */
  chapters: number;
}

/**
 * 据总字数(中文=字符数)和章数估算全书结构类分析的体量。
 *
 * 档位按总字数分(字数是慢/贵/截断的真正驱动量):
 * - < 50 万字:ok,不提醒(头回跑也就一两分钟)。
 * - 50–150 万字:large,慢 + 按段计费,但通常能跑全(明朝 ~88 万字)。
 * - >= 150 万字:huge,除了慢和贵,单段超长很可能被截断、只抽到一部分(几百万字网文)。
 *
 * segments = ceil(总字数 / CHAR_BUDGET),即全书结构类分析要分多少段(= LLM 调用数),给文案用。
 */
export function bookScale(totalChars: number, chapters: number): BookScale {
  const segments = Math.max(1, Math.ceil(totalChars / CHAR_BUDGET));
  const tier: ScaleTier =
    totalChars >= HUGE_CHARS ? "huge" : totalChars >= LARGE_CHARS ? "large" : "ok";
  return { tier, segments, wan: Math.round(totalChars / 10000), chapters };
}
