// ---------------------------------------------------------------------------
// StudyCards — 知识点卡片 + 启发测我（学习者发明区，功能队列第 8 个）
//
// 点"出卡片"→ 调 /api/agent/study-cards（整本出知识点卡）→ 卡片列表。
// 每张正面显示知识点 + 启发自测题（先自己想），点"翻看"展开解释 + 原文 + 钤印。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { SealButton } from "./SealButton";

interface Card {
  order: number;
  concept: string;
  point: string;
  question: string;
  chapter: number;
  snippet: string;
  verified?: boolean;
}

interface StudyCardsProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export function StudyCards({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: StudyCardsProps) {
  const [cards, setCards] = useState<Card[] | null>(null);
  const [scanned, setScanned] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<Set<number>>(new Set());
  const [trace, setTrace] = useState<RunTrace | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setRevealed(new Set());
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/study-cards", {
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
        cards: Card[];
        scanned: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      setScanned(data.scanned);
      setCards(data.cards);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  function toggle(i: number) {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  // 空态（还没出卡）：统一入口卡（视觉表现根治 · FeatureEntryCard）
  if (!cards) {
    return (
      <FeatureEntryCard
        title="知识卡片"
        lead="据书出知识点卡，每张一道启发自测题，先自己想，再翻看解释和原文。"
        actionLabel="出卡片"
        loadingLabel="出卡中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书出卡，约 1 分钟；命中缓存秒出"
        error={error}
      >
        {loading && <RunningProcess label="据全书出知识点卡片" />}
      </FeatureEntryCard>
    );
  }

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed pr-4">
          据书出知识点卡，每张一道启发自测题，先自己想，再翻看解释和原文。
        </p>
        <SealButton
          size="sm"
          label="重新出卡"
          loadingLabel="出卡中…"
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

      {loading && <RunningProcess label="据全书出知识点卡片" />}

      {!scanned && cards && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          这本书太大，暂不支持知识卡片。
        </p>
      )}

      {scanned && cards && cards.length === 0 && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          没出到可锚原文的知识点，稍后可重试。
        </p>
      )}

      {cards && cards.length > 0 && (
        <ol className="space-y-4">
          {cards.map((c, i) => {
            const open = revealed.has(i);
            return (
              <li
                key={i}
                className="rounded-md border pl-4 pr-3 py-3"
                style={{
                  borderColor: "var(--color-folio-edge)",
                  background: "var(--color-paper-raised)",
                }}
              >
                <div
                  className="text-body text-[var(--color-ink)]"
                  style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
                >
                  {c.concept}
                </div>
                {c.question && (
                  <div className="text-body-sm text-[var(--color-seal)] mt-1 leading-relaxed">
                    自测：{c.question}
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => toggle(i)}
                  className="text-xs text-[var(--color-ink-muted)] mt-2 hover:text-[var(--color-seal)] transition-colors"
                >
                  {open ? "收起" : "翻看答案 + 原文"}
                </button>
                {open && (
                  <div className="mt-2">
                    {c.point && (
                      <div
                        className="text-body leading-relaxed text-[var(--color-ink)] mb-2"
                        style={{ fontFamily: "var(--font-display)" }}
                      >
                        {c.point}
                      </div>
                    )}
                    {c.snippet && (
                      <div className="relative border-l-2 border-[var(--color-seal)]/40 pl-3 py-1">
                        <div className="text-xs text-[var(--color-ink-muted)] mb-1 flex items-center gap-1.5">
                          <span>第 {c.chapter} 章 · 原文依据</span>
                          {c.verified && (
                            <SealMark size={17} title="原文已核验" />
                          )}
                        </div>
                        <div
                          className="text-body-sm leading-relaxed text-[var(--color-ink)]"
                          style={{ fontFamily: "var(--font-display)" }}
                        >
                          {c.snippet}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}

      {cards && cards.length > 0 && !loading && (
        <RunStats trace={trace} note={`${cards.length} 张卡`} />
      )}
    </div>
  );
}
