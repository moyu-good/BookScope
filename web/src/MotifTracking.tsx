// ---------------------------------------------------------------------------
// MotifTracking — 主题母题追踪（读者发明区，功能队列第 6 个）
//
// 输一个主题/母题 → 调 /api/agent/motif-tracking（整本回溯它在全书的复现）→ 竖向轨迹。
// 每处带章节 / 怎么体现 / 原文出处，核验过盖钤印（核验不过的已在后端丢）。近 ConceptEvolution。
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

interface Occurrence {
  order: number;
  chapter: number;
  manifestation: string;
  snippet: string;
  verified?: boolean;
}

interface MotifTrackingProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  /** 从 agent 编排 drill-into 进来时预填的母题名 + 一个变化令牌，到了就自动跑一次。 */
  prefill?: { value: string; token: number } | null;
}

export function MotifTracking({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  prefill,
}: MotifTrackingProps) {
  const [motif, setMotif] = useState("");
  const [queried, setQueried] = useState<string | null>(null);
  const [occurrences, setOccurrences] = useState<Occurrence[] | null>(null);
  const [scanned, setScanned] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);

  // drill-into：prefill 令牌变化时填入母题名并自动跑（apiKey 缺时只填不跑）。
  useEffect(() => {
    if (!prefill || !prefill.value.trim()) return;
    setMotif(prefill.value);
    if (apiKey) void loadFor(prefill.value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.token]);

  async function load() {
    await loadFor(motif);
  }

  async function loadFor(raw: string) {
    const m = raw.trim();
    if (!m) return;
    setLoading(true);
    setError(null);
    setOpenIdx(null);
    setOccurrences(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        motif: m,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/motif-tracking", {
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
        motif: string;
        occurrences: Occurrence[];
        scanned: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      setScanned(data.scanned);
      setOccurrences(data.occurrences);
      setQueried(data.motif);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="pt-4">
      <p className="text-sm text-[var(--color-ink-muted)] mb-3 leading-relaxed">
        输一个主题/母题，看它在全书哪些地方复现——每处怎么体现、在哪章，带原文。
      </p>

      <form
        onSubmit={(ev) => {
          ev.preventDefault();
          load();
        }}
        className="flex gap-2 mb-5"
      >
        <input
          value={motif}
          onChange={(e) => setMotif(e.target.value)}
          placeholder="比如：正统 / 命运 / 背叛 / 某个反复出现的意象"
          className="flex-1 rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm focus:border-[var(--color-seal)] outline-none"
          style={{ fontFamily: "var(--font-display)" }}
        />
        <button
          type="submit"
          disabled={loading || !apiKey || !motif.trim()}
          className="shrink-0 text-sm px-4 py-2 rounded bg-[var(--color-seal)] text-white hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {loading ? "追踪中（约 1 分钟）…" : "追踪母题"}
        </button>
      </form>

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label={`追踪「${motif.trim()}」的复现`} />}

      {!scanned && occurrences && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          这本书太大，暂不支持母题追踪。
        </p>
      )}

      {scanned && occurrences && occurrences.length === 0 && queried && (
        <p className="text-sm text-[var(--color-ink)]">
          全书没追踪到「{queried}」的复现——可能书里没这个母题，或换个说法再试。
        </p>
      )}

      {occurrences && occurrences.length > 0 && (
        <>
          <p className="text-xs text-[var(--color-ink-muted)] mb-3">
            「{queried}」在全书复现 {occurrences.length} 处：
          </p>
          <ol className="relative border-l border-[var(--color-rule)] ml-2">
            {occurrences.map((o, i) => (
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
                    className="text-[14px] leading-relaxed text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {o.manifestation || "（复现）"}
                  </div>
                  <div className="text-xs text-[var(--color-ink-muted)] mt-1 flex items-center gap-1.5">
                    <span>第 {o.chapter} 章</span>
                    {o.verified && <SealMark size={17} title="原文已核验" />}
                    <span className="ml-auto opacity-60">
                      {openIdx === i ? "收起原文" : "看原文"}
                    </span>
                  </div>
                </button>
                {openIdx === i && o.snippet && (
                  <div
                    className="mt-1.5 border-l-2 border-[var(--color-seal)]/40 pl-3 py-1 text-[13px] leading-relaxed text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {o.snippet}
                  </div>
                )}
              </li>
            ))}
          </ol>
          {!loading && <RunStats trace={trace} note={`${occurrences.length} 处复现`} />}
        </>
      )}
    </div>
  );
}
