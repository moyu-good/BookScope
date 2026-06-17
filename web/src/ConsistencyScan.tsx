// ---------------------------------------------------------------------------
// ConsistencyScan — 设定一致性扫描（exp-011 GO）
//
// 点"扫全书找矛盾"→ 调 /api/agent/consistency-scan（整本进上下文找前后矛盾）→ 列出每条
// 矛盾的两处对照原文 + 章号。两处都过原文核验才会显示（编的矛盾被滤掉）。书自洽则正面
// 提示"没扫出矛盾"。按需 fetch 省 token。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

interface Side {
  snippet: string;
  chapter: number;
  verified?: boolean;
}

interface Contradiction {
  topic: string;
  conflict: string;
  a: Side;
  b: Side;
}

interface ConsistencyScanProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export function ConsistencyScan({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: ConsistencyScanProps) {
  const [result, setResult] = useState<{
    contradictions: Contradiction[];
    scanned: boolean;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/consistency-scan", {
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
        contradictions: Contradiction[];
        scanned: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      setResult(data);
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
          设定一致性扫描
        </h3>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading
            ? "扫全书中（约 1 分钟）…"
            : result
              ? "重新扫"
              : "扫全书找矛盾"}
        </button>
      </div>
      <p className="text-sm text-[var(--color-ink-muted)] mb-3">
        扫全书找设定/人物前后矛盾（如第 5 章左撇子、第 80 章用右手）。每条两处对照原文，编的矛盾会被滤掉。
      </p>

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label="扫全书找设定矛盾" />}

      {result && !result.scanned && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          这本书太大，暂不支持全书一致性扫描。
        </p>
      )}

      {result && result.scanned && result.contradictions.length === 0 && (
        <p className="text-sm text-[var(--color-ink)]">
          没扫出明显的前后矛盾——这本书的设定挺自洽。
        </p>
      )}

      {result && result.contradictions.length > 0 && (
        <div className="space-y-4">
          {result.contradictions.map((c, i) => (
            <div
              key={i}
              className="rounded border border-[var(--color-rule)] bg-white p-3"
            >
              <p className="text-sm font-bold text-[var(--color-ink)]">
                {c.topic || "前后矛盾"}
              </p>
              {c.conflict && (
                <p className="text-xs text-[var(--color-ink-muted)] mt-0.5 mb-2">
                  {c.conflict}
                </p>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {[c.a, c.b].map((side, j) => (
                  <div
                    key={j}
                    className="border-l-2 border-[var(--color-seal)]/50 pl-3 py-1"
                  >
                    <div className="text-xs text-[var(--color-ink-muted)] mb-1 flex items-center gap-1.5">
                      <span>第 {side.chapter} 章</span>
                      {side.verified && <SealMark size={17} title="原文已核验" />}
                    </div>
                    <div
                      className="text-[13px] leading-relaxed text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {side.snippet}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {result && result.scanned && !loading && (
        <RunStats trace={trace} note={`${result.contradictions.length} 处矛盾`} />
      )}
    </div>
  );
}
