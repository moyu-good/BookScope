// ---------------------------------------------------------------------------
// ForeshadowArcs — 伏笔→回收弧线图（WP-foreshadow-payoff-arcs，伏笔判定 exp-008 GO）
//
// 点生成 → 调 /api/agent/foreshadow-arcs（整本进上下文抽伏笔配对）→ 自写 SVG arc diagram：
// 横轴一排章节，每条伏笔从埋点章拱到回收点章画一道弧。
//   · 已回收弧（resolved）：实线、朱砂色，弧从埋点拱到回收点落地，弧长 = 伏笔跨度。
//   · 断弧（dangling，埋了没回收）：灰虚线，从埋点拱起后悬空不落地 + 端点一个问号，
//     悬在基线更高处——"够不着对岸"，一眼挑出没填的坑（作家审稿最想看的）。
// 点弧线看两端原文（埋点 + 回收点；断弧只有埋点 + 一句"全书未找到回收"）。
// evidence-first：埋点核不过的弧 BE 已滤掉；回收点核不过的降级成断弧。
// CPU-only，不引重图库，弧就是 SVG path 二次贝塞尔——同节奏曲线 / 关系图自写 SVG。
// 有"只看断弧"过滤 + 进场逐弧描画动画（带冷却，重出才再放）。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { Checkbox } from "./ui/FormControls";

interface Arc {
  description: string;
  setup_chapter: number;
  payoff_chapter: number | null;
  setup_evidence: string;
  payoff_evidence: string;
  status: "resolved" | "dangling";
  setup_verified: boolean;
  payoff_verified: boolean;
  setup_match_score: number;
  payoff_match_score: number;
}

interface ForeshadowArcsProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

const W = 760;
const PAD_LEFT = 28;
const PAD_RIGHT = 28;
const BASE_Y = 230; // 章节基线纵坐标
const ARC_MAX_H = 150; // 弧顶距基线的最大高度
const DANGLE_LIFT = 24; // 断弧整体再抬高，悬在已回收弧上方
const H = 270;

