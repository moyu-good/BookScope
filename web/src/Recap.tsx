// ---------------------------------------------------------------------------
// Recap — 无剧透情节回顾（读者发明区，功能队列第 4 个）
//
// 输"读到第几章"→ 调 /api/agent/recap（只把 ≤X 章原文喂模型，后文物理上看不到）→
// 竖向前情要点，每条钉原文、盖钤印。无剧透是结构保证，不是 prompt 哀求。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

interface RecapPoint {
  order: number;
  point: string;
  chapter: number;
  snippet: string;
  verified?: boolean;
}

interface RecapProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  /** 阅读器里打开时把"你读到第几章"带进来，自动填好回顾终点（贴着在读处）。 */
  prefillChapter?: number;
}

export function Recap({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  prefillChapter,
}: RecapProps) {
  const [chapter, setChapter] = useState(
    prefillChapter && prefillChapter >= 1 ? String(prefillChapter) : "",
  );
  const [queried, setQueried] = useState<number | null>(null);
  const [points, setPoints] = useState<RecapPoint[] | null>(null);
  const [scanned, setScanned] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);

  async function load() {
    const x = parseInt(chapter, 10);
    if (!Number.isFinite(x) || x < 1) {
      setError("请输入你读到的章节号（≥ 1 的整数）。");
      return;
    }
    setLoading(true);
    setError(null);
    setOpenIdx(null);
    setPoints(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        up_to_chapter: x,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/recap", {
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
        up_to_chapter: number;
        points: RecapPoint[];
        scanned: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      setScanned(data.scanned);
      setPoints(data.points);
      setQueried(data.up_to_chapter);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="pt-4">
      <p className="text-sm text-[var(--color-ink-muted)] mb-3 leading-relaxed">
        告诉我你读到第几章，回顾到此为止的前情，后文绝不剧透（模型根本看不到后文）。
      </p>

      <form
        onSubmit={(ev) => {
          ev.preventDefault();
          load();
        }}
        className="flex items-center gap-2 mb-5"
      >
        <span className="text-sm text-[var(--color-ink-muted)]">我读到第</span>
        <input
          type="number"
          min={1}
          value={chapter}
          onChange={(e) => setChapter(e.target.value)}
          placeholder="X"
          className="w-20 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] px-3 py-2 text-sm text-center focus:border-[var(--color-seal)] outline-none"
        />
        <span className="text-sm text-[var(--color-ink-muted)]">章</span>
        <button
          type="submit"
          disabled={loading || !apiKey || !chapter.trim()}
          className="ml-1 shrink-0 text-sm px-4 py-2 rounded bg-[var(--color-seal)] text-white hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {loading ? "回顾中（约 1 分钟）…" : "回顾前情"}
        </button>
      </form>

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label="回顾前情（不读后文）" hint="只把你读到的章节喂进模型，后文物理上看不到，零剧透。" />}

      {!scanned && points && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          回顾失败，书太大、或这一章之前没识别到原文。换个章号或稍后重试。
        </p>
      )}

      {points && points.length > 0 && (
        <>
          <p className="text-xs text-[var(--color-ink-muted)] mb-3">
            读到第 {queried} 章为止的前情（{points.length} 条，不含后文）：
          </p>
          <ol className="relative border-l border-[var(--color-rule)] ml-2">
            {points.map((p, i) => (
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
                  <div
                    className="text-body leading-relaxed text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {p.point}
                  </div>
                  <div className="text-xs text-[var(--color-ink-muted)] mt-1 flex items-center gap-1.5">
                    <span>第 {p.chapter} 章</span>
                    {p.verified && <SealMark size={17} title="原文已核验" />}
                    <span className="ml-auto opacity-60">
                      {openIdx === i ? "收起原文" : "看原文"}
                    </span>
                  </div>
                </button>
                {openIdx === i && p.snippet && (
                  <div
                    className="mt-1.5 border-l-2 border-[var(--color-seal)]/40 pl-3 py-1 text-body-sm leading-relaxed text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {p.snippet}
                  </div>
                )}
              </li>
            ))}
          </ol>
          {!loading && <RunStats trace={trace} note={`${points.length} 条前情`} />}
        </>
      )}
    </div>
  );
}
