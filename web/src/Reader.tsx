// ---------------------------------------------------------------------------
// Reader —— 沉浸式精读阅读器（WP-reading-experience §2.5，读书优先 IA）
//
// 整页是书:正文居中、留白舒展。顶栏停读自动隐(只剩书),动鼠标浮出。底部可拖进度条。
//   目录 = 左侧滑出抽屉     排版 = 浮层(对齐微信读书:背景色卡/字体/字号/行距/段距/字重/页边)
//   鉴   = 阅读界面里就地跑分析的大浮层(AnalysisOverlay,不跳走)   ‹书架 = 退回书架
// 数据走两个纯数据端点(不调 LLM):/api/sessions/{id}/toc、/chapters/{n}。CPU-only,懒取懒渲染。
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnalysisOverlay } from "./AnalysisOverlay";
import { bookScale } from "./bookScale";
import { RangeInput } from "./ui/FormControls";
import {
  annotationStore,
  buildAnchor,
  newAnnotationId,
} from "./annotationStore";
import type { Annotation, AnnotationColor, AnnotationKind } from "./annotationStore";
import {
  AnnotatedProse,
  AnnotationActions,
  AnnotationOverview,
  NoteEditor,
  SelectionToolbar,
} from "./ReaderAnnotations";
import type { PendingSelection } from "./ReaderAnnotations";

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
  bookTitle: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  /** 退回书架 */
  onExit: () => void;
}

// ---------------------------------------------------------------------------
// 排版偏好 —— 对齐微信读书档位,存 localStorage
// ---------------------------------------------------------------------------

type ThemeId = "white" | "cream" | "parchment" | "green" | "night";
type FontId = "song" | "hei" | "kai" | "fangsong";
type SpacingId = "compact" | "normal" | "loose";
type MarginId = "narrow" | "normal" | "wide";
type WeightId = "normal" | "medium";

interface ReaderPrefs {
  fontPx: number;
  lineHeight: SpacingId;
  paraGap: SpacingId;
  margin: MarginId;
  theme: ThemeId;
  font: FontId;
  weight: WeightId;
}

const PREFS_KEY = "bookscope_reader_prefs_v2";
const POS_KEY = "bookscope_reader_pos_v1";

const DEFAULT_PREFS: ReaderPrefs = {
  fontPx: 19,
  lineHeight: "normal",
  paraGap: "normal",
  margin: "normal",
  theme: "cream",
  font: "song",
  weight: "normal",
};

const FONT_MIN = 14;
const FONT_MAX = 28;

// 背景色卡 —— 铺满整页（对齐微信读书的一排主题）。
const THEMES: Record<ThemeId, { bg: string; fg: string; faint: string; label: string }> = {
  white: { bg: "#FCFBF7", fg: "#2B2925", faint: "rgba(40,38,32,0.12)", label: "白" },
  cream: { bg: "#F7F2E7", fg: "#33302A", faint: "rgba(60,50,30,0.13)", label: "米黄" },
  parchment: { bg: "#E7D9BE", fg: "#433a23", faint: "rgba(67,58,35,0.18)", label: "羊皮" },
  green: { bg: "#DCE7D6", fg: "#2E3A2A", faint: "rgba(46,58,42,0.16)", label: "护眼" },
  night: { bg: "#1B1A18", fg: "#C9C4B8", faint: "rgba(201,196,184,0.16)", label: "夜间" },
};

const LINE_HEIGHTS: Record<SpacingId, { value: number; label: string }> = {
  compact: { value: 1.7, label: "紧" },
  normal: { value: 2.0, label: "中" },
  loose: { value: 2.4, label: "松" },
};

// 段距:段落之间的间隔（与行距分开,微信读书也分两档调节）。
const PARA_GAPS: Record<SpacingId, { rem: number; label: string }> = {
  compact: { rem: 0.6, label: "紧" },
  normal: { rem: 1.1, label: "中" },
  loose: { rem: 1.8, label: "松" },
};

