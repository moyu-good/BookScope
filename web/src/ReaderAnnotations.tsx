// ---------------------------------------------------------------------------
// 阅读标注层 · 划词工具条 + 就地渲染 + 批注总览（WP-reading-workspace Phase A）
//
// 挂在 Reader 正文之上：
//   - AnnotatedProse —— 替代 Reader 原来的 ChapterProse，命中标注的段把对应文字段
//     渲染成带底色 / 带左线（评点排版的「就地朱墨」），段右天头地脚浮笔记小字。
//   - SelectionToolbar —— 选中文字浮出的气泡工具条：高亮 / 笔记 / 重点 / 书签。
//   - AnnotationDrawer —— 顶栏「批」点开的右侧抽屉，列这本书所有标注，点一条跳位置。
//
// 视觉走善本「评点排版」primitive（project_ui_design_language）：用户批注偏墨（ink）、
// 跟 AI 朱批（AnnotatedReader 的 seal）刻意分色，免得混。纯前端、不调 LLM、不碰 key。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import type {
  Annotation,
  AnnotationColor,
  AnnotationKind,
} from "./annotationStore";
import { resolveAnchor, splitParas } from "./annotationStore";

// 颜色档 → 实际色值。用户批注默认偏墨（ink），跟 AI 朱批（seal）分色。
const COLOR_VAR: Record<AnnotationColor, string> = {
  seal: "var(--color-seal)",
  ink: "var(--color-ink)",
  neutral: "var(--color-ink-muted)",
};

// 一段里命中的标注 + 它在本段的定位（已二次定位过）。
interface Placed {
  ann: Annotation;
  start: number;
  end: number;
  /** 二次定位降级到章级（原文有改动，位置可能不准）。 */
  chapterFallback: boolean;
  /** 走了哪一级定位——降级时给用户提示用。 */
  via: "exact" | "refind" | "disambiguated" | "chapter";
}

// ---------------------------------------------------------------------------
// 正文 + 标注就地渲染
// ---------------------------------------------------------------------------

export function AnnotatedProse({
  text,
  paraGapRem,
  chapter,
  annotations,
  fg,
  onPickAnnotation,
  onSelect,
}: {
  text: string;
  paraGapRem: number;
  chapter: number;
  /** 这本书的全部标注（本组件自己筛出本章的）。 */
  annotations: Annotation[];
  /** 当前主题前景色——画底色 / 左线时按它调透明度。 */
  fg: string;
  /** 点已有标注 → 浮出编辑 / 删除卡。 */
  onPickAnnotation: (ann: Annotation) => void;
  /** 划词选区落定 → 浮出工具条。段内偏移已换算好。 */
  onSelect: (sel: {
    chapter: number;
    paraIndex: number;
    paraText: string;
    selStart: number;
    selEnd: number;
    rect: DOMRect;
  }) => void;
}) {
  const paras = useMemo(() => splitParas(text), [text]);

  // 本章标注按段归位（二次定位）。
  const placedByPara = useMemo(() => {
    const map = new Map<number, Placed[]>();
    const chapterLevel: Placed[] = [];
    const pushTo = (pi: number, placed: Placed) => {
      const arr = map.get(pi);
      if (arr) arr.push(placed);
      else map.set(pi, [placed]);
    };

    for (const ann of annotations) {
      if (ann.anchor.chapter !== chapter) continue;

      // 书签锚到段级（无精确选区）：不走 quote 定位，直接挂锚点记的那段段首。
      // 段还在就当正常归位（不是「贴错」，书签本就可粗到段 / 章级）；段没了才进章级条。
      if (ann.kind === "bookmark") {
        const pi = ann.anchor.para_index;
        if (paras[pi] !== undefined) {
          pushTo(pi, { ann, start: 0, end: 0, chapterFallback: false, via: "chapter" });
        } else {
          chapterLevel.push({ ann, start: 0, end: 0, chapterFallback: true, via: "chapter" });
        }
        continue;
      }

      const r = resolveAnchor(ann.anchor, paras);
      if (r.kind === "chapter") {
        // 高亮 / 笔记 / 重点定不准 → 章末条，明确标「位置可能不准」，绝不乱贴。
        chapterLevel.push({ ann, start: 0, end: 0, chapterFallback: true, via: "chapter" });
        continue;
      }
      pushTo(r.paraIndex, {
        ann,
        start: r.start,
        end: r.end,
        chapterFallback: false,
        via: r.via,
      });
    }
    // 段内按起点排，方便切片渲染
    for (const arr of map.values()) arr.sort((a, b) => a.start - b.start);
    return { map, chapterLevel };
  }, [annotations, chapter, paras]);

  // 划词：选区落在正文里 → 换算成「哪段 + 段内起止偏移」，浮出工具条。
  function handleMouseUp() {
    const sel = typeof window !== "undefined" ? window.getSelection() : null;
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) return;
    const range = sel.getRangeAt(0);
    const text = sel.toString();
    if (!text.trim()) return;

    // 选区两端必须落在同一个段落 <p>（标了 data-para）。跨段选区不做（保守，避免锚乱）。
    const startP = closestPara(range.startContainer);
    const endP = closestPara(range.endContainer);
    if (!startP || startP !== endP) return;
    const paraIndex = Number(startP.dataset.para);
    if (!Number.isInteger(paraIndex)) return;
    const paraText = paras[paraIndex] ?? "";

    // 段内偏移：累加段内文本节点长度到选区端点。
    const selStart = offsetInPara(startP, range.startContainer, range.startOffset);
    const selEnd = offsetInPara(startP, range.endContainer, range.endOffset);
    if (selStart == null || selEnd == null || selEnd <= selStart) return;

    onSelect({
      chapter,
      paraIndex,
      paraText,
      selStart,
      selEnd,
      rect: range.getBoundingClientRect(),
    });
  }

  return (
    <div onMouseUp={handleMouseUp}>
      {paras.map((p, i) => (
        <ParaWithMarks
          key={i}
          paraIndex={i}
          text={p}
          paraGapRem={paraGapRem}
          placed={placedByPara.map.get(i) ?? []}
          fg={fg}
          onPickAnnotation={onPickAnnotation}
        />
      ))}
      {/* 降级到章级的标注（原文找不到了）——列在章末，明确标「位置可能不准」，不乱贴 */}
      {placedByPara.chapterLevel.length > 0 && (
        <ChapterLevelNotes
          placed={placedByPara.chapterLevel}
          onPickAnnotation={onPickAnnotation}
        />
      )}
    </div>
  );
}

