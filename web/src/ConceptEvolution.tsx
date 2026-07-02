// ---------------------------------------------------------------------------
// ConceptEvolution — 跨章概念演进对照（学习者发明区，功能队列第 5 个）
//
// 输一个概念 → 调 /api/agent/concept-evolution（整本回溯它怎么一步步发展）→ 竖向演进轨迹。
// 每阶段带章节 / 怎么发展 / 原文出处，核验过盖钤印（核验不过的已在后端丢）。近 EntityRecall。
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

interface Stage {
  order: number;
  chapter: number;
  development: string;
  snippet: string;
  verified?: boolean;
}

interface ConceptEvolutionProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  /** 从 agent 编排 drill-into 进来时预填的概念名 + 一个变化令牌，到了就自动跑一次。 */
  prefill?: { value: string; token: number } | null;
}

export function ConceptEvolution({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  prefill,
}: ConceptEvolutionProps) {
  const [concept, setConcept] = useState("");
  const [queried, setQueried] = useState<string | null>(null);
  const [stages, setStages] = useState<Stage[] | null>(null);
  const [scanned, setScanned] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);

  // drill-into：prefill 令牌变化时填入概念名并自动跑（apiKey 缺时只填不跑）。
  useEffect(() => {
    if (!prefill || !prefill.value.trim()) return;
    setConcept(prefill.value);
    if (apiKey) void loadFor(prefill.value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.token]);

  async function load() {
    await loadFor(concept);
  }

  async function loadFor(raw: string) {
    const c = raw.trim();
    if (!c) return;
    setLoading(true);
    setError(null);
    setOpenIdx(null);
    setStages(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        concept: c,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/concept-evolution", {
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
        concept: string;
        stages: Stage[];
        scanned: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      setScanned(data.scanned);
      setStages(data.stages);
      setQueried(data.concept);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="pt-4">
      <p className="text-sm text-[var(--color-ink-muted)] mb-3 leading-relaxed">
        输一个概念，看它在全书怎么一步步发展，每阶段在哪章、被怎么用/深化，带原文。
      </p>

      <form
        onSubmit={(ev) => {
          ev.preventDefault();
          load();
        }}
        className="flex gap-2 mb-5"
      >
        <input
          value={concept}
          onChange={(e) => setConcept(e.target.value)}
          placeholder="比如：制内市场 / 国家能力 / 某个理论概念"
          className="flex-1 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] px-3 py-2 text-sm focus:border-[var(--color-seal)] outline-none"
          style={{ fontFamily: "var(--font-display)" }}
        />
        <button
          type="submit"
          disabled={loading || !apiKey || !concept.trim()}
          className="shrink-0 text-sm px-4 py-2 rounded bg-[var(--color-seal)] text-white hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {loading ? "回溯中（约 1 分钟）…" : "看演进"}
        </button>
      </form>

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label={`回溯「${concept.trim()}」的演进`} />}

      {!scanned && stages && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          这本书太大，暂不支持概念演进回溯。
        </p>
      )}

      {scanned && stages && stages.length === 0 && queried && (
        <p className="text-sm text-[var(--color-ink)]">
          全书没回溯出「{queried}」的演进，可能书里没这个概念，或换个说法再试。
        </p>
      )}

      {stages && stages.length > 0 && (
        <>
          <p className="text-xs text-[var(--color-ink-muted)] mb-3">
            「{queried}」在全书的演进（{stages.length} 个阶段）：
          </p>
          <ol className="relative border-l border-[var(--color-rule)] ml-2">
            {stages.map((s, i) => (
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
                    {s.development || "（演进）"}
                  </div>
                  <div className="text-xs text-[var(--color-ink-muted)] mt-1 flex items-center gap-1.5">
                    <span>第 {s.chapter} 章</span>
                    {s.verified && <SealMark size={17} title="原文已核验" />}
                    <span className="ml-auto opacity-60">
                      {openIdx === i ? "收起原文" : "看原文"}
                    </span>
                  </div>
                </button>
                {openIdx === i && s.snippet && (
                  <div
                    className="mt-1.5 border-l-2 border-[var(--color-seal)]/40 pl-3 py-1 text-body-sm leading-relaxed text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {s.snippet}
                  </div>
                )}
              </li>
            ))}
          </ol>
          {!loading && <RunStats trace={trace} note={`${stages.length} 个阶段`} />}
        </>
      )}
    </div>
  );
}