// maxWidth = 阅读栏宽度,按页面宽度的百分比给(作者要正文铺到 ~80% 甚至更宽,别挤在窄列里)。
// "页边"越窄 → 正文栏越宽。默认「中」= 80%。嫌一行太长就调「宽」(页边宽、正文 66%)。
const MARGINS: Record<MarginId, { maxWidth: string; label: string }> = {
  narrow: { maxWidth: "92%", label: "窄" },
  normal: { maxWidth: "80%", label: "中" },
  wide: { maxWidth: "66%", label: "宽" },
};

const FONTS: Record<FontId, { family: string; label: string }> = {
  song: { family: "var(--font-display)", label: "宋" },
  hei: { family: "var(--font-body)", label: "黑" },
  kai: { family: '"Kaiti SC","STKaiti","Kaiti","楷体",serif', label: "楷" },
  fangsong: { family: '"FangSong","STFangsong","仿宋","Fang Song",serif', label: "仿宋" },
};

const WEIGHTS: Record<WeightId, { value: number; label: string }> = {
  normal: { value: 400, label: "常规" },
  medium: { value: 500, label: "偏粗" },
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
      paraGap: p.paraGap ?? DEFAULT_PREFS.paraGap,
      margin: p.margin ?? DEFAULT_PREFS.margin,
      theme: p.theme ?? DEFAULT_PREFS.theme,
      font: p.font ?? DEFAULT_PREFS.font,
      weight: p.weight ?? DEFAULT_PREFS.weight,
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
    /* 忽略 */
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
    /* 忽略 */
  }
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