// 一段正文 + 它身上的标注：高亮 / 重点就地染色，笔记在天头地脚浮小字。
function ParaWithMarks({
  paraIndex,
  text,
  paraGapRem,
  placed,
  fg,
  onPickAnnotation,
}: {
  paraIndex: number;
  text: string;
  paraGapRem: number;
  placed: Placed[];
  fg: string;
  onPickAnnotation: (ann: Annotation) => void;
}) {
  // 把文字按标注区间切成片段：未标注的裸文字 + 标注片段（可叠）。
  const segments = useMemo(() => sliceByMarks(text, placed), [text, placed]);

  // 这段挂的笺注（note）+ 书签 —— 走天头地脚（段右浮小字）。
  const sideNotes = placed.filter(
    (pl) => pl.ann.kind === "note" || pl.ann.kind === "bookmark",
  );

  return (
    <div
      className="group relative"
      style={{ marginBottom: `${paraGapRem}rem` }}
    >
      <p data-para={paraIndex} className="whitespace-pre-wrap">
        {segments.map((seg, idx) => {
          if (seg.marks.length === 0) {
            return <span key={idx}>{seg.text}</span>;
          }
          // 取该片段上「最重」的标注定外观：重点 > 高亮 > 笔记 > 书签。
          const top = topMark(seg.marks);
          return (
            <MarkedSpan
              key={idx}
              text={seg.text}
              ann={top}
              fg={fg}
              onClick={() => onPickAnnotation(top)}
            />
          );
        })}
      </p>
      {/* 天头地脚：段右浮用户笺注 / 书签小字（评点本气质，偏墨与 AI 朱批分色） */}
      {sideNotes.length > 0 && (
        <div className="mt-1.5 flex flex-col gap-1 pl-3">
          {sideNotes.map((pl) => (
            <SideNote key={pl.ann.id} placed={pl} onClick={() => onPickAnnotation(pl.ann)} />
          ))}
        </div>
      )}
    </div>
  );
}