export function ForeshadowArcs({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: ForeshadowArcsProps) {
  const [arcs, setArcs] = useState<Arc[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 空值三态（task #29 根一）：扫过全书确实没埋伏笔 = 确证全书没伏笔（笃定答案，正面显示），
  // 区别于扫失败（走 error）。单条弧的 status=dangling 是另一层确证（这条伏笔确证未回收）。
  const [confirmedNone, setConfirmedNone] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [onlyDangling, setOnlyDangling] = useState(false);
  // 进场动画：load 成功后 key 变 → SVG path 重新触发描画；冷却期内不重复放
  const [animKey, setAnimKey] = useState(0);

  async function load() {
    setLoading(true);
    setError(null);
    setConfirmedNone(false);
    setSelected(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/foreshadow-arcs", {
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
        arcs: Arc[];
        scanned?: boolean;
        confirmed_none?: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      if (!data.arcs || data.arcs.length === 0) {
        // 确证全书没伏笔(扫过全书且空)走正面笃定显示,不当 error;真扫失败才走 error。
        if (data.confirmed_none || data.scanned) {
          setConfirmedNone(true);
        } else {
          setError("没抽出伏笔弧，稍后重试。");
        }
      } else {
        setArcs(
          [...data.arcs].sort((a, b) => a.setup_chapter - b.setup_chapter),
        );
        setAnimKey((k) => k + 1);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 全书章号范围（取所有埋点 + 已回收的回收点的最小/最大），映射到横轴
  const { minCh, maxCh } = useMemo(() => {
    if (!arcs || arcs.length === 0) return { minCh: 1, maxCh: 1 };
    let lo = Infinity;
    let hi = -Infinity;
    for (const a of arcs) {
      lo = Math.min(lo, a.setup_chapter);
      hi = Math.max(hi, a.setup_chapter);
      if (a.payoff_chapter != null) {
        lo = Math.min(lo, a.payoff_chapter);
        hi = Math.max(hi, a.payoff_chapter);
      }
    }
    return { minCh: lo, maxCh: hi };
  }, [arcs]);

  if (!arcs) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          伏笔回收
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          每条伏笔从埋点章拱到回收点章画一道弧，埋了没回收的画成灰虚线悬空，一眼挑出没填的坑。点弧线看两端原文。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读全书找伏笔中（约 1 分钟）…" : "生成伏笔回收图"}
        </button>
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {/* 确证全书没伏笔（空值三态 task #29）：扫过全书确实没埋伏笔——笃定答案，正面显示，
            不是上面 error 那种像扫失败的红字。 */}
        {confirmedNone && (
          <div
            className="mt-3 rounded-md px-3.5 py-3 flex items-start gap-2.5"
            style={{
              background: "rgba(79, 122, 82, 0.07)",
              border: "1px solid rgba(79, 122, 82, 0.28)",
            }}
          >
            <svg width="18" height="18" viewBox="0 0 20 20" className="mt-0.5 shrink-0" aria-hidden>
              <circle cx="10" cy="10" r="9" fill="none" stroke="#4f7a52" strokeWidth="1.5" />
              <path d="M6 10.5l2.5 2.5L14.5 7" fill="none" stroke="#4f7a52" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div>
              <p
                className="text-sm font-bold"
                style={{ color: "#4f7a52", fontFamily: "var(--font-display)" }}
              >
                全书没有挂得上原文的伏笔
              </p>
              <p className="mt-0.5 text-[13px] leading-relaxed text-[var(--color-ink)]">
                读了全书，没找到前埋后收的伏笔线索。这是个确定的结果——不是没扫到。
              </p>
            </div>
          </div>
        )}
        {!apiKey && (
          <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
            填了 API key 才能生成。
          </p>
        )}
        {loading && (
          <RunningProcess
            label="读全书找伏笔回收"
            hint="整本书喂进模型抽伏笔配对，埋点和回收点都回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  const innerW = W - PAD_LEFT - PAD_RIGHT;
  const span = Math.max(1, maxCh - minCh);
  const xAt = (ch: number) => PAD_LEFT + ((ch - minCh) / span) * innerW;

  const shown = onlyDangling
    ? arcs.filter((a) => a.status === "dangling")
    : arcs;
  // 断弧画在最上层不被压住（设计：断弧优先渲染）
  const ordered = [...shown].sort((a, b) => {
    if (a.status === b.status) return 0;
    return a.status === "dangling" ? 1 : -1; // resolved 先画，dangling 后画压上层
  });

  const resolvedN = arcs.filter((a) => a.status === "resolved").length;
  const danglingN = arcs.length - resolvedN;

  const sel = selected != null ? arcs[selected] : null;

  // 一条已回收弧：埋点 → 回收点的二次贝塞尔拱（弧顶高度随跨度增大）
  function resolvedPath(a: Arc): string {
    const x1 = xAt(a.setup_chapter);
    const x2 = xAt(a.payoff_chapter as number);
    const spanFrac = Math.min(1, Math.abs(a.payoff_chapter! - a.setup_chapter) / span);
    const arcH = 30 + spanFrac * ARC_MAX_H;
    const cx = (x1 + x2) / 2;
    const cy = BASE_Y - arcH;
    return `M ${x1} ${BASE_Y} Q ${cx} ${cy} ${x2} ${BASE_Y}`;
  }

  // 一条断弧：从埋点拱起后悬空不落地——半截弧 + 端头悬在更高处（够不着对岸）
  function danglingPath(a: Arc): { d: string; tipX: number; tipY: number } {
    const x1 = xAt(a.setup_chapter);
    // 悬空终点：朝书末方向甩出一段固定长度，落点比基线高（不接任何章）
    const dir = a.setup_chapter < (minCh + maxCh) / 2 ? 1 : -1;
    const reach = Math.min(innerW * 0.22, 120);
    const tipX = Math.max(PAD_LEFT, Math.min(W - PAD_RIGHT, x1 + dir * reach));
    const arcH = 60 + DANGLE_LIFT;
    const tipY = BASE_Y - arcH * 0.7; // 端头悬在半空
    const cx = (x1 + tipX) / 2;
    const cy = BASE_Y - arcH;
    return { d: `M ${x1} ${BASE_Y} Q ${cx} ${cy} ${tipX} ${tipY}`, tipX, tipY };
  }

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          伏笔回收
        </h3>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "重出中…" : "重新生成"}
        </button>
      </div>

      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        {arcs.length} 条伏笔（{resolvedN} 条已回收、
        <span style={{ color: "var(--color-seal)" }}>{danglingN} 条断弧没回收</span>
        ）。实线朱弧 = 埋点拱到回收点（弧越长跨度越大）；灰虚线悬空 = 埋了没填的坑。点弧线看两端原文。
      </p>

      {danglingN > 0 && (
        <div className="flex items-center gap-3 mb-2 text-xs">
          <label className="flex items-center gap-1 cursor-pointer text-[var(--color-ink)]">
            <Checkbox
              checked={onlyDangling}
              onChange={(e) => {
                setOnlyDangling(e.target.checked);
                setSelected(null);
              }}
            />
            只看断弧（挑坑）
          </label>
        </div>
      )}

      <svg
        key={animKey}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full border border-[var(--color-rule)] rounded bg-white"
      >
        <style>{`
          @keyframes fa-draw { to { stroke-dashoffset: 0; } }
          .fa-arc { animation: fa-draw 1s ease-out forwards; }
        `}</style>

        {/* 章节基线 */}
        <line
          x1={PAD_LEFT}
          y1={BASE_Y}
          x2={W - PAD_RIGHT}
          y2={BASE_Y}
          stroke="var(--color-ink-muted)"
          strokeWidth={1}
        />

        {/* 章号刻度（min / mid / max 几个锚点，避免百回级糊成一片） */}
        {[minCh, Math.round((minCh + maxCh) / 2), maxCh].map((ch, i) => (
          <g key={`tick-${i}`}>
            <line
              x1={xAt(ch)}
              y1={BASE_Y}
              x2={xAt(ch)}
              y2={BASE_Y + 5}
              stroke="var(--color-ink-muted)"
              strokeWidth={1}
            />
            <text
              x={xAt(ch)}
              y={BASE_Y + 16}
              textAnchor="middle"
              fontSize={9}
              fill="var(--color-ink-muted)"
            >
              第{ch}章
            </text>
          </g>
        ))}

        {/* 弧线 */}
        {ordered.map((a) => {
          const idx = arcs.indexOf(a);
          const active = selected === idx;
          if (a.status === "resolved") {
            return (
              <g key={`arc-${idx}`} style={{ cursor: "pointer" }} onClick={() => setSelected(idx)}>
                {/* 加粗透明热区，便于点中细弧 */}
                <path d={resolvedPath(a)} fill="none" stroke="transparent" strokeWidth={12} />
                <path
                  className="fa-arc"
                  d={resolvedPath(a)}
                  fill="none"
                  stroke="var(--color-seal)"
                  strokeWidth={active ? 2.4 : 1.4}
                  strokeLinecap="round"
                  opacity={active ? 0.95 : 0.6}
                  style={{ strokeDasharray: 600, strokeDashoffset: 600 }}
                />
                {/* 两端落点 */}
                <circle cx={xAt(a.setup_chapter)} cy={BASE_Y} r={active ? 3.4 : 2.4} fill="var(--color-seal)" />
                <circle cx={xAt(a.payoff_chapter as number)} cy={BASE_Y} r={active ? 3.4 : 2.4} fill="var(--color-seal)" />
              </g>
            );
          }
          // 断弧
          const dp = danglingPath(a);
          return (
            <g key={`arc-${idx}`} style={{ cursor: "pointer" }} onClick={() => setSelected(idx)}>
              <path d={dp.d} fill="none" stroke="transparent" strokeWidth={12} />
              <path
                className="fa-arc"
                d={dp.d}
                fill="none"
                stroke="var(--color-ink-muted)"
                strokeWidth={active ? 2.2 : 1.3}
                strokeLinecap="round"
                strokeDasharray="5 4"
                opacity={active ? 0.95 : 0.55}
              />
              {/* 埋点落点（实心，有据） */}
              <circle cx={xAt(a.setup_chapter)} cy={BASE_Y} r={active ? 3.4 : 2.4} fill="var(--color-ink-muted)" />
              {/* 悬空端头 + 问号（够不着对岸） */}
              <circle cx={dp.tipX} cy={dp.tipY} r={5.5} fill="var(--color-paper)" stroke="var(--color-ink-muted)" strokeWidth={1} />
              <text
                x={dp.tipX}
                y={dp.tipY + 3}
                textAnchor="middle"
                fontSize={8}
                fill="var(--color-ink-muted)"
              >
                ?
              </text>
            </g>
          );
        })}
      </svg>

      {/* 图例 */}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-ink-muted)]">
        <span className="flex items-center gap-1">
          <svg width="22" height="8" aria-hidden>
            <path d="M1 7 Q11 -3 21 7" fill="none" stroke="var(--color-seal)" strokeWidth={1.4} />
          </svg>
          已回收
        </span>
        <span className="flex items-center gap-1">
          <svg width="22" height="8" aria-hidden>
            <path d="M1 7 Q11 0 19 2" fill="none" stroke="var(--color-ink-muted)" strokeWidth={1.3} strokeDasharray="3 2" />
          </svg>
          断弧（没回收）
        </span>
      </div>

      {sel && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            {sel.status === "resolved" ? (
              <>
                伏笔 · 第 {sel.setup_chapter} 章埋 → 第 {sel.payoff_chapter} 章回收
              </>
            ) : (
              <span style={{ color: "var(--color-seal)" }}>
                断弧 · 第 {sel.setup_chapter} 章埋，全书未找到回收
              </span>
            )}
          </p>
          {sel.description && (
            <p className="mt-1 text-sm text-[var(--color-ink)] leading-relaxed">
              {sel.description}
            </p>
          )}

          <div className="mt-2">
            <div className="text-xs text-[var(--color-ink-muted)] mb-0.5">
              埋点（第 {sel.setup_chapter} 章）{sel.setup_verified ? "· 原文已核验" : "· 原文未核验"}
            </div>
            <p
              className="text-sm leading-relaxed"
              style={{
                color: "var(--color-ink)",
                opacity: sel.setup_verified ? 1 : 0.45,
              }}
            >
              {sel.setup_evidence || "（无埋点原文）"}
            </p>
          </div>

          {sel.status === "resolved" ? (
            <div className="mt-2">
              <div className="text-xs text-[var(--color-ink-muted)] mb-0.5">
                回收点（第 {sel.payoff_chapter} 章）{sel.payoff_verified ? "· 原文已核验" : "· 原文未核验"}
              </div>
              <p
                className="text-sm leading-relaxed"
                style={{
                  color: "var(--color-ink)",
                  opacity: sel.payoff_verified ? 1 : 0.45,
                }}
              >
                {sel.payoff_evidence || "（无回收原文）"}
              </p>
            </div>
          ) : (
            <p className="mt-2 text-xs" style={{ color: "var(--color-seal)" }}>
              全书未找到回收原文，这个坑可能没填，建议人工复核。
            </p>
          )}
        </div>
      )}

      {loading ? (
        <RunningProcess label="重出伏笔回收图" />
      ) : (
        <RunStats trace={trace} note={`${arcs.length} 条伏笔`} />
      )}
    </div>
  );
}