export function Reader({ sessionId, bookTitle, provider, apiKey, model, baseUrl, onExit }: ReaderProps) {
  const [toc, setToc] = useState<TocChapter[] | null>(null);
  const [tocError, setTocError] = useState<string | null>(null);

  const [current, setCurrent] = useState<number | null>(null);
  const [chapter, setChapter] = useState<ChapterText | null>(null);
  const [chapterLoading, setChapterLoading] = useState(false);
  const [chapterError, setChapterError] = useState<string | null>(null);

  const [prefs, setPrefs] = useState<ReaderPrefs>(loadPrefs);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [tocOpen, setTocOpen] = useState(false);
  const [jianOpen, setJianOpen] = useState(false);
  const [piOpen, setPiOpen] = useState(false); // 「批」总览抽屉
  const [chromeShown, setChromeShown] = useState(true);

  // ── 标注层（WP-reading-workspace Phase A，纯本地 / 不调 LLM）──
  // 本书全部标注；划词工具条 / 笔记框 / 已有标注的编辑卡都从这套状态长出来。
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [pendingSel, setPendingSel] = useState<PendingSelection | null>(null);
  // 正在写 / 改的笺注：new=划词新建一条 note；edit=改已有那条。
  const [noteDraft, setNoteDraft] = useState<
    | { mode: "new"; sel: PendingSelection }
    | { mode: "edit"; ann: Annotation }
    | null
  >(null);
  // 点已有标注浮出的编辑 / 删除卡。
  const [activeAnn, setActiveAnn] = useState<Annotation | null>(null);
  // 跳到某条标注：换到它那章 + 标记一下要滚过去。
  const [jumpTo, setJumpTo] = useState<Annotation | null>(null);

  const cache = useRef<Map<number, ChapterText>>(new Map());
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const chromeTimer = useRef<number | null>(null);

  // 换书：重新载这本书的标注（local 范式，照 historyStorage）。
  useEffect(() => {
    setAnnotations(annotationStore.list(sessionId));
    setPiOpen(false);
    setPendingSel(null);
    setNoteDraft(null);
    setActiveAnn(null);
  }, [sessionId]);

  // 重载一次本书标注 —— 任何增删改后调，保 UI 与存储一致。
  const reloadAnnotations = useCallback(() => {
    setAnnotations(annotationStore.list(sessionId));
  }, [sessionId]);

  // 跨章跳转：换到目标章、正文取回来后，滚到那条标注（用 data-anno-id 锚）。
  useEffect(() => {
    if (!jumpTo || !chapter || chapter.chapter !== jumpTo.anchor.chapter) return;
    // 等这一帧渲染完正文再滚
    const t = window.setTimeout(() => {
      scrollToAnnotation(jumpTo);
      setJumpTo(null);
    }, 60);
    return () => window.clearTimeout(t);
  }, [jumpTo, chapter]);

  useEffect(() => {
    savePrefs(prefs);
  }, [prefs]);

  // 顶栏自动隐:动鼠标显形并重置计时;浮层开着时常显。
  const anyPanelOpen = settingsOpen || tocOpen || jianOpen || piOpen;
  useEffect(() => {
    function wake() {
      setChromeShown(true);
      if (chromeTimer.current) window.clearTimeout(chromeTimer.current);
      chromeTimer.current = window.setTimeout(() => setChromeShown(false), 2800);
    }
    window.addEventListener("mousemove", wake);
    window.addEventListener("keydown", wake);
    wake();
    return () => {
      window.removeEventListener("mousemove", wake);
      window.removeEventListener("keydown", wake);
      if (chromeTimer.current) window.clearTimeout(chromeTimer.current);
    };
  }, []);
  const chromeVisible = chromeShown || anyPanelOpen;

  // 拉目录 + 定位续读章
  useEffect(() => {
    cache.current.clear();
    setChapter(null);
    setCurrent(null);
    setToc(null);
    setTocError(null);
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`/api/sessions/${sessionId}/toc`);
        if (!resp.ok) {
          const j = (await resp.json().catch(() => null)) as { detail?: { message?: string } } | null;
          throw new Error(j?.detail?.message ?? `目录取不到（${resp.status}）`);
        }
        const data = (await resp.json()) as { total_chapters: number; chapters: TocChapter[] };
        if (cancelled) return;
        setToc(data.chapters ?? []);
        const last = loadLastChapter(sessionId);
        const nums = (data.chapters ?? []).map((c) => c.chapter);
        setCurrent(last != null && nums.includes(last) ? last : nums[0] ?? null);
      } catch (err) {
        if (!cancelled) setTocError(err instanceof Error ? err.message : String(err));
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
        const resp = await fetch(`/api/sessions/${sessionId}/chapters/${current}`);
        if (!resp.ok) {
          const j = (await resp.json().catch(() => null)) as { detail?: { message?: string } } | null;
          throw new Error(j?.detail?.message ?? `这章取不到（${resp.status}）`);
        }
        const data = (await resp.json()) as ChapterText;
        if (cancelled) return;
        cache.current.set(current, data);
        setChapter(data);
      } catch (err) {
        if (!cancelled) setChapterError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setChapterLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, current]);

  // 换章:记位置 + 滚回顶
  useEffect(() => {
    if (current == null) return;
    saveLastChapter(sessionId, current);
    if (surfaceRef.current) surfaceRef.current.scrollTop = 0;
  }, [sessionId, current]);

  const tocNums = useMemo(() => (toc ?? []).map((c) => c.chapter), [toc]);
  // 全书结构类分析在大书上会 token 爆炸——TOC 一到手就估好体量,传进鉴台提前提醒。
  const scale = useMemo(() => {
    if (!toc || toc.length === 0) return null;
    const totalChars = toc.reduce((s, c) => s + (c.word_count || 0), 0);
    return bookScale(totalChars, toc.length);
  }, [toc]);
  const idx = current == null ? -1 : tocNums.indexOf(current);
  const total = tocNums.length;
  const hasPrev = idx > 0;
  const hasNext = idx >= 0 && idx < total - 1;
  const goPrev = useCallback(() => {
    if (idx > 0) setCurrent(tocNums[idx - 1]);
  }, [tocNums, idx]);
  const goNext = useCallback(() => {
    if (idx >= 0 && idx < tocNums.length - 1) setCurrent(tocNums[idx + 1]);
  }, [tocNums, idx]);

  const theme = THEMES[prefs.theme];
  const pct = idx >= 0 && total > 0 ? Math.round(((idx + 1) / total) * 100) : 0;

  // ── 标注动作 ──────────────────────────────────────────────────────────
  // 高亮 / 重点：从选区造锚点直接落一条。笔记：先开输入框，写完再落。
  const addFromSelection = useCallback(
    (kind: AnnotationKind, color: AnnotationColor | null, noteText: string | null) => {
      if (!pendingSel) return;
      const anchor = buildAnchor({
        chapter: pendingSel.chapter,
        paraIndex: pendingSel.paraIndex,
        paraText: pendingSel.paraText,
        selStart: pendingSel.selStart,
        selEnd: pendingSel.selEnd,
      });
      const now = new Date().toISOString();
      const ann: Annotation = {
        id: newAnnotationId(),
        book_session_id: sessionId,
        kind,
        anchor,
        note_text: noteText,
        color,
        created_at: now,
        updated_at: now,
      };
      annotationStore.add(ann);
      reloadAnnotations();
      setPendingSel(null);
      clearSelection();
    },
    [pendingSel, sessionId, reloadAnnotations],
  );

  const handleHighlight = useCallback(
    (color: AnnotationColor) => addFromSelection("highlight", color, null),
    [addFromSelection],
  );
  const handleEmphasis = useCallback(
    () => addFromSelection("emphasis", "seal", null),
    [addFromSelection],
  );
  const handleStartNote = useCallback(() => {
    if (pendingSel) {
      setNoteDraft({ mode: "new", sel: pendingSel });
      setPendingSel(null);
    }
  }, [pendingSel]);

  // 书签：不依赖选区，落「读到这章」——锚到当前章、段级（quote 空 / char_start null）。
  // 划词时也能从工具条加，锚到选中那段段首；纯按钮加则锚到本章第一段。
  const addBookmark = useCallback(
    (fromSel: PendingSelection | null) => {
      if (current == null) return;
      const now = new Date().toISOString();
      const ann: Annotation = {
        id: newAnnotationId(),
        book_session_id: sessionId,
        kind: "bookmark",
        anchor: {
          chapter: current,
          para_index: fromSel?.paraIndex ?? 0,
          quote: "",
          prefix: "",
          suffix: "",
          char_start: null,
        },
        note_text: null,
        color: "ink",
        created_at: now,
        updated_at: now,
      };
      annotationStore.add(ann);
      reloadAnnotations();
      setPendingSel(null);
      clearSelection();
    },
    [current, sessionId, reloadAnnotations],
  );

  // 笺注存盘：new 落新条；edit 改已有。
  const saveNote = useCallback(
    (text: string) => {
      if (!noteDraft) return;
      const trimmed = text.trim();
      if (noteDraft.mode === "new") {
        const { sel } = noteDraft;
        const anchor = buildAnchor({
          chapter: sel.chapter,
          paraIndex: sel.paraIndex,
          paraText: sel.paraText,
          selStart: sel.selStart,
          selEnd: sel.selEnd,
        });
        const now = new Date().toISOString();
        annotationStore.add({
          id: newAnnotationId(),
          book_session_id: sessionId,
          kind: "note",
          anchor,
          note_text: trimmed,
          color: "ink",
          created_at: now,
          updated_at: now,
        });
      } else {
        annotationStore.update(noteDraft.ann.id, { note_text: trimmed });
      }
      reloadAnnotations();
      setNoteDraft(null);
      clearSelection();
    },
    [noteDraft, sessionId, reloadAnnotations],
  );

  const deleteAnnotation = useCallback(
    (ann: Annotation) => {
      annotationStore.remove(ann.id);
      reloadAnnotations();
      setActiveAnn(null);
    },
    [reloadAnnotations],
  );

  // 批注总览点一条 / 章末降级条点一条 → 跳到它那章那处。
  const jumpToAnnotation = useCallback(
    (ann: Annotation) => {
      setPiOpen(false);
      setActiveAnn(null);
      if (ann.anchor.chapter !== current) {
        setCurrent(ann.anchor.chapter);
        setJumpTo(ann); // 换章取完正文后再滚（见下面 effect）
      } else {
        scrollToAnnotation(ann);
      }
    },
    [current],
  );

  return (
    <div className="fixed inset-0 z-40 flex flex-col transition-colors" style={{ background: theme.bg, color: theme.fg }}>
      {/* 顶栏:停读自动淡隐,动鼠标显形 */}
      <header
        className="absolute top-0 inset-x-0 z-20 flex items-center justify-between px-4 sm:px-6 h-12 transition-opacity duration-500"
        style={{
          opacity: chromeVisible ? 1 : 0,
          pointerEvents: chromeVisible ? "auto" : "none",
          background: theme.bg,
          borderBottom: `0.5px solid ${theme.faint}`,
        }}
      >
        <button type="button" onClick={onExit} className="text-sm opacity-80 hover:opacity-100" style={{ fontFamily: "var(--font-display)" }}>
          ‹ 书架
        </button>
        <span className="text-xs truncate max-w-[40%] opacity-60" title={bookTitle}>
          {bookTitle}
        </span>
        <div className="flex items-center gap-1.5">
          <ChromeBtn onClick={() => setTocOpen(true)} label="目录" />
          <ChromeBtn onClick={() => setSettingsOpen((v) => !v)} label="排版" />
          {/* 批：用户标注总览抽屉（与目录左右对称、右滑）。有标注时角标记数。 */}
          <button
            type="button"
            onClick={() => setPiOpen(true)}
            className="relative text-xs px-3 py-1 rounded-full border opacity-80 hover:opacity-100"
            style={{ borderColor: "currentColor" }}
            title="我的批注"
          >
            批
            {annotations.length > 0 && (
              <span
                className="absolute -top-1.5 -right-1.5 min-w-[1rem] h-4 px-1 rounded-full text-[10px] leading-4 text-center text-white"
                style={{ background: "var(--color-ink)" }}
              >
                {annotations.length}
              </span>
            )}
          </button>
          <button type="button" onClick={() => setJianOpen(true)} className="text-xs px-3 py-1 rounded-full text-white hover:brightness-110" style={{ background: "var(--color-seal)" }}>
            鉴
          </button>
        </div>
      </header>

      {/* 排版浮层 */}
      {settingsOpen && (
        <div className="absolute right-3 sm:right-6 top-12 z-30 w-[20rem] max-w-[calc(100vw-1.5rem)]">
          <TypographyPanel prefs={prefs} onChange={setPrefs} theme={theme} />
        </div>
      )}

      {/* 读面:整页是书 */}
      <div ref={surfaceRef} className="flex-1 overflow-y-auto">
        <div
          className="mx-auto px-6 sm:px-10 pt-20 pb-28"
          style={{
            maxWidth: MARGINS[prefs.margin].maxWidth,
            fontFamily: FONTS[prefs.font].family,
            fontSize: `${prefs.fontPx}px`,
            lineHeight: LINE_HEIGHTS[prefs.lineHeight].value,
            fontWeight: WEIGHTS[prefs.weight].value,
          }}
        >
          {tocError ? (
            <p className="text-sm" style={{ color: "var(--color-seal)" }}>{tocError}</p>
          ) : chapterError ? (
            <p className="text-sm" style={{ color: "var(--color-seal)" }}>{chapterError}</p>
          ) : !toc ? (
            <p className="text-sm opacity-60">翻开书页中…</p>
          ) : toc.length === 0 ? (
            <p className="text-sm">这本书没解析出可读的章节。换个格式重新上传试试。</p>
          ) : chapterLoading && !chapter ? (
            <p className="text-sm opacity-60">取这一章…</p>
          ) : chapter ? (
            <article>
              <h1 className="font-bold mb-8" style={{ fontSize: `${prefs.fontPx + 5}px`, opacity: 0.92 }}>
                {chapter.title?.trim() ? chapter.title : `第 ${chapter.chapter} 章`}
              </h1>
              <AnnotatedProse
                text={chapter.text}
                paraGapRem={PARA_GAPS[prefs.paraGap].rem}
                chapter={chapter.chapter}
                annotations={annotations}
                fg={theme.fg}
                onPickAnnotation={(ann) => setActiveAnn(ann)}
                onSelect={(sel) => setPendingSel(sel)}
              />
              <div className="mt-12 pt-6 flex items-center justify-between" style={{ borderTop: `0.5px solid ${theme.faint}` }}>
                <ChapterNavBtn disabled={!hasPrev} onClick={goPrev} label="上一章" fg={theme.fg} faint={theme.faint} />
                <button type="button" onClick={() => setTocOpen(true)} className="text-xs opacity-50 hover:opacity-90">目录</button>
                <ChapterNavBtn disabled={!hasNext} onClick={goNext} label="下一章" fg={theme.fg} faint={theme.faint} />
              </div>
            </article>
          ) : null}
        </div>
      </div>

      {/* 两侧悬浮翻章箭头 */}
      {chromeVisible && hasPrev && <EdgeArrow side="left" onClick={goPrev} faint={theme.faint} fg={theme.fg} />}
      {chromeVisible && hasNext && <EdgeArrow side="right" onClick={goNext} faint={theme.faint} fg={theme.fg} />}

      {/* 底部进度条:可拖动跳章(对齐微信读书) */}
      {total > 0 && (
        <div
          className="absolute bottom-0 inset-x-0 z-20 px-5 sm:px-10 py-2 flex items-center gap-3 transition-opacity duration-500"
          style={{
            opacity: chromeVisible ? 1 : 0,
            pointerEvents: chromeVisible ? "auto" : "none",
            background: theme.bg,
            borderTop: `0.5px solid ${theme.faint}`,
          }}
        >
          <span className="text-xs opacity-60 shrink-0 tabular-nums">第 {current} / {total} 章</span>
          <RangeInput
            min={0}
            max={Math.max(0, total - 1)}
            value={idx >= 0 ? idx : 0}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              if (tocNums[v] != null) setCurrent(tocNums[v]);
            }}
            className="flex-1"
            aria-label="阅读进度,拖动跳章"
          />
          <span className="text-xs opacity-60 shrink-0 tabular-nums">{pct}%</span>
        </div>
      )}

      {/* 目录:左侧滑出抽屉 */}
      {tocOpen && (
        <Drawer side="left" onClose={() => setTocOpen(false)}>
          <TocList toc={toc ?? []} current={current} onPick={(ch) => { setCurrent(ch); setTocOpen(false); }} />
        </Drawer>
      )}

      {/* 鉴:阅读界面里就地跑分析的大浮层(不跳走) */}
      {jianOpen && (
        <AnalysisOverlay
          sessionId={sessionId}
          bookTitle={bookTitle}
          provider={provider}
          apiKey={apiKey}
          model={model}
          baseUrl={baseUrl}
          currentChapter={current}
          scale={scale}
          onClose={() => setJianOpen(false)}
        />
      )}

      {/* 批：标注总览抽屉（右滑，与目录左右对称）。点一条跳到那章那处。 */}
      {piOpen && (
        <Drawer side="right" onClose={() => setPiOpen(false)}>
          <AnnotationOverview
            annotations={annotations}
            onJump={jumpToAnnotation}
            onDelete={deleteAnnotation}
          />
        </Drawer>
      )}

      {/* 划词工具条：选中文字浮出，高亮 / 笔记 / 重点 / 书签。 */}
      {pendingSel && (
        <SelectionToolbar
          selection={pendingSel}
          onHighlight={handleHighlight}
          onNote={handleStartNote}
          onEmphasis={handleEmphasis}
          onBookmark={() => addBookmark(pendingSel)}
          onClose={() => {
            setPendingSel(null);
            clearSelection();
          }}
        />
      )}

      {/* 笺注输入框：写新笺注 / 改已有。 */}
      {noteDraft && (
        <NoteEditor
          initial={noteDraft.mode === "edit" ? noteDraft.ann.note_text ?? "" : ""}
          quote={
            noteDraft.mode === "edit"
              ? noteDraft.ann.anchor.quote
              : noteDraft.sel.paraText.slice(noteDraft.sel.selStart, noteDraft.sel.selEnd)
          }
          onSave={saveNote}
          onCancel={() => {
            setNoteDraft(null);
            clearSelection();
          }}
        />
      )}

      {/* 点已有标注浮出的编辑 / 删除卡。 */}
      {activeAnn && (
        <AnnotationActions
          ann={activeAnn}
          onEditNote={() => {
            const a = activeAnn;
            setActiveAnn(null);
            setNoteDraft({ mode: "edit", ann: a });
          }}
          onDelete={() => deleteAnnotation(activeAnn)}
          onClose={() => setActiveAnn(null)}
        />
      )}
    </div>
  );
}

