// ---------------------------------------------------------------------------
// AnnotatedReader — 精读注释层（WP-annotated-reading，#7）
//
// 调 /api/agent/annotations（按选中 layers 编排已有分析、收已核验结论）→ 返回的
// "有注释那些章"原文连续滚动显示，在 snippet 处浮朱砂小记号（沿用钤印视觉语言）。
// 点记号 → 右侧批注栏看注释 + 原文证据 +（跨章）跳到 target 章那处。
//
// evidence-first：每条注释都挂得到原文、点得开（BE 已滤掉 verified=false 的）。
// 分层开关（伏笔 / 母题 / 人物 / 矛盾）默认只开一两层——治"糊一脸"的闸（WP §53）。
// 记号密度上限：一段超 N 条折叠成「本段 N 条」（WP §67）。CPU-only、无重阅读器库——
// 纯文本子串定位 + 自写 DOM。
// ---------------------------------------------------------------------------

import { useMemo, useRef, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";
import { Select } from "./ui/FormControls";
import {
  READER_FONTS,
  READER_SIZES,
  loadReaderFontId,
  saveReaderFontId,
  loadReaderSizeId,
  saveReaderSizeId,
} from "./readerFont";

interface Annotation {
  layer: "foreshadow" | "motif" | "contradiction" | "entity";
  type: string;
  chapter: number;
  snippet: string;
  summary: string;
  target_chapter: number | null;
  target_snippet: string | null;
  // 逐字可定位（exact）才挂行间朱砂记号；转述类（approx）退章末批注、不进行间（WP §35）
  anchor: "exact" | "approx";
  target_anchor: "exact" | "approx" | null;
}

interface ChapterText {
  chapter: number;
  text: string;
}

interface AnnotatedReaderProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 四个图层的开关元信息——朱砂同色系，标签汉风一个词
const LAYERS: { id: Annotation["layer"]; label: string; needsInput?: "entity" | "motif" }[] = [
  { id: "foreshadow", label: "伏笔" },
  { id: "contradiction", label: "矛盾" },
  { id: "motif", label: "母题", needsInput: "motif" },
  { id: "entity", label: "人物", needsInput: "entity" },
];

// 一段里记号超这个数就折叠成「本段 N 条」（治"糊一脸"）
const MARKS_PER_PARA_CAP = 4;

// 归一化：去空白，便于把 snippet 在章原文里定位（BE 章原文按 chunk 拼接，
// 空白可能与 snippet 略有出入；定位只用来"贴在哪一段"，不要求逐字）。
function norm(s: string): string {
  return s.replace(/\s+/g, "");
}

export function AnnotatedReader({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: AnnotatedReaderProps) {
  const [layers, setLayers] = useState<Set<Annotation["layer"]>>(
    new Set(["foreshadow", "contradiction"]),
  );
  const [entity, setEntity] = useState("");
  const [motif, setMotif] = useState("");
  const [annotations, setAnnotations] = useState<Annotation[] | null>(null);
  const [chapters, setChapters] = useState<ChapterText[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 当前选中的注释（全局唯一索引），右侧批注栏据它显示
  const [selected, setSelected] = useState<number | null>(null);
  // 章正文阅读区的字体 / 字号——只作用于章正文，存 localStorage，刷新不丢
  const [fontId, setFontId] = useState<string>(loadReaderFontId);
  const [sizeId, setSizeId] = useState<string>(loadReaderSizeId);
  // 章节容器引用，用来"跳到 target 章那处"
  const chapterRefs = useRef<Map<number, HTMLDivElement | null>>(new Map());

  function pickFont(id: string) {
    setFontId(id);
    saveReaderFontId(id);
  }
  function pickSize(id: string) {
    setSizeId(id);
    saveReaderSizeId(id);
  }
  // 解析成实际样式值（找不到就回退到列表里的默认项）
  const readerFont =
    READER_FONTS.find((f) => f.id === fontId) ?? READER_FONTS[0];
  const readerSize =
    READER_SIZES.find((s) => s.id === sizeId) ??
    READER_SIZES.find((s) => s.id === "m") ??
    READER_SIZES[0];

  function toggleLayer(id: Annotation["layer"]) {
    setLayers((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function load() {
    setLoading(true);
    setError(null);
    setSelected(null);
    setAnnotations(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        layers: [...layers],
        provider,
        api_key: apiKey,
      };
      if (layers.has("entity") && entity.trim()) body.entity = entity.trim();
      if (layers.has("motif") && motif.trim()) body.motif = motif.trim();
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/annotations", {
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
      const data = (await resp.json()) as {
        annotations: Annotation[];
        chapters: ChapterText[];
        scanned: string[];
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      setAnnotations(data.annotations ?? []);
      setChapters([...(data.chapters ?? [])].sort((a, b) => a.chapter - b.chapter));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  // 给每条注释配一个稳定全局索引，再按章分组——批注栏按全局索引选中。
  const indexed = useMemo(
    () => (annotations ?? []).map((a, i) => ({ a, i })),
    [annotations],
  );
  const byChapter = useMemo(() => {
    const m = new Map<number, { a: Annotation; i: number }[]>();
    for (const item of indexed) {
      const arr = m.get(item.a.chapter) ?? [];
      arr.push(item);
      m.set(item.a.chapter, arr);
    }
    return m;
  }, [indexed]);

  const sel = selected != null ? annotations?.[selected] ?? null : null;

  function jumpToChapter(ch: number) {
    const el = chapterRefs.current.get(ch);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // 未跑过：配置 + 生成按钮
  if (!annotations) {
    const someInputMissing =
      (layers.has("entity") && !entity.trim()) ||
      (layers.has("motif") && !motif.trim());
    return (
      <div className="pt-4">
        <p className="text-sm text-[var(--color-ink-muted)] mb-4 leading-relaxed">
          读这本书的原文，读到某处行间浮一条带原文证据的批注，这里埋了伏笔、这句和别章矛盾、这是某母题的又一次复现。
          点记号看支撑它的原文。先选要哪几层（默认只开伏笔 + 矛盾，免得糊一脸）。
        </p>

        <LayerToggles
          layers={layers}
          onToggle={toggleLayer}
          entity={entity}
          setEntity={setEntity}
          motif={motif}
          setMotif={setMotif}
        />

        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey || layers.size === 0 || someInputMissing}
          className="mt-4 text-sm px-4 py-2 rounded bg-[var(--color-seal)] text-white hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {loading ? "读全书贴批注中（每层约 1 分钟）…" : "生成精读批注"}
        </button>

        {layers.size === 0 && (
          <p className="mt-2 text-xs text-[var(--color-ink-muted)]">至少选一层。</p>
        )}
        {someInputMissing && (
          <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
            选了「母题」/「人物」层要先填要追踪的母题 / 人物名。
          </p>
        )}
        {!apiKey && (
          <p className="mt-3 text-xs text-[var(--color-ink-muted)]">填了 API key 才能生成。</p>
        )}
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {loading && (
          <RunningProcess
            label="读全书贴精读批注"
            hint="按选中的层通读全书、把已有分析的结论挂回原文行间，每条都回原文核验，多选几层会更久。"
          />
        )}
      </div>
    );
  }

  const total = annotations.length;

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <LayerToggles
          layers={layers}
          onToggle={toggleLayer}
          entity={entity}
          setEntity={setEntity}
          motif={motif}
          setMotif={setMotif}
          compact
        />
        <div className="flex items-center gap-2 shrink-0">
          <ReaderTypeControls
            fontId={fontId}
            sizeId={sizeId}
            onFont={pickFont}
            onSize={pickSize}
          />
          <button
            type="button"
            onClick={load}
            disabled={loading || layers.size === 0}
            className="shrink-0 text-xs px-2.5 py-1.5 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
          >
            {loading ? "重出中…" : "换层重生成"}
          </button>
        </div>
      </div>

      {total === 0 ? (
        <p className="text-sm text-[var(--color-ink)]">
          这几层在全书没挂出核验得了的批注，换层、或填别的母题 / 人物名再试。
        </p>
      ) : (
        <>
          <p className="text-xs text-[var(--color-ink-muted)] mb-3">
            全书 {chapters.length} 章有批注、共 {total} 条。原文连续往下读，行间朱砂记号
            <SealMark size={15} className="mx-0.5 align-middle" /> 处点开看批注 + 原文证据。
          </p>

          {/* 左原文连续滚动 + 右批注栏 */}
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-4">
            {/* 原文阅读区 */}
            <div
              className="rounded border border-[var(--color-rule)] bg-[var(--color-paper)] p-4 lg:max-h-[640px] lg:overflow-y-auto"
            >
              {chapters.map((c) => (
                <div
                  key={c.chapter}
                  ref={(el) => {
                    chapterRefs.current.set(c.chapter, el);
                  }}
                  className="mb-6 last:mb-0 scroll-mt-2"
                >
                  <div
                    className="text-sm font-bold text-[var(--color-ink)] mb-2 pb-1 border-b border-[var(--color-rule)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    第 {c.chapter} 章
                  </div>
                  <ChapterBody
                    text={c.text}
                    annotations={byChapter.get(c.chapter) ?? []}
                    selected={selected}
                    onSelect={setSelected}
                    fontFamily={readerFont.fontFamily}
                    fontSize={readerSize.fontSize}
                    lineHeight={readerSize.lineHeight}
                  />
                </div>
              ))}
            </div>

            {/* 批注栏 */}
            <aside className="lg:sticky lg:top-2 lg:self-start">
              {sel ? (
                <AnnotationCard
                  ann={sel}
                  onJump={jumpToChapter}
                  onClose={() => setSelected(null)}
                />
              ) : (
                <div className="rounded border border-dashed border-[var(--color-rule)] p-4 text-sm text-[var(--color-ink-muted)] leading-relaxed">
                  点原文行间的朱砂记号
                  <SealMark size={15} className="mx-0.5 align-middle" />
                  看那条批注的内容和支撑它的原文证据。
                </div>
              )}
            </aside>
          </div>
        </>
      )}

      {loading ? (
        <RunningProcess label="重出精读批注" />
      ) : (
        <RunStats trace={trace} note={total > 0 ? `${total} 条批注` : undefined} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 图层开关 + 母题 / 人物输入框
// ---------------------------------------------------------------------------
function LayerToggles({
  layers,
  onToggle,
  entity,
  setEntity,
  motif,
  setMotif,
  compact = false,
}: {
  layers: Set<Annotation["layer"]>;
  onToggle: (id: Annotation["layer"]) => void;
  entity: string;
  setEntity: (s: string) => void;
  motif: string;
  setMotif: (s: string) => void;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "flex flex-wrap items-center gap-2" : ""}>
      <div className="flex flex-wrap items-center gap-2">
        {LAYERS.map((ly) => {
          const on = layers.has(ly.id);
          return (
            <button
              key={ly.id}
              type="button"
              onClick={() => onToggle(ly.id)}
              className="text-xs px-3 py-1.5 rounded-full border transition-colors"
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
              {ly.label}
            </button>
          );
        })}
      </div>
      {/* 选了母题 / 人物层才显示对应输入框 */}
      {(layers.has("motif") || layers.has("entity")) && (
        <div className={compact ? "flex flex-wrap gap-2" : "flex flex-wrap gap-2 mt-2"}>
          {layers.has("motif") && (
            <input
              value={motif}
              onChange={(e) => setMotif(e.target.value)}
              placeholder="母题（如：忠义 / 漂泊）"
              className="rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] px-2.5 py-1.5 text-xs focus:border-[var(--color-seal)] outline-none"
              style={{ fontFamily: "var(--font-display)", width: "11rem" }}
            />
          )}
          {layers.has("entity") && (
            <input
              value={entity}
              onChange={(e) => setEntity(e.target.value)}
              placeholder="人物 / 物（如：刘备 / 青釭剑）"
              className="rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] px-2.5 py-1.5 text-xs focus:border-[var(--color-seal)] outline-none"
              style={{ fontFamily: "var(--font-display)", width: "11rem" }}
            />
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 阅读字体 / 字号选择——只作用于章正文阅读区。两个克制的下拉，跟工具栏其它控件同
// 风格（CSS 变量、text-xs、与「换层重生成」一致的边框圆角）。选了即存 localStorage。
// ---------------------------------------------------------------------------
function ReaderTypeControls({
  fontId,
  sizeId,
  onFont,
  onSize,
}: {
  fontId: string;
  sizeId: string;
  onFont: (id: string) => void;
  onSize: (id: string) => void;
}) {
  // 工具栏里的紧凑变体：比默认下拉小一号字、窄一点 padding（右侧仍留出朱砂箭头的位）
  const compact = "text-xs pl-2 pr-8 py-1.5";
  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <label className="sr-only" htmlFor="reader-font">
        阅读字体
      </label>
      <Select
        id="reader-font"
        value={fontId}
        onChange={(e) => onFont(e.target.value)}
        className={compact}
        title="正文字体"
        aria-label="正文字体"
      >
        {READER_FONTS.map((f) => (
          <option key={f.id} value={f.id}>
            {f.label}
          </option>
        ))}
      </Select>
      <label className="sr-only" htmlFor="reader-size">
        阅读字号
      </label>
      <Select
        id="reader-size"
        value={sizeId}
        onChange={(e) => onSize(e.target.value)}
        className={compact}
        title="正文字号"
        aria-label="正文字号"
      >
        {READER_SIZES.map((s) => (
          <option key={s.id} value={s.id}>
            {s.label}
          </option>
        ))}
      </Select>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 一章原文 + 行间记号
//
// 行间只挂逐字可定位（anchor==="exact"）的注释：把章原文按段（双换行 / 单换行）切，
// 每段定位它命中的注释——snippet 归一化后是该段归一化文本的子串就算落在这段。段尾挂
// 记号（密度超上限折叠成「本段 N 条」）。
//
// 转述类（anchor==="approx"）不进行间——收进章末一个可折叠区「本章另有 N 条非逐字批注」，
// 点开走同一个批注栏看内容 + 原文证据，免得转述句乱挂章首冒充精确位置（WP §35）。
// ---------------------------------------------------------------------------
function ChapterBody({
  text,
  annotations,
  selected,
  onSelect,
  fontFamily,
  fontSize,
  lineHeight,
}: {
  text: string;
  annotations: { a: Annotation; i: number }[];
  selected: number | null;
  onSelect: (i: number | null) => void;
  fontFamily: string;
  fontSize: string;
  lineHeight: string;
}) {
  const paras = useMemo(() => {
    const split = text.split(/\n{1,}/).map((p) => p.trim()).filter(Boolean);
    return split.length > 0 ? split : [text];
  }, [text]);

  // 先按 anchor 分流：exact 进行间定位，approx 退章末批注区。
  const { exact, approx } = useMemo(() => {
    const ex: { a: Annotation; i: number }[] = [];
    const ap: { a: Annotation; i: number }[] = [];
    for (const item of annotations) {
      if (item.a.anchor === "exact") ex.push(item);
      else ap.push(item);
    }
    return { exact: ex, approx: ap };
  }, [annotations]);

  // 逐字注释每段对应哪些（按 snippet 子串定位）；定位不到的兜底挂章首段。
  const { perPara } = useMemo(() => {
    const buckets: { a: Annotation; i: number }[][] = paras.map(() => []);
    const normParas = paras.map(norm);
    const unplaced: { a: Annotation; i: number }[] = [];
    for (const item of exact) {
      const needle = norm(item.a.snippet);
      let placed = false;
      if (needle.length >= 2) {
        for (let p = 0; p < normParas.length; p += 1) {
          if (normParas[p].includes(needle)) {
            buckets[p].push(item);
            placed = true;
            break;
          }
        }
      }
      if (!placed) unplaced.push(item);
    }
    // 定位不到的兜底挂到首段（仍点得开）
    if (unplaced.length > 0 && buckets.length > 0) buckets[0].push(...unplaced);
    return { perPara: buckets };
  }, [paras, exact]);

  return (
    <div
      className="text-[var(--color-ink)] space-y-2"
      style={{ fontFamily, fontSize, lineHeight }}
    >
      {paras.map((p, idx) => (
        <p key={idx} className="whitespace-pre-wrap">
          {p}
          <ParaMarks
            items={perPara[idx]}
            selected={selected}
            onSelect={onSelect}
          />
        </p>
      ))}
      <ApproxNotes items={approx} selected={selected} onSelect={onSelect} />
    </div>
  );
}

// 章末「本章另有 N 条非逐字批注」可折叠区——转述类注释退到这里，点开走同一个批注栏。
function ApproxNotes({
  items,
  selected,
  onSelect,
}: {
  items: { a: Annotation; i: number }[];
  selected: number | null;
  onSelect: (i: number | null) => void;
}) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;

  return (
    <div className="mt-2 pt-2 border-t border-dashed border-[var(--color-rule)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
      >
        {open ? "收起" : "展开"}本章另有 {items.length} 条非逐字批注（无法精确定位行间，点开看内容 + 原文证据）
      </button>
      {open && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {items.map(({ a, i }) => (
            <button
              key={i}
              type="button"
              onClick={() => onSelect(selected === i ? null : i)}
              className="text-[11px] px-2 py-0.5 rounded border transition-colors"
              style={
                selected === i
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
              title={a.summary || a.snippet}
            >
              {a.type}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// 一段尾部的记号串：≤ 上限逐个铺；超上限折叠成「本段 N 条」可展开
function ParaMarks({
  items,
  selected,
  onSelect,
}: {
  items: { a: Annotation; i: number }[];
  selected: number | null;
  onSelect: (i: number | null) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;

  const collapsed = items.length > MARKS_PER_PARA_CAP && !expanded;

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className="inline-flex items-center align-middle ml-1 px-1.5 py-0.5 rounded text-[11px]"
        style={{
          background: "var(--color-seal-soft)",
          color: "var(--color-seal)",
          border: "1px solid var(--color-seal)",
        }}
        title="这一段批注较密，点开铺开"
      >
        本段 {items.length} 条
      </button>
    );
  }

  return (
    <span className="inline-flex items-center align-middle gap-0.5 ml-1">
      {items.map(({ a, i }) => (
        <button
          key={i}
          type="button"
          onClick={() => onSelect(selected === i ? null : i)}
          className="inline-flex"
          title={`${a.type}：${a.summary || a.snippet}`}
        >
          <SealMark
            size={selected === i ? 19 : 16}
            label={a.target_chapter != null ? "联" : "鉴"}
          />
        </button>
      ))}
    </span>
  );
}

// ---------------------------------------------------------------------------
// 批注栏卡片：注释内容 + 原文证据 +（跨章）跳到 target 章那处
// ---------------------------------------------------------------------------
function AnnotationCard({
  ann,
  onJump,
  onClose,
}: {
  ann: Annotation;
  onJump: (ch: number) => void;
  onClose: () => void;
}) {
  return (
    <div className="rounded border border-[var(--color-rule)] bg-white p-3">
      <div className="flex items-center justify-between mb-1">
        <span
          className="text-xs px-2 py-0.5 rounded-full"
          style={{ background: "var(--color-seal-soft)", color: "var(--color-seal)" }}
        >
          {ann.type}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
          aria-label="收起批注"
        >
          收起
        </button>
      </div>

      {ann.summary && (
        <p className="text-sm text-[var(--color-ink)] leading-relaxed mb-2">
          {ann.summary}
        </p>
      )}

      <div className="text-xs text-[var(--color-ink-muted)] mb-0.5 flex items-center gap-1.5">
        第 {ann.chapter} 章 · 这一处
        <SealMark size={15} title="原文已核验" />
      </div>
      <p
        className="text-[13px] leading-relaxed text-[var(--color-ink)] border-l-2 pl-2.5 py-0.5"
        style={{ borderColor: "var(--color-seal)", fontFamily: "var(--font-display)" }}
      >
        {ann.snippet}
      </p>

      {ann.target_chapter != null && ann.target_snippet && (
        <div className="mt-3 pt-2 border-t border-[var(--color-rule)]">
          <div className="text-xs text-[var(--color-ink-muted)] mb-0.5 flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              {ann.layer === "foreshadow" ? "回收处" : "另一处"} · 第 {ann.target_chapter} 章
              <SealMark size={15} title="原文已核验" />
            </span>
            <button
              type="button"
              onClick={() => onJump(ann.target_chapter as number)}
              className="text-[var(--color-seal)] hover:underline"
            >
              跳到那处
            </button>
          </div>
          <p
            className="text-[13px] leading-relaxed text-[var(--color-ink)] border-l-2 pl-2.5 py-0.5"
            style={{ borderColor: "var(--color-ink-muted)", fontFamily: "var(--font-display)" }}
          >
            {ann.target_snippet}
          </p>
        </div>
      )}
    </div>
  );
}
