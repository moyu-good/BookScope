// ---------------------------------------------------------------------------
// NarrativeCurve — 事件密度曲线（1.5.x 重做，作者拍板）
//
// 砍三为二:旧的「节奏」(柱状画 tension)和「叙事曲线」(山水画 tension)画的是同一个东西、都吃
// 模型糊出来的张力标量,合并成这一条。纵轴从"张力分"换成"能数的事"——每章高度 = 事件数 + 转折数
// (从章脉 events / 伏笔回收数出来,每条能锚原文)。转折章标朱砂点,点一章 → 列出这章实际发生的
// 几件事,每件能看原文。张力留在选中章明细里标"模型判读",绝不再当纵轴。
//
// 点生成 → 调 /api/agent/narrative-curve(从共享章脉派生,命中缓存秒出)→ 画成事件密度长卷
// (见 ShanshuiCurve)。evidence-first:这章没事件就标"平铺过渡"。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { ShanshuiCurve, type CurveChapter } from "./ShanshuiCurve";

interface NarrativeCurveProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

function sentLabel(s: number): string {
  if (s > 0) return "偏暖";
  if (s < 0) return "偏沉";
  return "平";
}

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
        setChapters([...data.chapters].sort((p, q) => p.chapter - q.chapter));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  if (!chapters) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          叙事曲线
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          逐章数能数的事：每章高度 = 事件数 + 转折数（伏笔回收），一眼看出整本书哪几章戏多、哪几章是转折。点一章列出这章实际发生的几件事，每件回原文核验。
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
            hint="整本书喂进模型逐章精读出章脉，再数每章的事件和伏笔回收，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  const n = chapters.length;
  const turningN = chapters.filter((c) => c.is_turning).length;
  const sel = selected != null ? chapters.find((c) => c.chapter === selected) : null;

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
        {n} 章 · 转折章 {turningN} 处（朱砂点）。山高 = 这章的事件数 + 转折数，都是从章脉数出来、每条能回原文的，不是模型眼估的张力。鼠标移过去吸附最近章、点看这章发生了什么。
      </p>

      <ShanshuiCurve chapters={chapters} selected={selected} onSelect={setSelected} />

      {sel && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            第 {sel.chapter} 章 · {sel.event_count} 件事
            {sel.turning_count > 0 && (
              <span style={{ color: "var(--color-seal)" }}> · {sel.turning_count} 处转折</span>
            )}
          </p>

          {/* 这章实际发生的几件事，每件回原文核验 */}
          {sel.events.length > 0 ? (
            <ul className="mt-2 space-y-2">
              {sel.events.map((ev, i) => (
                <li key={`ev-${i}`} className="text-sm">
                  <p className="text-[var(--color-ink)]">· {ev.text}</p>
                  {ev.evidence ? (
                    <p className="mt-0.5 ml-3 text-xs text-[var(--color-ink-muted)] border-l-2 border-[var(--color-rule)] pl-2 leading-relaxed">
                      {ev.evidence}
                      <span className="ml-1" style={{ color: "var(--color-seal)" }} title="原文已核验">
                        ✓核
                      </span>
                    </p>
                  ) : (
                    <p className="mt-0.5 ml-3 text-xs text-[var(--color-ink-muted)]">
                      原文未在书中比对命中，待核
                    </p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-[var(--color-ink-muted)]">
              这章没数出关键事件，平铺过渡 / 待核。
            </p>
          )}

          {/* 转折（伏笔回收）单列 */}
          {sel.turning_points.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-bold" style={{ color: "var(--color-seal)" }}>
                这章的转折（伏笔回收）
              </p>
              <ul className="mt-1 space-y-2">
                {sel.turning_points.map((tp, i) => (
                  <li key={`tp-${i}`} className="text-sm">
                    <p className="text-[var(--color-ink)]">· {tp.hook}</p>
                    {tp.evidence ? (
                      <p className="mt-0.5 ml-3 text-xs text-[var(--color-ink-muted)] border-l-2 pl-2 leading-relaxed" style={{ borderColor: "var(--color-seal)" }}>
                        {tp.evidence}
                        <span className="ml-1" style={{ color: "var(--color-seal)" }} title="原文已核验">
                          ✓核
                        </span>
                      </p>
                    ) : (
                      <p className="mt-0.5 ml-3 text-xs text-[var(--color-ink-muted)]">
                        原文未命中，待核
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 张力等四维：只附带，标"模型判读"，不当纵轴 */}
          <p className="mt-3 pt-2 border-t border-[var(--color-rule)] text-xs text-[var(--color-ink-muted)]">
            模型判读（仅供参考，不当数据）：张力 {sel.tension}/10 · 情感{sentLabel(sel.sentiment)} · 视角「{sel.pov}」· {sel.mainline ? "主线" : "支线"}
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
