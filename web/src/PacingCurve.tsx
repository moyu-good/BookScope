// ---------------------------------------------------------------------------
// PacingCurve — 节奏 / 张力曲线（exp-012 GO）
//
// 点"生成节奏曲线"→ 调 /api/agent/pacing-curve（整本进上下文逐章判张力）→ SVG 柱状图。
// 每章一根柱，高低 = 张力 1-5（松章矮、高潮章高），点柱看这章的依据。按需 fetch 省 token。
// 不引重图库（合 CPU-only）。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";

interface PacingPoint {
  chapter: number;
  tension: number; // 1-5
  note: string;
}

interface PacingCurveProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

const W = 760;
const H = 200;
const PAD_BOTTOM = 22;
const PAD_TOP = 12;

export function PacingCurve({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: PacingCurveProps) {
  const [points, setPoints] = useState<PacingPoint[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);

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
      const resp = await fetch("/api/agent/pacing-curve", {
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
        points: PacingPoint[];
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      if (!data.points || data.points.length === 0) {
        setError("没生成出节奏曲线（书可能太大，或稍后重试）。");
      } else {
        setPoints(data.points);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  if (!points) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          节奏曲线
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          逐章看张力高低——哪几章松（铺垫多、拖沓）、哪几章是高潮。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读全书出曲线中（约 1 分钟）…" : "生成节奏曲线"}
        </button>
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {loading && <RunningProcess label="读全书出节奏曲线" />}
      </div>
    );
  }

  const n = points.length;
  const slotW = W / n;
  const barW = Math.max(3, slotW * 0.6);
  const plotH = H - PAD_BOTTOM - PAD_TOP;
  const sel = selected != null ? points.find((p) => p.chapter === selected) : null;

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          节奏曲线
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
        {n} 章 · 柱越矮越松（拖沓）、越高越紧（高潮）。点柱看这章依据。
      </p>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full border border-[var(--color-rule)] rounded bg-white"
      >
        {/* 张力 1-5 横向参考线 */}
        {[1, 2, 3, 4, 5].map((lvl) => {
          const y = PAD_TOP + plotH - (lvl / 5) * plotH;
          return (
            <line
              key={lvl}
              x1={0}
              y1={y}
              x2={W}
              y2={y}
              stroke="var(--color-rule)"
              strokeWidth={0.5}
            />
          );
        })}
        {points.map((p, i) => {
          const h = (p.tension / 5) * plotH;
          const x = i * slotW + (slotW - barW) / 2;
          const y = PAD_TOP + plotH - h;
          const active = selected === p.chapter;
          return (
            <g key={p.chapter}>
              <rect
                x={x}
                y={y}
                width={barW}
                height={h}
                fill="var(--color-seal)"
                opacity={active ? 1 : 0.35 + (p.tension / 5) * 0.5}
                style={{ cursor: "pointer" }}
                onClick={() => setSelected(p.chapter)}
              />
              {/* 每隔几章标个章号，避免拥挤 */}
              {(n <= 20 || i % 5 === 0) && (
                <text
                  x={x + barW / 2}
                  y={H - 8}
                  textAnchor="middle"
                  fontSize={9}
                  fill="var(--color-ink-muted)"
                >
                  {p.chapter}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {sel && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            第 {sel.chapter} 章 · 张力 {sel.tension}/5
          </p>
          <p className="mt-1 text-sm text-[var(--color-ink)] leading-relaxed">
            {sel.note || "（没给依据）"}
          </p>
        </div>
      )}

      {loading ? <RunningProcess label="重出节奏曲线" /> : <RunStats trace={trace} />}
    </div>
  );
}
