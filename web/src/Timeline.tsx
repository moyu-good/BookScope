// ---------------------------------------------------------------------------
// Timeline — 时间线 / 事件梳理（读者发明区）
//
// 点"梳理时间线"→ 调 /api/agent/timeline（整本进上下文按时序梳理事件）→ 时间轴图。
// 命根子不是"按章节把事件列出来"，而是两件竖列表做不到的事：
//   1. 把倒叙 / 多线的故事还原成真实时序（events 已按 order 排好真实先后）；
//   2. 一眼看出哪里作者用了倒叙——某事件故事上早发生、却在靠后的章节才讲
//      （order 靠前但 chapter 靠后），或反之（提前讲了后面才发生的事）。
// 每条带时间 / 事件 / 章节 / 原文出处。按需 fetch 省 token。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { SealButton } from "./SealButton";

// 缩放区间：0.6 缩到能一屏看完几十上百条的全局，2.0 放大到看清单条局部。
const ZOOM_MIN = 0.6;
const ZOOM_MAX = 2;
const ZOOM_STEP = 0.2;
const clampZoom = (z: number) =>
  Math.round(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z)) * 100) / 100;

interface TimelineEvent {
  order: number;
  time: string;
  event: string;
  chapter: number;
  evidence: string;
  verified?: boolean;
}

interface TimelineProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 一个事件在轴上排布时算好的派生量：故事序位次、叙述序位次、错位方向与幅度。
interface PlacedEvent {
  ev: TimelineEvent;
  idx: number; // 在 events 里的下标（点开原文用它）
  newPeriod: boolean; // time 文本比上一条变了 = 进入新时期，轴上拉开留白
  dislocation: "flashback" | "foreshadow" | null; // 倒叙 / 预叙，null = 顺叙
  gapChapters: number; // 章序偏离故事序多少章（绝对值），标注强弱用
}

// 把后端按 order 排好的事件，算出每条的"章序 vs 故事序"错位。
//
// 思路：events 已按故事真实先后（order）排好，下标 i 就是故事序位次。
// 再看每条讲它的章号（chapter）在所有事件里排第几名——叙述序位次。
// 两个位次差得多 = 这段脱离了顺叙：
//   叙述序明显靠后（后面章节才讲早发生的事）→ 倒叙 flashback；
//   叙述序明显靠前（前面章节先讲了后发生的事）→ 预叙 / 插叙 foreshadow。
// 用位次差而非章号直接比，是因为不同书章号疏密差得远，位次更稳。
function placeEvents(events: TimelineEvent[]): PlacedEvent[] {
  // 章序位次：按 chapter 升序给每条一个名次（同章号并列取平均名次，避免抖动）。
  const byChapter = events
    .map((ev, idx) => ({ idx, chapter: ev.chapter }))
    .sort((a, b) => a.chapter - b.chapter || a.idx - b.idx);
  const narrativeRank = new Array<number>(events.length);
  byChapter.forEach((item, rank) => {
    narrativeRank[item.idx] = rank;
  });

  // 错位判定阈值：位次差要占总量一定比例才算"明显"，短列表放宽、长列表收紧，
  // 避免相邻一两位的正常抖动被误标成倒叙。至少差 2 位起判。
  const threshold = Math.max(2, Math.round(events.length * 0.15));

  return events.map((ev, i) => {
    const storyRank = i; // 已按 order 排好，下标即故事序位次
    const drift = narrativeRank[i] - storyRank; // >0 越靠后章节才讲
    let dislocation: PlacedEvent["dislocation"] = null;
    if (drift >= threshold) dislocation = "flashback"; // 早发生、后面才讲
    else if (drift <= -threshold) dislocation = "foreshadow"; // 后发生、前面先讲

    // 第一条永远起一个时期刻度；之后只在 time 文本变了才起新刻度。
    const prevTime = i > 0 ? events[i - 1].time?.trim() : "";
    const newPeriod = !!ev.time?.trim() && (i === 0 || ev.time.trim() !== prevTime);

    // 章序偏离故事序多少章（拿真实章号差，读者看得懂"隔了几章"）
    const gapChapters = (() => {
      // 找故事序上相邻那条的章号做参照，算这条讲得早/晚了几章
      if (dislocation === null) return 0;
      const ref = i > 0 ? events[i - 1].chapter : events[i + 1]?.chapter ?? ev.chapter;
      return Math.abs(ev.chapter - ref);
    })();

    return { ev, idx: i, newPeriod, dislocation, gapChapters };
  });
}

