// ---------------------------------------------------------------------------
// Reader —— 精读阅读器（WP-reading-experience，1.3）
//
// 把「精读」从"只显示有注释那几章、字体写死"改成一台真阅读器：整本书按章通读，
// 字号 / 行距 / 页边 / 背景 / 字体可调，读到哪记得住。数据走两个纯数据端点（不调 LLM）：
//   GET /api/sessions/{id}/toc                目录（章号 + 标题 + 字数，不带正文）
//   GET /api/sessions/{id}/chapters/{chapter}  单章正文
//
// 注释是「可开关的叠加层」（默认关、先纯读）——叠加层逻辑见 ReaderAnnotations（后续接）。
// 排版皮肤留在「数字善本」：背景三主题是读面局部覆盖，不黑整个 app-shell。
// CPU-only、无重阅读器库：按章懒取懒渲染 + 目录跳转，不一次性塞整本进 DOM。
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface TocChapter {
  chapter: number;
  title: string;
  word_count: number;
}

interface ChapterText {
  chapter: number;
  title: string;
  text: string;
  word_count: number;
}

interface ReaderProps {
  sessionId: string;
}

// ---------------------------------------------------------------------------
// 排版偏好 —— 存 localStorage，跨会话不丢
// ---------------------------------------------------------------------------

type ThemeId = "paper" | "sepia" | "night";
type FontId = "song" | "hei";
type SpacingId = "compact" | "normal" | "loose";
type MarginId = "narrow" | "normal" | "wide";

interface ReaderPrefs {
  fontPx: number; // 13–24
  lineHeight: SpacingId;
  margin: MarginId;
  theme: ThemeId;
  font: FontId;
}

const PREFS_KEY = "bookscope_reader_prefs_v1";
const POS_KEY = "bookscope_reader_pos_v1"; // { [sessionId]: chapter }

const DEFAULT_PREFS: ReaderPrefs = {
  fontPx: 17,
  lineHeight: "normal",
  margin: "normal",
  theme: "paper",
  font: "song",
};

const FONT_MIN = 13;
const FONT_MAX = 24;

// 读面三主题——只覆盖读面这块 DOM 的前景/背景，不动 app-shell 善本浅色。
const THEMES: Record<ThemeId, { bg: string; fg: string; label: string }> = {
  paper: { bg: "var(--color-paper)", fg: "var(--color-ink)", label: "纸色" },
  sepia: { bg: "oklch(92% 0.035 85)", fg: "oklch(30% 0.02 50)", label: "护眼" },
  night: { bg: "oklch(22% 0.008 60)", fg: "oklch(82% 0.012 75)", label: "夜间" },
};

const LINE_HEIGHTS: Record<SpacingId, { value: number; label: string }> = {
  compact: { value: 1.6, label: "紧" },
  normal: { value: 1.95, label: "中" },
  loose: { value: 2.3, label: "松" },
};

const MARGINS: Record<MarginId, { maxWidth: string; label: string }> = {
  narrow: { maxWidth: "46rem", label: "窄" },
  normal: { maxWidth: "38rem", label: "中" },
  wide: { maxWidth: "30rem", label: "宽" },
};

const FONTS: Record<FontId, { family: string; label: string }> = {
  song: { family: "var(--font-display)", label: "宋" },
  hei: { family: "var(--font-body)", label: "黑" },
};

function loadPrefs(): ReaderPrefs {
  if (typeof window === "undefined") return DEFAULT_PREFS;
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    if (!raw) return DEFAULT_PREFS;
    const p = JSON.parse(raw) as Partial<ReaderPrefs>;
    return {
      fontPx:
        typeof p.fontPx === "number"
          ? Math.min(FONT_MAX, Math.max(FONT_MIN, p.fontPx))
          : DEFAULT_PREFS.fontPx,
      lineHeight: p.lineHeight ?? DEFAULT_PREFS.lineHeight,
      margin: p.margin ?? DEFAULT_PREFS.margin,
      theme: p.theme ?? DEFAULT_PREFS.theme,
      font: p.font ?? DEFAULT_PREFS.font,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

function savePrefs(p: ReaderPrefs): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    // 隐私模式 / 配额满 / SSR——失败默默忽略
  }
}

function loadLastChapter(sessionId: string): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(POS_KEY);
    if (!raw) return null;
    const map = JSON.parse(raw) as Record<string, number>;
    const ch = map[sessionId];
    return typeof ch === "number" ? ch : null;
  } catch {
    return null;
  }
}