// 划词后清掉浏览器选区（落了标注 / 取消时调，免得选区残留盖着新染的底色）。
function clearSelection(): void {
  if (typeof window === "undefined") return;
  try {
    window.getSelection()?.removeAllRanges();
  } catch {
    /* 个别环境取不到 selection，忽略 */
  }
}

// 滚到某条标注所在的段（按 data-para；降级到章级的也能滚到记的那段）。
function scrollToAnnotation(ann: Annotation): void {
  if (typeof document === "undefined") return;
  const el = document.querySelector(`[data-para="${ann.anchor.para_index}"]`);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ---------------------------------------------------------------------------
// 通用:左 / 右侧滑出抽屉(目录左滑 / 批注右滑)
// ---------------------------------------------------------------------------
function Drawer({ side, width = "20rem", onClose, children }: { side: "left" | "right"; width?: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="absolute inset-0 z-30">
      <button type="button" aria-label="关闭" onClick={onClose} className="absolute inset-0" style={{ background: "color-mix(in oklch, var(--color-ink) 30%, transparent)" }} />
      <div
        className={["absolute top-0 bottom-0 overflow-y-auto bg-[var(--color-paper)] p-3", side === "left" ? "left-0 border-r" : "right-0 border-l", "border-[var(--color-rule)]"].join(" ")}
        style={{ width, maxWidth: "85vw" }}
      >
        <div className="flex justify-end mb-1">
          <button type="button" onClick={onClose} className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]" aria-label="收起">收起 ✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function ChromeBtn({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button type="button" onClick={onClick} className="text-xs px-3 py-1 rounded-full border opacity-80 hover:opacity-100" style={{ borderColor: "currentColor" }}>
      {label}
    </button>
  );
}