export function Timeline({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: TimelineProps) {
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 缩放倍率：长时间线缩小看全局、放大看局部。用 CSS transform: scale 作用在轴内容上，
  // 外层套一个可滚动 wrapper（放大后内容变高就滚动看）。这里只是个纯数字 state。
  const [zoom, setZoom] = useState(1);

  const placed = useMemo(() => (events ? placeEvents(events) : []), [events]);
  const dislocationCount = useMemo(
    () => placed.filter((p) => p.dislocation !== null).length,
    [placed],
  );

  async function load() {
    setLoading(true);
    setError(null);
    setOpenIdx(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/timeline", {
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
        events: TimelineEvent[];
        scanned: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      if (!data.scanned) {
        setError("时间线没读出来，稍后重试。");
      } else if (data.events.length === 0) {
        setError("没梳理出明显的事件时间线，稍后可重试。");
      } else {
        setEvents(data.events);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 空态（还没梳理）：统一入口卡（视觉表现根治 · FeatureEntryCard）
  if (!events) {
    return (
      <FeatureEntryCard
        title="时间线"
        lead="把全书事件按真实时间先后理清（多线 / 倒叙也还原顺序）。点一条看原文出处。"
        actionLabel="梳理时间线"
        loadingLabel="按时序梳理中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书按时序梳理，约 1 分钟；命中缓存秒出"
        error={error}
      >
        {loading && <RunningProcess label="按时序梳理时间线" />}
      </FeatureEntryCard>
    );
  }

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-1">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          时间线
        </h3>
        <div className="flex items-center gap-2">
          <ZoomControls
            zoom={zoom}
            onChange={(z) => setZoom(clampZoom(z))}
            onReset={() => setZoom(1)}
          />
          <SealButton
            size="sm"
            label="重新梳理"
            loadingLabel="梳理中…"
            loading={loading}
            onClick={load}
          />
        </div>
      </div>
      <p className="text-sm text-[var(--color-ink-muted)] mb-2">
        按故事真实先后排在一条主轴上；时期一变就拉开留白，看得出事件的疏密。
      </p>

      {/* 图例：读者要先懂"轴左的记号是倒叙" */}
      <TimelineLegend dislocationCount={dislocationCount} />

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label="按时序梳理时间线" />}

      {events && (
        // 可滚动 wrapper：给一个高度上限，放大后内容超出这层就在框里滚动看，
        // 缩小后内容变矮不滚。缩放只改里面内容的视觉尺寸，这个"框"本身不缩。
        <div
          className="tl-scroll"
          style={{ overflow: "auto", maxHeight: "min(72vh, 720px)" }}
        >
          <div
            className="rounded-md overflow-hidden"
            style={{
              background: "var(--color-paper-raised)",
              border: "1px solid var(--color-folio-edge)",
              // 缩放本体：锚在左上角，放大时顶边和左侧（时期刻度那列）都稳住不被裁掉，
              // 内容朝右下方长出去，超出就靠外层 wrapper 滚动看。
              transform: `scale(${zoom})`,
              transformOrigin: "top left",
              transition: "transform .18s ease",
            }}
          >
            {/* 手卷上轴杆 */}
            <div style={{ height: 7, background: "var(--color-ink)", opacity: 0.5 }} aria-hidden />

            {/* 时间轴：一条竖主轴，事件按故事序自上而下；倒叙 / 预叙的事件从轴上错开标出来 */}
            <div className="relative py-4 pr-3" style={{ paddingLeft: 92 }}>
              <style>{TIMELINE_CSS}</style>

              {/* 主轴竖线（朱砂淡），压在时期刻度与事件之间 */}
              <div
                className="absolute top-4 bottom-4"
                style={{
                  left: 84,
                  width: 2,
                  background:
                    "linear-gradient(var(--color-seal) 0%, color-mix(in srgb, var(--color-seal) 35%, transparent) 100%)",
                }}
                aria-hidden
              />

              <ol className="relative m-0 p-0 list-none tl-unroll">
                {placed.map((p, i) => (
                  <TimelineRow
                    key={p.idx}
                    placed={p}
                    animIndex={i}
                    open={openIdx === p.idx}
                    onToggle={() =>
                      setOpenIdx(openIdx === p.idx ? null : p.idx)
                    }
                  />
                ))}
              </ol>
            </div>

            {/* 手卷下轴杆 */}
            <div style={{ height: 7, background: "var(--color-ink)", opacity: 0.5 }} aria-hidden />
          </div>
        </div>
      )}

      {events && !loading && (
        <RunStats
          trace={trace}
          note={
            dislocationCount > 0
              ? `${events.length} 个事件 · ${dislocationCount} 处倒叙 / 插叙`
              : `${events.length} 个事件 · 基本顺叙`
          }
        />
      )}
    </div>
  );
}

// 缩放控件：一对克制的 − / + 加一个重置。数字善本风——细朱砂描边、小号、不喧宾夺主。
function ZoomControls({
  zoom,
  onChange,
  onReset,
}: {
  zoom: number;
  onChange: (z: number) => void;
  onReset: () => void;
}) {
  const atMin = zoom <= ZOOM_MIN + 0.001;
  const atMax = zoom >= ZOOM_MAX - 0.001;
  const atDefault = Math.abs(zoom - 1) < 0.001;
  return (
    <div
      className="inline-flex items-center rounded-sm overflow-hidden tl-zoom"
      style={{ border: "1px solid var(--color-folio-edge)" }}
    >
      <button
        type="button"
        className="tl-zoom-btn"
        onClick={() => onChange(zoom - ZOOM_STEP)}
        disabled={atMin}
        aria-label="缩小"
        title="缩小，看全局"
      >
        −
      </button>
      {/* 中间显示当前倍率，点一下回到 100%（等于重置） */}
      <button
        type="button"
        className="tl-zoom-pct"
        onClick={onReset}
        disabled={atDefault}
        aria-label="重置缩放"
        title="重置到 100%"
      >
        {Math.round(zoom * 100)}%
      </button>
      <button
        type="button"
        className="tl-zoom-btn"
        onClick={() => onChange(zoom + ZOOM_STEP)}
        disabled={atMax}
        aria-label="放大"
        title="放大，看局部"
      >
        +
      </button>
    </div>
  );
}

// 图例：把"轴左朱砂记号 = 倒叙"这条读图规则先讲清楚，否则读者看不懂错位标记。
function TimelineLegend({ dislocationCount }: { dislocationCount: number }) {
  if (dislocationCount === 0) {
    return (
      <p className="text-xs text-[var(--color-ink-muted)] mb-3 opacity-80">
        全书基本顺着讲，没有明显的倒叙 / 插叙。
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mb-3 text-xs text-[var(--color-ink-muted)]">
      <span className="inline-flex items-center gap-1.5">
        <span
          className="inline-block w-2.5 h-2.5 rounded-full"
          style={{ background: "var(--color-seal)" }}
          aria-hidden
        />
        倒叙：故事上早发生、后面章节才讲
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span
          className="inline-block w-2.5 h-2.5"
          style={{
            border: "1.5px solid var(--color-seal)",
            background: "var(--color-seal-soft)",
            transform: "rotate(45deg)",
          }}
          aria-hidden
        />
        插叙 / 预叙：后发生、却提前讲了
      </span>
    </div>
  );
}

// 一行事件。顺叙的贴着主轴排；倒叙 / 预叙的往轴左错开一截、连一条斜引线，一眼看出脱序。
function TimelineRow({
  placed,
  animIndex,
  open,
  onToggle,
}: {
  placed: PlacedEvent;
  animIndex: number;
  open: boolean;
  onToggle: () => void;
}) {
  const { ev, newPeriod, dislocation, gapChapters } = placed;
  const isDislocated = dislocation !== null;

  return (
    <li
      className="relative tl-row"
      style={{
        // 新时期上多留白，制造"疏"；同一时期挨着，制造"密"
        marginTop: newPeriod ? 26 : 10,
        // CSS 变量喂给 keyframes 做入场逐条延迟（不用 rAF，headless 也能跑）
        ["--tl-delay" as string]: `${Math.min(animIndex * 45, 700)}ms`,
      }}
    >
      {/* 时期刻度标签：立在主轴左侧，只在换时期时显示，等于把 time 当刻度 */}
      {newPeriod && ev.time && (
        <div
          className="absolute text-xs font-medium text-[var(--color-seal)] text-right leading-tight"
          style={{ left: -92, width: 74, top: 2, fontFamily: "var(--font-display)" }}
        >
          {ev.time}
        </div>
      )}

      {/* 轴上的节点：顺叙实心小圆点；倒叙实心大点；插叙空心菱形。
          倒叙 / 插叙的节点 hover 出一个说明浮层，讲清这个记号的意思。 */}
      <TimelineNode dislocation={dislocation} gapChapters={gapChapters} />

      {/* 错位事件的斜引线：从轴上节点连到错开的卡片，视觉上"拉出去" */}
      {isDislocated && (
        <span
          className="absolute"
          style={{
            left: -8,
            top: 7,
            width: 8,
            height: 2,
            background: "var(--color-seal)",
            opacity: 0.55,
          }}
          aria-hidden
        />
      )}

      <button
        type="button"
        onClick={onToggle}
        className={`text-left w-full rounded-sm ${isDislocated ? "tl-card-off" : "tl-card"}`}
        style={{
          // 错位事件整块往左错开一截并加朱砂描边，从顺叙的直线里"跳"出来
          marginLeft: isDislocated ? -14 : 0,
          padding: isDislocated ? "6px 9px" : "2px 0 2px 2px",
          background: isDislocated ? "var(--color-seal-soft)" : "transparent",
          border: isDislocated
            ? "1px solid color-mix(in srgb, var(--color-seal) 40%, transparent)"
            : "1px solid transparent",
        }}
      >
        {/* 倒叙 / 插叙标签：说破"这里作者用了倒叙"，命根子的显式标注 */}
        {isDislocated && (
          <span
            className="inline-flex items-center gap-1 mb-1 px-1.5 py-0.5 rounded-sm text-[var(--color-seal)]"
            style={{
              fontSize: "0.6875rem",
              lineHeight: 1.2,
              border: "1px solid color-mix(in srgb, var(--color-seal) 45%, transparent)",
              fontFamily: "var(--font-display)",
            }}
          >
            {dislocation === "flashback" ? "倒叙" : "插叙 / 预叙"}
            {gapChapters > 0 && (
              <span className="opacity-70">
                · {dislocation === "flashback" ? "隔" : "提前"} {gapChapters} 章
              </span>
            )}
          </span>
        )}

        <div
          className="text-body leading-relaxed text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {ev.event}
        </div>
        <div className="text-xs text-[var(--color-ink-muted)] mt-1 flex items-center gap-1.5">
          {/* 顺叙时 time 已在时期标签上，这里只在同一时期内补一个细时间，不喧宾 */}
          {!newPeriod && ev.time && (
            <span className="text-[var(--color-seal)] opacity-80">{ev.time}</span>
          )}
          <span>第 {ev.chapter} 章讲</span>
          {ev.verified ? (
            <SealMark size={17} title="原文已核验" />
          ) : (
            <span className="opacity-60">待核</span>
          )}
          {/* 展开提示：文字 + 会转的小箭头，明确"点这行能展开原文"，hover 时更亮 */}
          <span className="tl-afford ml-auto inline-flex items-center gap-1">
            {open ? "收起原文" : "看原文"}
            <svg
              width="10"
              height="10"
              viewBox="0 0 10 10"
              className="tl-chevron"
              style={{ transform: open ? "rotate(180deg)" : "none" }}
              aria-hidden
            >
              <path
                d="M2 3.5 L5 6.5 L8 3.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
        </div>
      </button>

      {open && (
        <div
          className="mt-1.5 ml-0.5 border-l-2 pl-3 py-1 text-body-sm leading-relaxed text-[var(--color-ink)] tl-quote"
          style={{
            fontFamily: "var(--font-display)",
            borderColor: "color-mix(in srgb, var(--color-seal) 40%, transparent)",
          }}
        >
          {ev.evidence ? ev.evidence : "这条没在原文里找到确切出处，待核。"}
        </div>
      )}
    </li>
  );
}

// 轴上节点：三种形态对应顺叙 / 倒叙 / 插叙，光看节点就分得出脱序类型。
// 倒叙 / 插叙的节点包一层 .tl-node-wrap，hover 出说明浮层（纯 CSS，不用 JS）。
function TimelineNode({
  dislocation,
  gapChapters,
}: {
  dislocation: PlacedEvent["dislocation"];
  gapChapters: number;
}) {
  if (dislocation === "flashback") {
    // 倒叙：实心大朱砂点，最跳眼
    return (
      <span className="tl-node-wrap absolute" style={{ left: -8, top: 3 }}>
        <span
          className="block rounded-full"
          style={{
            width: 13,
            height: 13,
            background: "var(--color-seal)",
            boxShadow: "0 0 0 3px var(--color-paper-raised)",
          }}
        />
        <NodeTip
          label="倒叙"
          desc={
            gapChapters > 0
              ? `故事上早发生，隔了 ${gapChapters} 章后面才讲。`
              : "故事上早发生，后面章节才讲。"
          }
        />
      </span>
    );
  }
  if (dislocation === "foreshadow") {
    // 插叙 / 预叙：空心菱形，跟倒叙区分开
    return (
      <span className="tl-node-wrap absolute" style={{ left: -7, top: 3 }}>
        <span
          className="block"
          style={{
            width: 11,
            height: 11,
            border: "2px solid var(--color-seal)",
            background: "var(--color-paper-raised)",
            transform: "rotate(45deg)",
            boxShadow: "0 0 0 2px var(--color-paper-raised)",
          }}
        />
        <NodeTip
          label="插叙 / 预叙"
          desc={
            gapChapters > 0
              ? `故事上后发生，却提前 ${gapChapters} 章先讲了。`
              : "故事上后发生，却提前讲了。"
          }
        />
      </span>
    );
  }
  // 顺叙：小实心点，贴着主轴
  return (
    <span
      className="absolute rounded-full"
      style={{
        left: -3,
        top: 6,
        width: 8,
        height: 8,
        background: "var(--color-seal)",
        boxShadow: "0 0 0 2px var(--color-paper-raised)",
      }}
      aria-hidden
    />
  );
}

// 节点 hover 浮层：解释这个记号是倒叙还是插叙、错开了几章。默认藏起，父节点 hover 才浮出。
function NodeTip({ label, desc }: { label: string; desc: string }) {
  return (
    <span className="tl-node-tip" role="tooltip">
      <span
        className="font-medium"
        style={{ color: "var(--color-seal)", fontFamily: "var(--font-display)" }}
      >
        {label}
      </span>
      <span className="tl-node-tip-desc">{desc}</span>
    </span>
  );
}

// 入场动画全走 CSS：整卷从上展开一次 + 每行按 --tl-delay 依次浮入。
// headless 预览把 rAF 节流，所以显示不依赖 JS 动画帧——纯 CSS keyframes。
const TIMELINE_CSS = `
@keyframes tl-unroll { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }
.tl-unroll { animation: tl-unroll .5s ease-out both; }
@keyframes tl-rowin { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
.tl-row { animation: tl-rowin .45s ease-out both; animation-delay: var(--tl-delay, 0ms); }
.tl-card { transition: background .15s ease, border-color .15s ease; }
.tl-card:hover { background: var(--color-paper-sunken); }
.tl-card-off { transition: border-color .15s ease; }
.tl-card-off:hover { border-color: var(--color-seal); }
@keyframes tl-quotein { from { opacity: 0; } to { opacity: 1; } }
.tl-quote { animation: tl-quotein .25s ease-out both; }
/* 展开提示：默认淡，整行 hover 时变朱砂、箭头微动，读者一眼知道能点开 */
.tl-afford { color: var(--color-ink-muted); opacity: .6; transition: color .15s ease, opacity .15s ease; }
.tl-card:hover .tl-afford, .tl-card-off:hover .tl-afford,
button:hover > * .tl-afford, button:focus-visible .tl-afford { color: var(--color-seal); opacity: 1; }
.tl-chevron { transition: transform .18s ease; }
/* 节点 hover 浮层：默认藏起，鼠标移到倒叙 / 插叙节点上才浮出 */
.tl-node-wrap { cursor: help; }
.tl-node-tip {
  position: absolute; left: 18px; top: -4px; z-index: 20;
  display: flex; flex-direction: column; gap: 2px;
  width: max-content; max-width: 220px;
  padding: 6px 9px; border-radius: 4px;
  background: var(--color-paper-raised);
  border: 1px solid color-mix(in srgb, var(--color-seal) 40%, transparent);
  box-shadow: 0 2px 10px rgba(0,0,0,.12);
  font-size: .75rem; line-height: 1.35;
  opacity: 0; visibility: hidden; transform: translateY(2px);
  transition: opacity .15s ease, transform .15s ease, visibility .15s;
  pointer-events: none;
}
.tl-node-wrap:hover .tl-node-tip, .tl-node-wrap:focus-within .tl-node-tip {
  opacity: 1; visibility: visible; transform: none;
}
.tl-node-tip-desc { color: var(--color-ink-muted); }
/* 缩放控件：细描边小按钮，朱砂 hover，禁用时变淡 */
.tl-zoom-btn, .tl-zoom-pct {
  background: var(--color-paper-raised); color: var(--color-ink-muted);
  border: none; cursor: pointer; user-select: none;
  transition: background .12s ease, color .12s ease;
  font-family: var(--font-display);
}
.tl-zoom-btn { width: 26px; height: 24px; font-size: 15px; line-height: 1; }
.tl-zoom-pct {
  min-width: 42px; height: 24px; font-size: 11px;
  border-left: 1px solid var(--color-folio-edge);
  border-right: 1px solid var(--color-folio-edge);
}
.tl-zoom-btn:hover:not(:disabled), .tl-zoom-pct:hover:not(:disabled) {
  background: var(--color-paper-sunken); color: var(--color-seal);
}
.tl-zoom-btn:disabled, .tl-zoom-pct:disabled { opacity: .35; cursor: default; }
@media (prefers-reduced-motion: reduce) {
  .tl-unroll, .tl-row, .tl-quote { animation: none; }
  .tl-chevron, .tl-node-tip { transition: none; }
}
`;
