// ---------------------------------------------------------------------------
// Timeline — 时间线 / 事件梳理（读者发明区）
//
// 点"梳理时间线"→ 调 /api/agent/timeline（整本进上下文按时序梳理事件）→ 竖向时间线。
// 每条带时间 / 事件 / 章节 / 原文出处。按需 fetch 省 token。沿用「全书透视」轻量子块风格。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

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

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-1">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          时间线
        </h3>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading
            ? "按时序梳理中（约 1 分钟）…"
            : events
              ? "重新梳理"
              : "梳理时间线"}
        </button>
      </div>
      <p className="text-sm text-[var(--color-ink-muted)] mb-3">
        把全书事件按真实时间先后理清（多线/倒叙也还原顺序）。点一条看原文出处。
      </p>

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label="按时序梳理时间线" />}

      {events && (
        <ol className="relative border-l border-[var(--color-rule)] ml-2">
          {events.map((ev, i) => (
            <li key={i} className="mb-4 ml-4">
              <span
                className="absolute -left-[5px] w-2.5 h-2.5 rounded-full"
                style={{ background: "var(--color-seal)" }}
                aria-hidden="true"
              />
              <button
                type="button"
                onClick={() => setOpenIdx(openIdx === i ? null : i)}
                className="text-left w-full"
              >
                {ev.time && (
                  <div className="text-xs text-[var(--color-seal)] mb-0.5">
                    {ev.time}
                  </div>
                )}
                <div
                  className="text-[14px] leading-relaxed text-[var(--color-ink)]"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {ev.event}
                </div>
                <div className="text-xs text-[var(--color-ink-muted)] mt-1 flex items-center gap-1.5">
                  <span>第 {ev.chapter} 章</span>
                  {ev.verified && <SealMark size={17} title="原文已核验" />}
                  <span className="ml-auto opacity-60">
                    {openIdx === i ? "收起原文" : "看原文"}
                  </span>
                </div>
              </button>
              {openIdx === i && ev.evidence && (
                <div
                  className="mt-1.5 border-l-2 border-[var(--color-seal)]/40 pl-3 py-1 text-[13px] leading-relaxed text-[var(--color-ink)]"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {ev.evidence}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}

      {events && !loading && <RunStats trace={trace} note={`${events.length} 个事件`} />}
    </div>
  );
}