function ChapterNavBtn({ disabled, onClick, label, fg, faint }: { disabled: boolean; onClick: () => void; label: string; fg: string; faint: string }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} className="text-sm px-4 py-1.5 rounded border disabled:opacity-30 disabled:cursor-not-allowed hover:opacity-100 opacity-80" style={{ borderColor: faint, color: fg }}>
      {label}
    </button>
  );
}

function EdgeArrow({ side, onClick, faint, fg }: { side: "left" | "right"; onClick: () => void; faint: string; fg: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={side === "left" ? "上一章" : "下一章"}
      className={["absolute top-1/2 -translate-y-1/2 z-10 w-10 h-16 rounded flex items-center justify-center text-2xl transition-opacity", side === "left" ? "left-1 sm:left-3" : "right-1 sm:right-3"].join(" ")}
      style={{ color: fg, opacity: 0.4, background: `color-mix(in srgb, ${faint}, transparent 40%)` }}
    >
      {side === "left" ? "‹" : "›"}
    </button>
  );
}

// ---------------------------------------------------------------------------
// 目录列表
// ---------------------------------------------------------------------------
function TocList({ toc, current, onPick }: { toc: TocChapter[]; current: number | null; onPick: (chapter: number) => void }) {
  return (
    <>
      <div className="text-xs text-[var(--color-ink-muted)] px-2 pb-2 mb-1 border-b border-[var(--color-rule)]">目录 · 共 {toc.length} 章</div>
      <ul className="space-y-0.5">
        {toc.map((c) => {
          const active = c.chapter === current;
          return (
            <li key={c.chapter}>
              <button
                type="button"
                onClick={() => onPick(c.chapter)}
                className="w-full text-left text-xs px-2.5 py-1.5 rounded transition-colors truncate"
                style={active ? { background: "var(--color-seal-soft)", color: "var(--color-seal)" } : { color: "var(--color-ink-muted)" }}
                title={c.title || `第 ${c.chapter} 章`}
              >
                {c.title?.trim() ? `${c.chapter}. ${c.title}` : `第 ${c.chapter} 章`}
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}

// ---------------------------------------------------------------------------
// 排版设置浮层(对齐微信读书)
// ---------------------------------------------------------------------------
function TypographyPanel({
  prefs,
  onChange,
  theme,
}: {
  prefs: ReaderPrefs;
  onChange: (p: ReaderPrefs) => void;
  theme: { bg: string; fg: string; faint: string };
}) {
  function set<K extends keyof ReaderPrefs>(key: K, value: ReaderPrefs[K]) {
    onChange({ ...prefs, [key]: value });
  }
  const { fg, faint, bg } = theme;
  return (
    <div className="rounded-lg p-3 flex flex-col gap-3 text-xs" style={{ background: bg, border: `0.5px solid ${faint}`, color: fg, boxShadow: "0 8px 30px rgba(0,0,0,0.18)" }}>
      <Row label="字号" fg={fg}>
        <StepBtn faint={faint} fg={fg} disabled={prefs.fontPx <= FONT_MIN} onClick={() => set("fontPx", Math.max(FONT_MIN, prefs.fontPx - 1))}>A−</StepBtn>
        <span className="w-10 text-center">{prefs.fontPx}px</span>
        <StepBtn faint={faint} fg={fg} disabled={prefs.fontPx >= FONT_MAX} onClick={() => set("fontPx", Math.min(FONT_MAX, prefs.fontPx + 1))}>A+</StepBtn>
      </Row>
      <Row label="字体" fg={fg}>
        <Seg faint={faint} fg={fg} options={(["song", "hei", "kai", "fangsong"] as FontId[]).map((id) => ({ id, label: FONTS[id].label }))} value={prefs.font} onPick={(v) => set("font", v)} />
      </Row>
      <Row label="字重" fg={fg}>
        <Seg faint={faint} fg={fg} options={(["normal", "medium"] as WeightId[]).map((id) => ({ id, label: WEIGHTS[id].label }))} value={prefs.weight} onPick={(v) => set("weight", v)} />
      </Row>
      <Row label="行距" fg={fg}>
        <Seg faint={faint} fg={fg} options={(["compact", "normal", "loose"] as SpacingId[]).map((id) => ({ id, label: LINE_HEIGHTS[id].label }))} value={prefs.lineHeight} onPick={(v) => set("lineHeight", v)} />
      </Row>
      <Row label="段距" fg={fg}>
        <Seg faint={faint} fg={fg} options={(["compact", "normal", "loose"] as SpacingId[]).map((id) => ({ id, label: PARA_GAPS[id].label }))} value={prefs.paraGap} onPick={(v) => set("paraGap", v)} />
      </Row>
      <Row label="页边" fg={fg}>
        <Seg faint={faint} fg={fg} options={(["narrow", "normal", "wide"] as MarginId[]).map((id) => ({ id, label: MARGINS[id].label }))} value={prefs.margin} onPick={(v) => set("margin", v)} />
      </Row>
      <Row label="背景" fg={fg}>
        <div className="flex gap-1.5 flex-wrap">
          {(["white", "cream", "parchment", "green", "night"] as ThemeId[]).map((id) => {
            const t = THEMES[id];
            const on = id === prefs.theme;
            return (
              <button
                key={id}
                type="button"
                onClick={() => set("theme", id)}
                title={t.label}
                aria-label={t.label}
                className="w-7 h-7 rounded-full"
                style={{ background: t.bg, border: on ? "2px solid var(--color-seal)" : `1px solid ${faint}` }}
              />
            );
          })}
        </div>
      </Row>
    </div>
  );
}

function Row({ label, fg, children }: { label: string; fg: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-8 shrink-0 opacity-60" style={{ color: fg }}>{label}</span>
      <div className="flex items-center gap-1.5 flex-wrap">{children}</div>
    </div>
  );
}

function StepBtn({ onClick, disabled, fg, faint, children }: { onClick: () => void; disabled?: boolean; fg: string; faint: string; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} className="w-7 h-7 rounded disabled:opacity-40" style={{ border: `0.5px solid ${faint}`, color: fg }}>
      {children}
    </button>
  );
}

function Seg<T extends string>({ options, value, onPick, fg, faint }: { options: { id: T; label: string }[]; value: T; onPick: (v: T) => void; fg: string; faint: string }) {
  return (
    <div className="flex gap-1 flex-wrap">
      {options.map((o) => {
        const on = o.id === value;
        return (
          <button
            key={o.id}
            type="button"
            onClick={() => onPick(o.id)}
            className="px-3 py-1 rounded"
            style={on ? { background: "var(--color-seal)", color: "#fff" } : { border: `0.5px solid ${faint}`, color: fg, opacity: 0.7 }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