// 一段被标注覆盖的文字片段（marks 为空 = 裸文字）。
interface Segment {
  text: string;
  marks: Annotation[];
}

/** 把一段文字按所有标注的 [start,end) 切成不重叠的片段，每片记盖在它上面的标注。 */
function sliceByMarks(text: string, placed: Placed[]): Segment[] {
  const spans = placed.filter(
    (pl) =>
      !pl.chapterFallback &&
      (pl.ann.kind === "highlight" || pl.ann.kind === "emphasis") &&
      pl.end > pl.start,
  );
  if (spans.length === 0) return [{ text, marks: [] }];

  // 收集所有边界点，切成区间。
  const bounds = new Set<number>([0, text.length]);
  for (const s of spans) {
    bounds.add(Math.max(0, Math.min(s.start, text.length)));
    bounds.add(Math.max(0, Math.min(s.end, text.length)));
  }
  const points = [...bounds].sort((a, b) => a - b);
  const out: Segment[] = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const a = points[i];
    const b = points[i + 1];
    if (b <= a) continue;
    const marks = spans
      .filter((s) => s.start <= a && s.end >= b)
      .map((s) => s.ann);
    out.push({ text: text.slice(a, b), marks });
  }
  return out;
}

/** 一组叠在同一片段上的标注里，取最重的定外观（重点 > 高亮）。 */
function topMark(marks: Annotation[]): Annotation {
  const rank: Record<AnnotationKind, number> = {
    emphasis: 3,
    highlight: 2,
    note: 1,
    bookmark: 0,
  };
  return [...marks].sort((a, b) => rank[b.kind] - rank[a.kind])[0];
}

// 一个被标注的文字片段：高亮染淡底，重点加左竖线 + 加粗。
function MarkedSpan({
  text,
  ann,
  fg,
  onClick,
}: {
  text: string;
  ann: Annotation;
  fg: string;
  onClick: () => void;
}) {
  const colorVar = COLOR_VAR[ann.color ?? "ink"];
  const isEmphasis = ann.kind === "emphasis";
  // 高亮：朱砂 / 墨 / 中性淡底（按颜色档）。重点：更重的标记——左竖线 + 加粗。
  const style: React.CSSProperties = isEmphasis
    ? {
        fontWeight: 600,
        borderLeft: `2px solid ${colorVar}`,
        paddingLeft: "0.2em",
        marginLeft: "0.1em",
        background: tint(colorVar, fg, 0.06),
        cursor: "pointer",
      }
    : {
        background: tint(colorVar, fg, 0.16),
        borderRadius: "2px",
        cursor: "pointer",
        boxDecorationBreak: "clone",
        WebkitBoxDecorationBreak: "clone",
      };
  return (
    <span
      onClick={onClick}
      style={style}
      title={ann.kind === "emphasis" ? "重点 · 点开看 / 改 / 删" : "高亮 · 点开看 / 改 / 删"}
    >
      {text}
    </span>
  );
}

// 段右天头地脚的一条笺注 / 书签小字。
function SideNote({ placed, onClick }: { placed: Placed; onClick: () => void }) {
  const { ann, chapterFallback } = placed;
  const isBookmark = ann.kind === "bookmark";
  const colorVar = COLOR_VAR[ann.color ?? "ink"];
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-left w-full text-xs leading-relaxed rounded px-2 py-1 transition-colors hover:opacity-90"
      style={{
        borderLeft: `2px solid ${colorVar}`,
        background: tint(colorVar, colorVar, 0.07),
        opacity: 0.92,
      }}
    >
      <span className="opacity-60 mr-1.5" aria-hidden>
        {isBookmark ? "⚑" : "✎"}
      </span>
      {isBookmark ? (
        <span className="opacity-70">{ann.note_text?.trim() || "书签 · 读到这"}</span>
      ) : (
        <span>{ann.note_text?.trim() || "（空笺注）"}</span>
      )}
      {chapterFallback && (
        <span className="ml-1.5 opacity-60" title="原文有改动，位置可能不准">
          · 位置可能不准
        </span>
      )}
    </button>
  );
}

