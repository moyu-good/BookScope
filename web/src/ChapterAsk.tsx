// ---------------------------------------------------------------------------
// ChapterAsk —— 问这一章 / 本章导读（WP-reading-experience §2.6，按章 scoped）
//
// 阅读器「鉴」里的"贴着在读这一章"入口:只问你正读的这一章,答案只从本章原文来。
// POST /api/agent/chapter-ask（后端只把这一章原文喂进 context）。留空问题 = 本章导读。
// 每条引文盖朱砂「鉴」= 本章内核验过。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { SealMark } from "./SealMark";

interface Citation {
  chapter: number;
  snippet: string;
  verified?: boolean;
}

interface ChapterAskResult {
  chapter: number;
  answer: string;
  citations: Citation[];
  scanned: boolean;
}

interface ChapterAskProps {
  sessionId: string;
  chapter: number | null;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export function ChapterAsk({
  sessionId,
  chapter,
  provider,
  apiKey,
  model,
  baseUrl,
}: ChapterAskProps) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ChapterAskResult | null>(null);

  async function ask(q: string) {
    if (chapter == null) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        chapter,
        question: q,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/chapter-ask", {
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
      setResult((await resp.json()) as ChapterAskResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  if (chapter == null) {
    return (
      <p className="text-sm text-[var(--color-ink-muted)]">
        先翻开一章再问，这里只问你正读的那一章。
      </p>
    );
  }

  return (
    <div>
      <p className="text-sm text-[var(--color-ink)] mb-3 leading-relaxed">
        只问<strong>第 {chapter} 章</strong>，答案只从这一章的原文来，不掺别章、不剧透后文。
      </p>

      <div className="flex gap-2 flex-wrap mb-3">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && question.trim() && !loading) ask(question.trim());
          }}
          placeholder={`问第 ${chapter} 章……（比如：这章谁占上风？为什么）`}
          disabled={loading || !apiKey}
          className="flex-1 min-w-[12rem] rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm focus:border-[var(--color-seal)] outline-none"
          style={{ fontFamily: "var(--font-display)" }}
        />
        <button
          type="button"
          onClick={() => ask(question.trim())}
          disabled={loading || !apiKey || !question.trim()}
          className="text-sm px-4 py-2 rounded bg-[var(--color-seal)] text-white hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          style={{ fontFamily: "var(--font-display)" }}
        >
          问
        </button>
        <button
          type="button"
          onClick={() => ask("")}
          disabled={loading || !apiKey}
          className="text-sm px-3 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
          title="不填问题，给这一章一个导读：讲了什么、谁登场、几个要点"
        >
          本章导读
        </button>
      </div>

      {!apiKey && (
        <p className="text-xs text-[var(--color-ink-muted)]">填了 API key 才能问。</p>
      )}
      {loading && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          <span className="animate-pulse">●</span> 读这一章、作答中…
        </p>
      )}
      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>{error}</p>
      )}

      {result && !loading && (
        <div className="mt-1">
          {!result.scanned ? (
            <p className="text-sm text-[var(--color-ink)]">
              这一章没取到可分析的原文，换一章试试。
            </p>
          ) : (
            <>
              <p className="text-[15px] leading-relaxed text-[var(--color-ink)] whitespace-pre-wrap mb-3" style={{ fontFamily: "var(--font-display)" }}>
                {result.answer}
              </p>
              {result.citations.length > 0 && (
                <div className="space-y-2">
                  <div className="text-xs text-[var(--color-ink-muted)]">本章原文出处：</div>
                  {result.citations.map((c, i) => (
                    <div
                      key={i}
                      className="text-[13px] leading-relaxed text-[var(--color-ink)] border-l-2 pl-2.5 py-0.5 flex items-start gap-1.5"
                      style={{ borderColor: "var(--color-seal)" }}
                    >
                      {c.verified && <SealMark size={15} className="mt-0.5" title="本章原文已核验" />}
                      <span style={{ fontFamily: "var(--font-display)" }}>{c.snippet}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
