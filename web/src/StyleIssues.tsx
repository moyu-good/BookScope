// ---------------------------------------------------------------------------
// StyleIssues — 文体级毛病检测（作家发明区，功能队列第 3 个）
//
// 点"扫文体毛病"→ 调 /api/agent/style-issues（整本扫用词重复/视角越界/支线失踪）→
// 按类分组列出。每条原文核验过（编的已在后端丢），盖钤印。保守：没毛病就说没毛病。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { SealButton } from "./SealButton";

interface Issue {
  type: string;
  what: string;
  chapter: number;
  snippet: string;
  verified?: boolean;
}

interface StyleIssuesProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

const TYPE_LABEL: Record<string, string> = {
  repetition: "用词重复",
  pov: "视角越界",
  dropped_thread: "支线失踪",
};

export function StyleIssues({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: StyleIssuesProps) {
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const [scanned, setScanned] = useState(true);
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
      const resp = await fetch("/api/agent/style-issues", {
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
        issues: Issue[];
        scanned: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      setScanned(data.scanned);
      setIssues(data.issues);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const groups = issues
    ? (["repetition", "pov", "dropped_thread"] as const).map((t) => ({
        type: t,
        items: issues.filter((it) => it.type === t),
      }))
    : [];

  // 空态（还没扫）：统一入口卡（视觉表现根治 · FeatureEntryCard）
  if (!issues) {
    return (
      <FeatureEntryCard
        title="文体体检"
        lead="扫用词重复 / 视角越界 / 支线失踪，保守只报清楚的，每条钉原文，编的会被滤掉。"
        actionLabel="扫文体毛病"
        loadingLabel="扫全书中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书体检文体，约 1 分钟；命中缓存秒出"
        error={error}
      >
        {loading && <RunningProcess label="扫全书文体毛病" />}
      </FeatureEntryCard>
    );
  }

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed pr-4">
          扫用词重复 / 视角越界 / 支线失踪，保守只报清楚的，每条钉原文，编的会被滤掉。
        </p>
        <SealButton
          size="sm"
          label="重新扫"
          loadingLabel="扫全书中…"
          loading={loading}
          onClick={load}
          className="shrink-0"
        />
      </div>

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label="扫全书文体毛病" />}

      {!scanned && issues && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          这本书太大，暂不支持文体检测。
        </p>
      )}

      {scanned && issues && issues.length === 0 && (
        <p className="text-sm text-[var(--color-ink)]">
          没扫出明显的文体毛病，用词、视角、支线都还稳。
        </p>
      )}

      {issues && issues.length > 0 && (
        <div className="space-y-5">
          {groups
            .filter((g) => g.items.length > 0)
            .map((g) => (
              <div key={g.type}>
                <div
                  className="text-sm mb-2"
                  style={{
                    fontFamily: "var(--font-display)",
                    fontWeight: 600,
                    color: "var(--color-seal)",
                  }}
                >
                  {TYPE_LABEL[g.type]} · {g.items.length}
                </div>
                <ul className="space-y-3">
                  {g.items.map((it, i) => (
                    <li
                      key={i}
                      className="rounded-md border pl-4 pr-3 py-3"
                      style={{
                        borderColor: "var(--color-folio-edge)",
                        background: "var(--color-paper-raised)",
                      }}
                    >
                      <div
                        className="text-body leading-relaxed text-[var(--color-ink)] mb-2"
                        style={{ fontFamily: "var(--font-display)" }}
                      >
                        {it.what}
                      </div>
                      <div className="relative border-l-2 border-[var(--color-seal)]/40 pl-3 py-1">
                        <div className="text-xs text-[var(--color-ink-muted)] mb-1 flex items-center gap-1.5">
                          <span>第 {it.chapter} 章</span>
                          {it.verified && <SealMark size={17} title="原文已核验" />}
                        </div>
                        <div
                          className="text-body-sm leading-relaxed text-[var(--color-ink)]"
                          style={{ fontFamily: "var(--font-display)" }}
                        >
                          {it.snippet}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
        </div>
      )}

      {scanned && issues && !loading && (
        <RunStats trace={trace} note={`${issues.length} 处`} />
      )}
    </div>
  );
}