function saveLastChapter(sessionId: string, chapter: number): void {
  if (typeof window === "undefined") return;
  try {
    const raw = window.localStorage.getItem(POS_KEY);
    const map = raw ? (JSON.parse(raw) as Record<string, number>) : {};
    map[sessionId] = chapter;
    window.localStorage.setItem(POS_KEY, JSON.stringify(map));
  } catch {
    // 忽略
  }
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

export function Reader({ sessionId }: ReaderProps) {
  const [toc, setToc] = useState<TocChapter[] | null>(null);
  const [bookTitle, setBookTitle] = useState("");
  const [tocError, setTocError] = useState<string | null>(null);
  const [tocLoading, setTocLoading] = useState(false);

  const [current, setCurrent] = useState<number | null>(null);
  const [chapter, setChapter] = useState<ChapterText | null>(null);
  const [chapterLoading, setChapterLoading] = useState(false);
  const [chapterError, setChapterError] = useState<string | null>(null);

  const [prefs, setPrefs] = useState<ReaderPrefs>(loadPrefs);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [tocOpen, setTocOpen] = useState(false);

  // 已取章节正文缓存：翻回去不重新请求
  const cache = useRef<Map<number, ChapterText>>(new Map());
  // 读面容器：换章时滚回顶
  const surfaceRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    savePrefs(prefs);
  }, [prefs]);

  // 换书：清缓存、清正文，重新拉目录
  useEffect(() => {
    cache.current.clear();
    setChapter(null);
    setCurrent(null);
    setToc(null);
    setTocError(null);
    let cancelled = false;
    setTocLoading(true);
    (async () => {
      try {
        const resp = await fetch(`/api/sessions/${sessionId}/toc`);
        if (!resp.ok) {
          const j = (await resp.json().catch(() => null)) as
            | { detail?: { message?: string } }
            | null;
          throw new Error(j?.detail?.message ?? `目录取不到（${resp.status}）`);
        }
        const data = (await resp.json()) as {
          book_title: string;
          total_chapters: number;
          chapters: TocChapter[];
        };
        if (cancelled) return;
        setBookTitle(data.book_title ?? "");
        setToc(data.chapters ?? []);
        // 续读：上次读到的章还在目录里就回到那章，否则第一章
        const last = loadLastChapter(sessionId);
        const nums = (data.chapters ?? []).map((c) => c.chapter);
        const start =
          last != null && nums.includes(last) ? last : nums[0] ?? null;
        setCurrent(start);
      } catch (err) {
        if (!cancelled) setTocError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setTocLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // 取当前章正文（带缓存）
  useEffect(() => {
    if (current == null) return;
    const cached = cache.current.get(current);
    if (cached) {
      setChapter(cached);
      setChapterError(null);
      return;
    }
    let cancelled = false;
    setChapterLoading(true);
    setChapterError(null);
    (async () => {
      try {
        const resp = await fetch(
          `/api/sessions/${sessionId}/chapters/${current}`,
        );
        if (!resp.ok) {
          const j = (await resp.json().catch(() => null)) as
            | { detail?: { message?: string } }
            | null;
          throw new Error(j?.detail?.message ?? `这章取不到（${resp.status}）`);
        }
        const data = (await resp.json()) as ChapterText;
        if (cancelled) return;
        cache.current.set(current, data);
        setChapter(data);
      } catch (err) {
        if (!cancelled)
          setChapterError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setChapterLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, current]);

  // 换章：记位置 + 读面滚回顶
  useEffect(() => {
    if (current == null) return;
    saveLastChapter(sessionId, current);
    if (surfaceRef.current) surfaceRef.current.scrollTop = 0;
  }, [sessionId, current]);

  const tocNums = useMemo(() => (toc ?? []).map((c) => c.chapter), [toc]);
  const idx = current == null ? -1 : tocNums.indexOf(current);
  const hasPrev = idx > 0;
  const hasNext = idx >= 0 && idx < tocNums.length - 1;

  const goPrev = useCallback(() => {
    if (hasPrev) setCurrent(tocNums[idx - 1]);
  }, [hasPrev, tocNums, idx]);
  const goNext = useCallback(() => {
    if (hasNext) setCurrent(tocNums[idx + 1]);
  }, [hasNext, tocNums, idx]);

  const theme = THEMES[prefs.theme];

  if (tocLoading && !toc) {
    return (
      <p className="pt-4 text-sm text-[var(--color-ink-muted)]">翻开书页中…</p>
    );
  }
  if (tocError) {
    return (
      <p className="pt-4 text-sm" style={{ color: "var(--color-seal)" }}>
        {tocError}
      </p>
    );
  }
  if (toc && toc.length === 0) {
    return (
      <p className="pt-4 text-sm text-[var(--color-ink)]">
        这本书没解析出可读的章节。换本书，或换个格式重新上传试试。
      </p>
    );
  }

  return (
    <div className="pt-2">
      {/* 顶栏：目录 / 进度 / 排版设置 */}
      <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
        <button
          type="button"
          onClick={() => setTocOpen((v) => !v)}
          className="text-sm px-3 py-1.5 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] transition-colors"
        >
          目录
        </button>
        <span className="text-xs text-[var(--color-ink-muted)]">
          {idx >= 0 ? `第 ${current} 章` : ""}
          {toc ? ` · 全书 ${toc.length} 章` : ""}
        </span>
        <button
          type="button"
          onClick={() => setSettingsOpen((v) => !v)}
          className="text-sm px-3 py-1.5 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] transition-colors"
          aria-label="排版设置"
        >
          排版
        </button>
      </div>

      {settingsOpen && (
        <TypographyPanel prefs={prefs} onChange={setPrefs} />
      )}

      <div className="relative grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-4">
        {/* 目录侧栏：桌面常驻、手机抽屉式（tocOpen 控制） */}
        <aside
          className={[
            tocOpen ? "block" : "hidden",
            "lg:block lg:sticky lg:top-2 lg:self-start lg:max-h-[640px] lg:overflow-y-auto",
            "rounded border border-[var(--color-rule)] bg-[var(--color-paper-sunken)] p-2",
          ].join(" ")}
        >
          <TocList
            toc={toc ?? []}
            current={current}
            onPick={(ch) => {
              setCurrent(ch);
              setTocOpen(false);
            }}
          />
        </aside>

        {/* 读面：摊开的册页 */}
        <div>
          <div
            ref={surfaceRef}
            className="rounded border border-[var(--color-rule)] p-6 sm:p-8 max-h-[640px] overflow-y-auto transition-colors"
            style={{ background: theme.bg, color: theme.fg }}
          >
            {bookTitle && (
              <div
                className="text-xs mb-4 opacity-60"
                style={{ fontFamily: FONTS[prefs.font].family }}
              >
                {bookTitle}
              </div>
            )}

            {chapterError ? (
              <p className="text-sm" style={{ color: "var(--color-seal)" }}>
                {chapterError}
              </p>
            ) : chapterLoading && !chapter ? (
              <p className="text-sm opacity-60">取这一章…</p>
            ) : chapter ? (
              <article>
                <h2
                  className="text-lg font-bold mb-4 pb-2"
                  style={{
                    fontFamily: FONTS[prefs.font].family,
                    borderBottom: `1px solid ${theme.fg}`,
                    opacity: 0.92,
                  }}
                >
                  {chapter.title?.trim()
                    ? chapter.title
                    : `第 ${chapter.chapter} 章`}
                </h2>
                <ChapterProse
                  text={chapter.text}
                  fontPx={prefs.fontPx}
                  lineHeight={LINE_HEIGHTS[prefs.lineHeight].value}
                  fontFamily={FONTS[prefs.font].family}
                  maxWidth={MARGINS[prefs.margin].maxWidth}
                />
              </article>
            ) : null}
          </div>

          {/* 翻章 */}
          <div className="flex items-center justify-between mt-3">
            <button
              type="button"
              onClick={goPrev}
              disabled={!hasPrev}
              className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              上一章
            </button>
            <button
              type="button"
              onClick={goNext}
              disabled={!hasNext}
              className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              下一章
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 一章正文：按段落渲染，居中阅读栏控页边宽度
// ---------------------------------------------------------------------------
function ChapterProse({
  text,
  fontPx,
  lineHeight,
  fontFamily,
  maxWidth,
}: {
  text: string;
  fontPx: number;
  lineHeight: number;
  fontFamily: string;
  maxWidth: string;
}) {
  const paras = useMemo(
    () => text.split(/\n{1,}/).map((p) => p.trim()).filter(Boolean),
    [text],
  );
  return (
    <div
      style={{ maxWidth, marginInline: "auto", fontFamily, fontSize: `${fontPx}px`, lineHeight }}
    >
      {paras.map((p, i) => (
        <p key={i} className="mb-4 whitespace-pre-wrap">
          {p}
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 目录列表
// ---------------------------------------------------------------------------
function TocList({
  toc,
  current,
  onPick,
}: {
  toc: TocChapter[];
  current: number | null;
  onPick: (chapter: number) => void;
}) {
  return (
    <ul className="space-y-0.5">
      {toc.map((c) => {
        const active = c.chapter === current;
        return (
          <li key={c.chapter}>
            <button
              type="button"
              onClick={() => onPick(c.chapter)}
              className="w-full text-left text-xs px-2.5 py-1.5 rounded transition-colors truncate"
              style={
                active
                  ? {
                      background: "var(--color-seal-soft)",
                      color: "var(--color-seal)",
                    }
                  : { color: "var(--color-ink-muted)" }
              }
              title={c.title || `第 ${c.chapter} 章`}
            >
              {c.title?.trim() ? `${c.chapter}. ${c.title}` : `第 ${c.chapter} 章`}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// 排版设置浮层：字号 / 行距 / 页边 / 背景 / 字体
// ---------------------------------------------------------------------------
function TypographyPanel({
  prefs,
  onChange,
}: {
  prefs: ReaderPrefs;
  onChange: (p: ReaderPrefs) => void;
}) {
  function set<K extends keyof ReaderPrefs>(key: K, value: ReaderPrefs[K]) {
    onChange({ ...prefs, [key]: value });
  }
  return (
    <div className="mb-3 rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-3 flex flex-col gap-3 text-xs">
      {/* 字号 */}
      <Row label="字号">
        <button
          type="button"
          onClick={() => set("fontPx", Math.max(FONT_MIN, prefs.fontPx - 1))}
          disabled={prefs.fontPx <= FONT_MIN}
          className="w-7 h-7 rounded border border-[var(--color-rule)] bg-white disabled:opacity-40"
        >
          A−
        </button>
        <span className="w-10 text-center text-[var(--color-ink)]">
          {prefs.fontPx}px
        </span>
        <button
          type="button"
          onClick={() => set("fontPx", Math.min(FONT_MAX, prefs.fontPx + 1))}
          disabled={prefs.fontPx >= FONT_MAX}
          className="w-7 h-7 rounded border border-[var(--color-rule)] bg-white disabled:opacity-40"
        >
          A+
        </button>
      </Row>
      {/* 行距 */}
      <Row label="行距">
        <Seg
          options={(["compact", "normal", "loose"] as SpacingId[]).map((id) => ({
            id,
            label: LINE_HEIGHTS[id].label,
          }))}
          value={prefs.lineHeight}
          onPick={(v) => set("lineHeight", v)}
        />
      </Row>
      {/* 页边 */}
      <Row label="页边">
        <Seg
          options={(["narrow", "normal", "wide"] as MarginId[]).map((id) => ({
            id,
            label: MARGINS[id].label,
          }))}
          value={prefs.margin}
          onPick={(v) => set("margin", v)}
        />
      </Row>
      {/* 背景 */}
      <Row label="背景">
        <Seg
          options={(["paper", "sepia", "night"] as ThemeId[]).map((id) => ({
            id,
            label: THEMES[id].label,
          }))}
          value={prefs.theme}
          onPick={(v) => set("theme", v)}
        />
      </Row>
      {/* 字体 */}
      <Row label="字体">
        <Seg
          options={(["song", "hei"] as FontId[]).map((id) => ({
            id,
            label: FONTS[id].label,
          }))}
          value={prefs.font}
          onPick={(v) => set("font", v)}
        />
      </Row>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-8 shrink-0 text-[var(--color-ink-muted)]">{label}</span>
      <div className="flex items-center gap-1.5">{children}</div>
    </div>
  );
}

function Seg<T extends string>({
  options,
  value,
  onPick,
}: {
  options: { id: T; label: string }[];
  value: T;
  onPick: (v: T) => void;
}) {
  return (
    <div className="flex gap-1">
      {options.map((o) => {
        const on = o.id === value;
        return (
          <button
            key={o.id}
            type="button"
            onClick={() => onPick(o.id)}
            className="px-3 py-1 rounded border transition-colors"
            style={
              on
                ? {
                    background: "var(--color-seal-soft)",
                    borderColor: "var(--color-seal)",
                    color: "var(--color-seal)",
                  }
                : {
                    background: "var(--color-paper)",
                    borderColor: "var(--color-rule)",
                    color: "var(--color-ink-muted)",
                  }
            }
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
