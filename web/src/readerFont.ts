// ---------------------------------------------------------------------------
// 精读阅读器的字体 / 字号选项 + localStorage 持久化（只服务 AnnotatedReader 章正文）
//
// 字体用系统字体栈，不引网络字体（CPU-only、离线可用、首选已装的系统字）。每个栈都以
// --font-display 兜底，系统没装首选字时优雅回退到全站默认。字号同时调 font-size 与行高，
// 只作用于章正文阅读区，不动 UI chrome / 注释签 / 工具栏。
// ---------------------------------------------------------------------------

export interface ReaderFont {
  id: string;
  label: string;
  // 直接塞进章正文容器的 style.fontFamily
  fontFamily: string;
}

// 默认项沿用全站正文字体（--font-display），其余给几种常见中文阅读字体的系统栈，
// 末尾都接 var(--font-display) 兜底——系统没装就回退到默认，不会掉成无衬线乱码。
export const READER_FONTS: ReaderFont[] = [
  { id: "default", label: "默认", fontFamily: "var(--font-display)" },
  {
    id: "songti",
    label: "宋体",
    fontFamily:
      '"Songti SC", "SimSun", "Source Han Serif SC", "Noto Serif CJK SC", var(--font-display)',
  },
  {
    id: "kaiti",
    label: "楷体",
    fontFamily: '"Kaiti SC", "KaiTi", "STKaiti", "BiauKai", var(--font-display)',
  },
  {
    id: "fangsong",
    label: "仿宋",
    fontFamily: '"FangSong", "STFangsong", "Fang Song", var(--font-display)',
  },
  {
    id: "heiti",
    label: "黑体",
    fontFamily:
      '"Heiti SC", "SimHei", "PingFang SC", "Microsoft YaHei", var(--font-display)',
  },
  {
    id: "source-serif",
    label: "思源宋体",
    fontFamily:
      '"Source Han Serif SC", "Noto Serif CJK SC", "Noto Serif SC", var(--font-display)',
  },
  {
    id: "source-sans",
    label: "思源黑体",
    fontFamily:
      '"Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC", var(--font-display)',
  },
];

export interface ReaderSize {
  id: string;
  label: string;
  fontSize: string;
  lineHeight: string;
}

// 中为默认（与改版前的 14px / 1.9 一致），上下各两档。
export const READER_SIZES: ReaderSize[] = [
  { id: "s", label: "小", fontSize: "13px", lineHeight: "1.8" },
  { id: "m", label: "中", fontSize: "14px", lineHeight: "1.9" },
  { id: "l", label: "大", fontSize: "16px", lineHeight: "2.0" },
  { id: "xl", label: "特大", fontSize: "18px", lineHeight: "2.1" },
];

const FONT_KEY = "bookscope_reader_font_v1";
const SIZE_KEY = "bookscope_reader_size_v1";

// 默认字体 = 列表首项（默认）；默认字号 = 中（与旧版一致）。
const DEFAULT_FONT_ID = READER_FONTS[0].id;
const DEFAULT_SIZE_ID = "m";

export function loadReaderFontId(): string {
  if (typeof window === "undefined") return DEFAULT_FONT_ID;
  try {
    const raw = window.localStorage.getItem(FONT_KEY);
    if (raw && READER_FONTS.some((f) => f.id === raw)) return raw;
    return DEFAULT_FONT_ID;
  } catch {
    return DEFAULT_FONT_ID;
  }
}

export function saveReaderFontId(id: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(FONT_KEY, id);
  } catch {
    // 隐私模式 / 配额满 / SSR ——失败默默忽略
  }
}

export function loadReaderSizeId(): string {
  if (typeof window === "undefined") return DEFAULT_SIZE_ID;
  try {
    const raw = window.localStorage.getItem(SIZE_KEY);
    if (raw && READER_SIZES.some((s) => s.id === raw)) return raw;
    return DEFAULT_SIZE_ID;
  } catch {
    return DEFAULT_SIZE_ID;
  }
}

export function saveReaderSizeId(id: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SIZE_KEY, id);
  } catch {
    // 隐私模式 / 配额满 / SSR ——失败默默忽略
  }
}
