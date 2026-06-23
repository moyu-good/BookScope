// ---------------------------------------------------------------------------
// NarrativeCurve — 多维叙事曲线（WP-multidim-narrative-curve，probe GO）
//
// 点生成 → 调 /api/agent/narrative-curve（整本进上下文逐章抽四维）→ 自写 SVG：
// 同一道横轴（章节序）叠四维——
//   · 张力（0-10）：填充面积，看全书绷得紧不紧的"形状"
//   · 情感正负（-5..+5）：零轴居中的折线，上方=往上走、下方=往下沉
//   · 主导 POV：横轴下方一条窄泳道，同视角同色块，切换处一眼可见
//   · 主/支线：泳道里实心(主线)/描边(支线)区分
// 点任一章看四维数值 + 判定依据原文。evidence-first：verified=false 的章淡化（核不过
// 不当确定结论画）。不引重图库（CPU-only），同节奏曲线 / character-flow 自写 SVG。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";

interface CurveChapter {
  chapter: number;
  tension: number; // 0-10
  sentiment: number; // -5..+5
  pov: string;
  mainline: boolean;
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface NarrativeCurveProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

const W = 760;
const PAD_LEFT = 28;
const PAD_RIGHT = 16;
const PAD_TOP = 14;
const TENSION_H = 130; // 张力 + 情感主图区高
const POV_H = 26; // POV 泳道高
const GAP = 10;
const H = PAD_TOP + TENSION_H + GAP + POV_H + 20;

// 山水长卷视图：山势=各章张力，平缓处=江水留白。同一份数据、换种画法。
const ART_TOP = 16;
const ART_RANGE = 118; // 张力 0-10 映射到的山高
const ART_BASE = ART_TOP + ART_RANGE; // 山脚 / 水岸基线
const ART_WATER_H = 20;
const ART_H = ART_BASE + ART_WATER_H + 22;

// POV 色带取一组克制的古籍色（不刺眼、可区分），循环用；"群像"固定中性灰
const POV_PALETTE = [
  "#8c6b4f",
  "#5f7a6b",
  "#9a5b52",
  "#6b6f8c",
  "#8a7a4a",
  "#5b7d8a",
  "#7a5b6b",
];

export function NarrativeCurve({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: NarrativeCurveProps) {
  const [chapters, setChapters] = useState<CurveChapter[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 维度开关——四线糊一起时可单独看
  const [showTension, setShowTension] = useState(true);
  const [showSentiment, setShowSentiment] = useState(true);
  // 视图：山水长卷（品读，默认）/ 朴素图（分析，看四维数值）
  const [artMode, setArtMode] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    setSelected(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/narrative-curve", {
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
        chapters: CurveChapter[];
        scanned?: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      if (!data.chapters || data.chapters.length === 0) {
        setError("没抽出叙事曲线，稍后重试。");
      } else {
        setChapters(
          [...data.chapters].sort((p, q) => p.chapter - q.chapter),
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 各 POV → 固定颜色（按首次出现顺序分配，"群像"走中性灰）
  const povColor = useMemo(() => {
    const map = new Map<string, string>();
    if (!chapters) return map;
    let next = 0;
    for (const c of chapters) {
      if (map.has(c.pov)) continue;
      if (c.pov === "群像") {
        map.set(c.pov, "var(--color-ink-muted)");
      } else {
        map.set(c.pov, POV_PALETTE[next % POV_PALETTE.length]);
        next += 1;
      }
    }
    return map;
  }, [chapters]);

  // 山水长卷派生量：山脊（近山=张力）、远山（张力平滑后压低，作烟霭层）、朱砂题点（核验
  // 过的高张力章，取前 6 个当"题在画上的名场面"）。山脚连成江岸，低张力处留白成水。
  const art = useMemo(() => {
    if (!chapters) return null;
    const m = chapters.length;
    const inner = W - PAD_LEFT - PAD_RIGHT;
    const xAt = (i: number) =>
      PAD_LEFT + (m <= 1 ? inner / 2 : (i / (m - 1)) * inner);
    const ridgeY = (t: number) =>
      ART_BASE - (Math.max(0, Math.min(10, t)) / 10) * ART_RANGE;
    const ridge = chapters.map((c, i) => `${xAt(i)},${ridgeY(c.tension)}`);
    // 远山：张力做 3 点滑动平均再压到 0.5 高、整体抬高一点，淡墨烟霭层
    const far = chapters.map((c, i) => {
      const a = chapters[Math.max(0, i - 1)].tension;
      const b = chapters[Math.min(m - 1, i + 1)].tension;
      const sm = (a + c.tension + b) / 3;
      return `${xAt(i)},${ART_BASE - (sm / 10) * ART_RANGE * 0.5 - 14}`;
    });
    const peaks = chapters
      .map((c, i) => ({ c, x: xAt(i), y: ridgeY(c.tension) }))
      .filter((p) => p.c.verified && p.c.tension >= 6)
      .sort((a, b) => b.c.tension - a.c.tension)
      .slice(0, 6);
    return { m, xAt, ridgeY, ridge, far, peaks };
  }, [chapters]);

  if (!chapters || !art) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          叙事曲线
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          同一道章节横轴上叠四维——张力起落、情感正负、视角切换、主/支线，看出整本书是个什么"形状"。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读全书出曲线中（约 1 分钟）…" : "生成叙事曲线"}
        </button>
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {!apiKey && (
          <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
            填了 API key 才能生成。
          </p>
        )}
        {loading && (
          <RunningProcess
            label="读全书出叙事曲线"
            hint="整本书喂进模型逐章判四维——每章判定都回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  const n = chapters.length;
  const innerW = W - PAD_LEFT - PAD_RIGHT;
  const slotW = innerW / n;
  const xAt = (i: number) => PAD_LEFT + i * slotW + slotW / 2;

  // 张力区：底在 tensionBottom，顶在 PAD_TOP
  const tensionBottom = PAD_TOP + TENSION_H;
  const tensionY = (t: number) =>
    tensionBottom - (Math.max(0, Math.min(10, t)) / 10) * TENSION_H;
  // 情感区：零轴在张力区竖向中线，±5 映射到 ±(TENSION_H/2)
  const zeroY = PAD_TOP + TENSION_H / 2;
  const sentY = (s: number) =>
    zeroY - (Math.max(-5, Math.min(5, s)) / 5) * (TENSION_H / 2);

  const povTop = tensionBottom + GAP;

  const barW = Math.max(2, slotW * 0.66);

  // 情感折线点串（只连相邻章）
  const sentPts = chapters.map((c, i) => `${xAt(i)},${sentY(c.sentiment)}`).join(" ");

  const sel = selected != null ? chapters.find((c) => c.chapter === selected) : null;
  const verifiedN = chapters.filter((c) => c.verified).length;

  // 图例：本书出现过的 POV（最多列 6 个，群像放最后）
  const povsInOrder = [...povColor.keys()];

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          叙事曲线
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
        {artMode ? (
          <>
            {n} 章（原文核验 {verifiedN}/{n} 章）。山势=各章张力，越高越紧、平缓处留白成江水；朱砂点=核验过的高潮章。点山看那章原文。要看情感/视角/主支线，切「朴素图」。
          </>
        ) : (
          <>
            {n} 章（原文核验 {verifiedN}/{n} 章）。柱=张力（越高越紧）、线=情感（零轴上方往上走、下方往下沉）、
            下方色带=主导视角（同色同视角、换色=切视角，实心主线/斜纹支线）。淡化的章=原文没核验上。点任一章看依据。
          </>
        )}
      </p>

      {/* 视图切换：山水（品读）/ 朴素（分析） */}
      <div className="flex items-center gap-2 mb-2 text-xs">
        {(["art", "plain"] as const).map((mode) => {
          const on = artMode === (mode === "art");
          return (
            <button
              key={mode}
              type="button"
              onClick={() => setArtMode(mode === "art")}
              className={[
                "px-2.5 py-1 rounded border transition-colors",
                on
                  ? "border-[var(--color-seal)] text-[var(--color-seal)]"
                  : "border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:border-[var(--color-seal)]",
              ].join(" ")}
            >
              {mode === "art" ? "山水长卷" : "朴素图"}
            </button>
          );
        })}
      </div>

      {/* 维度开关（只在朴素图下需要） */}
      {!artMode && (
        <div className="flex items-center gap-3 mb-2 text-xs">
          <label className="flex items-center gap-1 cursor-pointer text-[var(--color-ink)]">
            <input
              type="checkbox"
              checked={showTension}
              onChange={(e) => setShowTension(e.target.checked)}
            />
            张力
          </label>
          <label className="flex items-center gap-1 cursor-pointer text-[var(--color-ink)]">
            <input
              type="checkbox"
              checked={showSentiment}
              onChange={(e) => setShowSentiment(e.target.checked)}
            />
            情感
          </label>
        </div>
      )}

      {/* 山水长卷视图：山势=张力，留白成江水，朱砂=核验过的高潮章 */}
      {artMode && (
        <svg
          viewBox={`0 0 ${W} ${ART_H}`}
          className="w-full border border-[var(--color-rule)] rounded"
          style={{ background: "var(--color-paper)" }}
        >
          {/* 远山·烟霭层（张力平滑压低） */}
          <polygon
            points={`${art.far.join(" ")} ${W - PAD_RIGHT},${ART_BASE} ${PAD_LEFT},${ART_BASE}`}
            fill="var(--color-ink)"
            opacity={0.1}
          />
          {/* 近山·张力山脊（墨色填充 + 脊线） */}
          <polygon
            points={`${art.ridge.join(" ")} ${W - PAD_RIGHT},${ART_BASE} ${PAD_LEFT},${ART_BASE}`}
            fill="var(--color-ink)"
            opacity={0.32}
          />
          <polyline
            points={art.ridge.join(" ")}
            fill="none"
            stroke="var(--color-ink)"
            strokeWidth={1}
            strokeLinejoin="round"
            opacity={0.55}
          />
          {/* 江水·留白 + 涟漪 */}
          <rect
            x={PAD_LEFT}
            y={ART_BASE}
            width={W - PAD_LEFT - PAD_RIGHT}
            height={ART_WATER_H}
            fill="var(--color-paper-raised)"
            opacity={0.7}
          />
          <line
            x1={PAD_LEFT + 18}
            y1={ART_BASE + 7}
            x2={W * 0.4}
            y2={ART_BASE + 7}
            stroke="var(--color-rule)"
            strokeWidth={0.6}
          />
          <line
            x1={W * 0.5}
            y1={ART_BASE + 13}
            x2={W - PAD_RIGHT - 28}
            y2={ART_BASE + 13}
            stroke="var(--color-rule)"
            strokeWidth={0.6}
          />
          {/* 选中章：竖向朱砂线 + 山脊大点 */}
          {sel && (
            <g>
              <line
                x1={art.xAt(chapters.indexOf(sel))}
                y1={ART_TOP}
                x2={art.xAt(chapters.indexOf(sel))}
                y2={ART_BASE + ART_WATER_H}
                stroke="var(--color-seal)"
                strokeWidth={1}
                opacity={0.5}
              />
              <circle
                cx={art.xAt(chapters.indexOf(sel))}
                cy={art.ridgeY(sel.tension)}
                r={5}
                fill="var(--color-seal)"
              />
            </g>
          )}
          {/* 朱砂题点：核验过的高潮章 */}
          {art.peaks.map((p) => (
            <circle
              key={`pk-${p.c.chapter}`}
              cx={p.x}
              cy={p.y}
              r={selected === p.c.chapter ? 5 : 3.2}
              fill="var(--color-seal)"
              opacity={0.9}
            />
          ))}
          {/* 章号刻度 */}
          {chapters.map((c, i) =>
            n <= 20 || i % 5 === 0 ? (
              <text
                key={`ax-${c.chapter}`}
                x={art.xAt(i)}
                y={ART_H - 6}
                textAnchor="middle"
                fontSize={9}
                fill="var(--color-ink-muted)"
              >
                {c.chapter}
              </text>
            ) : null,
          )}
          {/* 每章透明热区——点选 */}
          {chapters.map((c, i) => {
            const hw = (W - PAD_LEFT - PAD_RIGHT) / n;
            return (
              <rect
                key={`ah-${c.chapter}`}
                x={art.xAt(i) - hw / 2}
                y={ART_TOP}
                width={hw}
                height={ART_BASE + ART_WATER_H - ART_TOP}
                fill="transparent"
                style={{ cursor: "pointer" }}
                onClick={() => setSelected(c.chapter)}
              />
            );
          })}
        </svg>
      )}

      {!artMode && (
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full border border-[var(--color-rule)] rounded bg-white"
      >
        <defs>
          {/* 支线章泳道斜纹 */}
          <pattern
            id="nc-branch"
            width="5"
            height="5"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="5" height="5" fill="var(--color-paper-raised)" />
            <line x1="0" y1="0" x2="0" y2="5" stroke="var(--color-rule)" strokeWidth="1.5" />
          </pattern>
        </defs>

        {/* 张力参考横线 + 情感零轴 */}
        {showTension &&
          [2, 4, 6, 8, 10].map((lvl) => (
            <line
              key={`t-${lvl}`}
              x1={PAD_LEFT}
              y1={tensionY(lvl)}
              x2={W - PAD_RIGHT}
              y2={tensionY(lvl)}
              stroke="var(--color-rule)"
              strokeWidth={0.5}
            />
          ))}
        {showSentiment && (
          <line
            x1={PAD_LEFT}
            y1={zeroY}
            x2={W - PAD_RIGHT}
            y2={zeroY}
            stroke="var(--color-ink-muted)"
            strokeWidth={0.7}
            strokeDasharray="2 2"
            opacity={0.6}
          />
        )}

        {/* 张力柱 */}
        {showTension &&
          chapters.map((c, i) => {
            const y = tensionY(c.tension);
            const h = tensionBottom - y;
            const active = selected === c.chapter;
            return (
              <rect
                key={`bar-${c.chapter}`}
                x={xAt(i) - barW / 2}
                y={y}
                width={barW}
                height={h}
                fill="var(--color-seal)"
                opacity={
                  c.verified
                    ? active
                      ? 0.85
                      : 0.28 + (c.tension / 10) * 0.32
                    : 0.12
                }
              />
            );
          })}

        {/* 情感折线 + 点 */}
        {showSentiment && (
          <>
            <polyline
              points={sentPts}
              fill="none"
              stroke="var(--color-ink)"
              strokeWidth={1.6}
              strokeLinejoin="round"
              strokeLinecap="round"
              opacity={0.85}
            />
            {chapters.map((c, i) => (
              <circle
                key={`s-${c.chapter}`}
                cx={xAt(i)}
                cy={sentY(c.sentiment)}
                r={selected === c.chapter ? 3.4 : 2.2}
                fill={c.verified ? "var(--color-ink)" : "var(--color-paper)"}
                stroke="var(--color-ink)"
                strokeWidth={c.verified ? 0 : 1}
                opacity={c.verified ? 0.95 : 0.5}
              />
            ))}
          </>
        )}

        {/* POV 泳道 + 主/支线 */}
        {chapters.map((c, i) => {
          const x = xAt(i) - slotW / 2 + 1;
          const w = Math.max(1, slotW - 2);
          const color = povColor.get(c.pov) ?? "var(--color-ink-muted)";
          return (
            <g key={`pov-${c.chapter}`}>
              <rect
                x={x}
                y={povTop}
                width={w}
                height={POV_H}
                fill={c.mainline ? color : "url(#nc-branch)"}
                opacity={c.verified ? (c.mainline ? 0.55 : 0.9) : 0.18}
              />
              {/* 支线章再叠一层视角色描边，区分是谁的支线 */}
              {!c.mainline && (
                <rect
                  x={x}
                  y={povTop}
                  width={w}
                  height={POV_H}
                  fill="none"
                  stroke={color}
                  strokeWidth={1.5}
                  opacity={c.verified ? 0.7 : 0.25}
                />
              )}
            </g>
          );
        })}

        {/* 章号刻度（隔几章标一个） */}
        {chapters.map((c, i) =>
          n <= 20 || i % 5 === 0 ? (
            <text
              key={`x-${c.chapter}`}
              x={xAt(i)}
              y={H - 6}
              textAnchor="middle"
              fontSize={9}
              fill="var(--color-ink-muted)"
            >
              {c.chapter}
            </text>
          ) : null,
        )}

        {/* 每章透明热区——点选 */}
        {chapters.map((c, i) => (
          <rect
            key={`hit-${c.chapter}`}
            x={xAt(i) - slotW / 2}
            y={PAD_TOP}
            width={slotW}
            height={povTop + POV_H - PAD_TOP}
            fill="transparent"
            style={{ cursor: "pointer" }}
            onClick={() => setSelected(c.chapter)}
          />
        ))}

        {/* 选中章竖向高亮线 */}
        {sel && (
          <line
            x1={xAt(chapters.indexOf(sel))}
            y1={PAD_TOP}
            x2={xAt(chapters.indexOf(sel))}
            y2={povTop + POV_H}
            stroke="var(--color-seal)"
            strokeWidth={1}
            opacity={0.5}
          />
        )}
      </svg>
      )}

      {/* POV 图例（只在朴素图下） */}
      {!artMode && povsInOrder.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--color-ink-muted)]">
          {povsInOrder.slice(0, 7).map((p) => (
            <span key={p} className="flex items-center gap-1">
              <span
                className="inline-block w-3 h-3 rounded-sm"
                style={{ background: povColor.get(p) }}
                aria-hidden
              />
              {p}
            </span>
          ))}
        </div>
      )}

      {sel && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            第 {sel.chapter} 章 · 张力 {sel.tension}/10 · 情感{" "}
            {sel.sentiment > 0 ? "↑" : sel.sentiment < 0 ? "↓" : "→"}
            {sel.sentiment} · 视角「{sel.pov}」· {sel.mainline ? "主线" : "支线"}
          </p>
          <p className="mt-1 text-sm text-[var(--color-ink)] leading-relaxed">
            {sel.evidence || "（这章没给出原文依据）"}
          </p>
          <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
            {sel.verified
              ? "原文已核验"
              : "原文未在书中比对命中——这章四维仅供参考"}
          </p>
        </div>
      )}

      {loading ? (
        <RunningProcess label="重出叙事曲线" />
      ) : (
        <RunStats trace={trace} note={`${n} 章`} />
      )}
    </div>
  );
}