// 降级到章级的标注（原文找不到了）：章末统一列出，明确标「位置可能不准」。
function ChapterLevelNotes({
  placed,
  onPickAnnotation,
}: {
  placed: Placed[];
  onPickAnnotation: (ann: Annotation) => void;
}) {
  return (
    <div
      className="mt-8 pt-4 rounded-md px-3 py-3"
      style={{
        borderTop: "0.5px solid var(--color-rule)",
        background: "var(--color-paper-sunken)",
      }}
    >
      <div className="text-xs opacity-60 mb-2">
        这几条标注的原文像是改动过，定不准位置，先挂在本章（绝不乱贴别处）：
      </div>
      <div className="flex flex-col gap-1.5">
        {placed.map((pl) => (
          <button
            key={pl.ann.id}
            type="button"
            onClick={() => onPickAnnotation(pl.ann)}
            className="text-left text-xs leading-relaxed rounded px-2 py-1.5 hover:opacity-90"
            style={{ border: "0.5px solid var(--color-rule)" }}
          >
            <span className="opacity-60 mr-1.5">「{pl.ann.anchor.quote.slice(0, 30)}」</span>
            {pl.ann.note_text?.trim() && (
              <span className="opacity-80">— {pl.ann.note_text}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 划词工具条 —— 贴着选区浮出，四动作
// ---------------------------------------------------------------------------

export interface PendingSelection {
  chapter: number;
  paraIndex: number;
  paraText: string;
  selStart: number;
  selEnd: number;
  rect: DOMRect;
}

export function SelectionToolbar({
  selection,
  onHighlight,
  onNote,
  onEmphasis,
  onBookmark,
  onClose,
}: {
  selection: PendingSelection;
  onHighlight: (color: AnnotationColor) => void;
  onNote: () => void;
  onEmphasis: () => void;
  onBookmark: () => void;
  onClose: () => void;
}) {
  const { rect } = selection;
  // 贴选区上方居中浮出；靠近顶部时翻到下方。
  const above = rect.top > 120;
  const top = above ? rect.top - 8 : rect.bottom + 8;
  const left = Math.min(
    Math.max(rect.left + rect.width / 2, 120),
    (typeof window !== "undefined" ? window.innerWidth : 1024) - 120,
  );

  // 高亮的颜色档小选择：朱 / 墨 / 中性。
  const [colorOpen, setColorOpen] = useState(false);

  return (
    <div
      className="fixed z-50"
      style={{
        top,
        left,
        transform: `translate(-50%, ${above ? "-100%" : "0"})`,
      }}
      // 阻止点工具条本身又清掉选区
      onMouseDown={(e) => e.preventDefault()}
    >
      <div
        className="flex items-center gap-0.5 rounded-lg px-1 py-1"
        style={{
          background: "var(--color-paper-raised)",
          border: "0.5px solid var(--color-rule)",
          boxShadow: "0 8px 30px rgba(0,0,0,0.18)",
        }}
      >
        {colorOpen ? (
          <>
            <ColorDot label="朱" color="seal" onClick={() => onHighlight("seal")} />
            <ColorDot label="墨" color="ink" onClick={() => onHighlight("ink")} />
            <ColorDot label="灰" color="neutral" onClick={() => onHighlight("neutral")} />
            <ToolbarBtn label="返回" onClick={() => setColorOpen(false)} />
          </>
        ) : (
          <>
            <ToolbarBtn label="高亮" onClick={() => setColorOpen(true)} />
            <Sep />
            <ToolbarBtn label="笔记" onClick={onNote} />
            <Sep />
            <ToolbarBtn label="重点" onClick={onEmphasis} />
            <Sep />
            <ToolbarBtn label="书签" onClick={onBookmark} />
            <Sep />
            <ToolbarBtn label="✕" onClick={onClose} dim />
          </>
        )}
      </div>
    </div>
  );
}

function ToolbarBtn({
  label,
  onClick,
  dim,
}: {
  label: string;
  onClick: () => void;
  dim?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-xs px-2.5 py-1 rounded transition-colors hover:bg-[var(--color-seal-soft)]"
      style={{
        color: dim ? "var(--color-ink-muted)" : "var(--color-ink)",
        fontFamily: "var(--font-display)",
      }}
    >
      {label}
    </button>
  );
}

function ColorDot({
  label,
  color,
  onClick,
}: {
  label: string;
  color: AnnotationColor;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`高亮 · ${label}`}
      className="flex items-center gap-1 text-xs px-2 py-1 rounded hover:bg-[var(--color-seal-soft)]"
      style={{ color: "var(--color-ink)" }}
    >
      <span
        className="inline-block w-3 h-3 rounded-full"
        style={{ background: COLOR_VAR[color], opacity: 0.85 }}
        aria-hidden
      />
      {label}
    </button>
  );
}

function Sep() {
  return <span className="w-px h-4 self-center" style={{ background: "var(--color-rule)" }} aria-hidden />;
}

// ---------------------------------------------------------------------------
// 笔记输入框 —— 写 / 改一条笺注（纯 textarea，不上富文本编辑器，善本克制）
// ---------------------------------------------------------------------------

export function NoteEditor({
  initial,
  quote,
  onSave,
  onCancel,
}: {
  initial: string;
  quote: string;
  onSave: (text: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "color-mix(in oklch, var(--color-ink) 28%, transparent)" }}
      onMouseDown={onCancel}
    >
      <div
        className="w-[28rem] max-w-[calc(100vw-2rem)] rounded-lg p-4"
        style={{
          background: "var(--color-paper-raised)",
          border: "0.5px solid var(--color-rule)",
          boxShadow: "0 12px 40px rgba(0,0,0,0.22)",
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {quote && (
          <div
            className="text-xs mb-3 pl-2.5 py-1 leading-relaxed"
            style={{ borderLeft: "2px solid var(--color-ink)", color: "var(--color-ink-muted)" }}
          >
            「{quote.length > 60 ? `${quote.slice(0, 60)}…` : quote}」
          </div>
        )}
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          rows={4}
          placeholder="写几句你的想法…"
          className="w-full rounded border px-3 py-2 text-sm resize-y"
          style={{
            borderColor: "var(--color-rule)",
            background: "var(--color-paper)",
            color: "var(--color-ink)",
          }}
        />
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="text-xs px-3 py-1.5 rounded border"
            style={{ borderColor: "var(--color-rule)", color: "var(--color-ink-muted)" }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => onSave(value)}
            className="text-xs px-3 py-1.5 rounded text-white"
            style={{ background: "var(--color-ink)", fontFamily: "var(--font-display)" }}
          >
            存这条笺注
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 已有标注的编辑 / 删除小卡（点已标注处浮出）
// ---------------------------------------------------------------------------

export function AnnotationActions({
  ann,
  onEditNote,
  onDelete,
  onClose,
}: {
  ann: Annotation;
  onEditNote: () => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "color-mix(in oklch, var(--color-ink) 24%, transparent)" }}
      onMouseDown={onClose}
    >
      <div
        className="w-[24rem] max-w-[calc(100vw-2rem)] rounded-lg p-4"
        style={{
          background: "var(--color-paper-raised)",
          border: "0.5px solid var(--color-rule)",
          boxShadow: "0 12px 40px rgba(0,0,0,0.22)",
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="text-xs opacity-60 mb-1.5">{KIND_LABEL[ann.kind]}</div>
        <div
          className="text-sm mb-3 pl-2.5 py-1 leading-relaxed"
          style={{ borderLeft: `2px solid ${COLOR_VAR[ann.color ?? "ink"]}`, color: "var(--color-ink)" }}
        >
          「{ann.anchor.quote.slice(0, 80) || "（书签 · 段级）"}」
        </div>
        {ann.note_text?.trim() && (
          <div className="text-sm mb-3 leading-relaxed" style={{ color: "var(--color-ink)" }}>
            {ann.note_text}
          </div>
        )}
        <div className="flex justify-between items-center">
          <button
            type="button"
            onClick={onDelete}
            className="text-xs px-3 py-1.5 rounded border hover:text-[var(--color-seal)]"
            style={{ borderColor: "var(--color-rule)", color: "var(--color-ink-muted)" }}
          >
            删除
          </button>
          <div className="flex gap-2">
            {(ann.kind === "note" || ann.kind === "bookmark") && (
              <button
                type="button"
                onClick={onEditNote}
                className="text-xs px-3 py-1.5 rounded text-white"
                style={{ background: "var(--color-ink)", fontFamily: "var(--font-display)" }}
              >
                改笺注
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="text-xs px-3 py-1.5 rounded border"
              style={{ borderColor: "var(--color-rule)", color: "var(--color-ink-muted)" }}
            >
              关
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

const KIND_LABEL: Record<AnnotationKind, string> = {
  bookmark: "书签",
  highlight: "高亮",
  note: "笺注",
  emphasis: "重点",
};

// ---------------------------------------------------------------------------
// 批注总览抽屉 —— 顶栏「批」点开，右侧滑出，列这本书所有标注，点一条跳位置
// ---------------------------------------------------------------------------

export function AnnotationOverview({
  annotations,
  onJump,
  onDelete,
}: {
  annotations: Annotation[];
  /** 点一条 → 跳到那章那处。 */
  onJump: (ann: Annotation) => void;
  onDelete: (ann: Annotation) => void;
}) {
  // 按章排，章内按段排，方便顺着读下来。
  const sorted = useMemo(
    () =>
      [...annotations].sort((a, b) => {
        if (a.anchor.chapter !== b.anchor.chapter)
          return a.anchor.chapter - b.anchor.chapter;
        return a.anchor.para_index - b.anchor.para_index;
      }),
    [annotations],
  );

  return (
    <>
      <div className="text-xs text-[var(--color-ink-muted)] px-2 pb-2 mb-1 border-b border-[var(--color-rule)]">
        我的批注 · 共 {sorted.length} 条
      </div>
      {sorted.length === 0 ? (
        <p className="px-2 py-6 text-xs text-[var(--color-ink-muted)] leading-relaxed">
          还没标过。读正文时选中一段文字，就能高亮 / 写笺注 / 标重点 / 加书签。
        </p>
      ) : (
        <ul className="space-y-1.5">
          {sorted.map((ann) => (
            <li key={ann.id}>
              <div
                className="rounded px-2.5 py-2 group"
                style={{
                  borderLeft: `2px solid ${COLOR_VAR[ann.color ?? "ink"]}`,
                  background: "var(--color-paper-sunken)",
                }}
              >
                <button
                  type="button"
                  onClick={() => onJump(ann)}
                  className="block w-full text-left"
                >
                  <div className="flex items-center gap-1.5 text-[10.5px] text-[var(--color-ink-muted)] mb-0.5">
                    <span>{KIND_LABEL[ann.kind]}</span>
                    <span aria-hidden>·</span>
                    <span>第 {ann.anchor.chapter} 章</span>
                  </div>
                  {ann.anchor.quote.trim() && (
                    <div className="text-xs text-[var(--color-ink)] leading-snug line-clamp-2">
                      {ann.anchor.quote.slice(0, 60)}
                    </div>
                  )}
                  {ann.note_text?.trim() && (
                    <div className="text-xs text-[var(--color-ink-muted)] leading-snug mt-0.5 line-clamp-2">
                      ✎ {ann.note_text}
                    </div>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(ann)}
                  className="mt-1 text-[10.5px] text-[var(--color-ink-muted)] opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-[var(--color-seal)] transition-opacity"
                >
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// DOM 选区 → 段内偏移 的工具
// ---------------------------------------------------------------------------

/** 从一个 DOM 节点往上找最近的标了 data-para 的段落元素。 */
function closestPara(node: Node | null): HTMLElement | null {
  let el: Node | null = node;
  while (el) {
    if (el instanceof HTMLElement && el.dataset.para !== undefined) return el;
    el = el.parentNode;
  }
  return null;
}

/**
 * 选区端点（container + offset）换算成「在段落纯文本里的字符偏移」。
 * 走 TreeWalker 累加该端点之前所有文本节点的长度。定不出返 null。
 */
function offsetInPara(
  paraEl: HTMLElement,
  container: Node,
  offset: number,
): number | null {
  if (typeof document === "undefined") return null;
  const walker = document.createTreeWalker(paraEl, NodeFilter.SHOW_TEXT);
  let acc = 0;
  let n = walker.nextNode();
  while (n) {
    if (n === container) return acc + offset;
    acc += (n.textContent ?? "").length;
    n = walker.nextNode();
  }
  // container 本身可能是元素节点（选到段末等）——退而求其次按累加长度
  if (container === paraEl) return Math.min(offset, acc);
  return null;
}

/** 朱 / 墨 / 中性色 + 当前前景，调出一个淡底（高亮 / 左线背景用）。 */
function tint(colorVar: string, _fg: string, alpha: number): string {
  return `color-mix(in oklch, ${colorVar} ${Math.round(alpha * 100)}%, transparent)`;
}
