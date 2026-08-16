// ---------------------------------------------------------------------------
// CrossWorkbench —— 跨文本对照工作台
//
// 报告是交付物（HTML 预览），这里是"干活台"：同一份对照数据用结构化面板
// 呈现——左边每本书的观点骨架，右边关系/概念/分歧，底部可继续追问。
// 数据来自 /agent/cross-book/data（与 HTML 报告同一套逻辑）。
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react";
import type { SessionMetadata } from "./BookShelf";

interface Perspective {
  title: string;
  slug: string;
  summary: string;
  stance: string;
  claims: { claim: string; chapter: number; kind: string }[];
}

interface Reason {
  nodes: { slug: string; label: string; stance: string }[];
  edges: { from: string; to: string; relation: string; rationale: string }[];
  concept_evolution: { concept: string; stages: { paper: string; stage: string; claim: string; evidence: string }[] }[];
  disagreements: { question: string; sides: { paper: string; stance: string; evidence: string }[] }[];
  narrative: string;
}

interface WorkbenchData {
  perspectives: Perspective[];
  reason: Reason;
  titles: string;
}

const REL_COLORS: Record<string, string> = {
  继承: "#2E7D5B",
  反驳: "#3D5A99",
  补充: "#B03A2E",
  落地: "#9C7A2E",
  检验: "#6A4E8E",
};

export function CrossWorkbench({
  sessions,
  provider,
  apiKey,
  model,
  baseUrl,
  onGenerateReport,
  onClose,
}: {
  sessions: SessionMetadata[];
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  onGenerateReport?: (sessions: SessionMetadata[]) => void;
  onClose: () => void;
}) {
  const [data, setData] = useState<WorkbenchData | null>(null);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [asking, setAsking] = useState(false);
  const [relationFilter, setRelationFilter] = useState("全部");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/agent/cross-book/data", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            book_session_ids: sessions.map((x) => x.session_id),
            provider,
            api_key: apiKey,
            model: model.trim() || undefined,
            base_url: baseUrl || undefined,
          }),
        });
        if (!resp.ok) {
          let msg = `加载对照数据失败（${resp.status}）`;
          try {
            const d = (await resp.json()) as { detail?: { message?: string } };
            if (d?.detail?.message) msg = d.detail.message;
          } catch {
            /* 非 JSON */
          }
          if (!cancelled) setError(msg);
          return;
        }
        const body = (await resp.json()) as WorkbenchData;
        if (!cancelled) setData(body);
      } catch {
        if (!cancelled) setError("加载对照数据失败：网络错误");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessions, provider, apiKey, model, baseUrl]);

  const submitAsk = async () => {
    const q = question.trim();
    if (!q || asking || !data) return;
    setAsking(true);
    setAnswer("");
    try {
      const resp = await fetch("/api/agent/cross-book/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          book_session_ids: sessions.map((x) => x.session_id),
          question: q,
          provider,
          api_key: apiKey,
          model: model.trim() || undefined,
          base_url: baseUrl || undefined,
        }),
      });
      if (!resp.ok) {
        let msg = `追问失败（${resp.status}）`;
        try {
          const d = (await resp.json()) as { detail?: { message?: string } };
          if (d?.detail?.message) msg = d.detail.message;
        } catch {
          /* 非 JSON */
        }
        setError(msg);
        return;
      }
      const body = (await resp.json()) as { answer: string };
      setAnswer(body.answer);
    } catch {
      setError("追问失败：网络错误");
    } finally {
      setAsking(false);
    }
  };

  const exportJson = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "cross-workbench.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      className="fixed inset-0 z-[210] flex flex-col bg-[var(--color-paper)]"
      role="dialog"
      aria-modal="true"
      aria-label="跨文本对照工作台"
    >
      {/* 顶栏 */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 border-b border-[var(--color-rule)]"
        style={{ background: "var(--color-paper-raised)" }}
      >
        <span className="text-sm font-bold text-[var(--color-seal)] truncate" style={{ fontFamily: "var(--font-display)" }}>
          🔬 对照工作台
        </span>
        <span className="text-xs text-[var(--color-ink-muted)] truncate">
          {data ? data.titles : "加载中…"}
        </span>
        {data && (
          <button
            type="button"
            onClick={exportJson}
            className="text-xs px-3 py-1.5 rounded-md border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition"
          >
            导出 JSON
          </button>
        )}
        {onGenerateReport && (
          <button
            type="button"
            onClick={() => {
              onClose();
              onGenerateReport(sessions);
            }}
            className="ml-auto text-xs px-3 py-1.5 rounded-md bg-[var(--color-seal)] text-white hover:brightness-110 transition"
            style={{ fontFamily: "var(--font-display)" }}
          >
            生成 HTML 报告
          </button>
        )}
        <button
          type="button"
          onClick={onClose}
          className="text-xs px-3 py-1.5 rounded-md border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] transition"
        >
          关闭
        </button>
      </div>

      {error && (
        <div className="px-4 py-2 text-xs text-[var(--color-seal)]">⚠️ {error}</div>
      )}

      {!data ? (
        <div className="flex-1 flex items-center justify-center text-sm text-[var(--color-ink-muted)] italic">
          {error ? "加载失败" : "正在整理各书观点与关系…"}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* 左：每本书观点骨架 */}
          <div>
            <h3 className="text-xs font-bold text-[var(--color-ink-muted)] mb-2" style={{ fontFamily: "var(--font-display)" }}>
              各书观点
            </h3>
            <div className="flex flex-col gap-3">
              {data.perspectives.map((p) => (
                <div
                  key={p.slug}
                  className="rounded-md border border-[var(--color-rule)] p-3"
                  style={{ background: "var(--color-paper-raised)" }}
                >
                  <div className="text-sm font-bold text-[var(--color-ink)]">{p.title}</div>
                  <div className="text-[10px] text-[var(--color-ink-muted)] mb-1">立场：{p.stance || "未标"}</div>
                  <p className="text-xs text-[var(--color-ink)] leading-relaxed mb-2">{p.summary}</p>
                  <ul className="flex flex-col gap-1">
                    {(p.claims || []).map((c, i) => (
                      <li key={i} className="text-xs text-[var(--color-ink-2)]">
                        <span className="text-[var(--color-seal)]">第{c.chapter}章</span> · {c.claim}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            {data.reason.narrative && (
              <div
                className="mt-3 rounded-md border border-[var(--color-rule)] p-3 text-xs leading-relaxed text-[var(--color-ink)]"
                style={{ background: "var(--color-paper-raised)" }}
              >
                <span className="font-bold text-[var(--color-seal)]">总体逻辑</span>
                <div className="mt-1">{data.reason.narrative}</div>
              </div>
            )}
          </div>

          {/* 右：关系 + 概念/分歧 + 追问 */}
          <div>
            <h3 className="text-xs font-bold text-[var(--color-ink-muted)] mb-2" style={{ fontFamily: "var(--font-display)" }}>
              关系网（{data.reason.edges.length} 条）
            </h3>
            <div className="flex flex-wrap items-center gap-1 mb-2">
              {(() => {
                const counts = data.reason.edges.reduce<Record<string, number>>((acc, e) => {
                  acc[e.relation] = (acc[e.relation] || 0) + 1;
                  return acc;
                }, {});
                return ["全部", "继承", "反驳", "补充", "落地", "检验"].map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setRelationFilter(r)}
                    className={`text-[10px] px-2 py-0.5 rounded-full border transition-colors ${
                      relationFilter === r
                        ? "border-[var(--color-seal)] text-[var(--color-seal)] bg-[var(--color-seal-soft)]"
                        : "border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)]"
                    }`}
                  >
                    {r === "全部" ? `全部 ${data.reason.edges.length}` : `${r} ${counts[r] || 0}`}
                  </button>
                ));
              })()}
            </div>
            <div className="flex flex-col gap-2">
              {data.reason.edges.filter((e) => relationFilter === "全部" || e.relation === relationFilter).length === 0 ? (
                <p className="text-sm text-[var(--color-ink-muted)] italic">暂无明显关系。</p>
              ) : (
                data.reason.edges.filter((e) => relationFilter === "全部" || e.relation === relationFilter).map((e, i) => (
                  <div
                    key={i}
                    className="rounded-md border border-[var(--color-rule)] px-3 py-2 text-xs"
                    style={{ background: "var(--color-paper-raised)" }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-[var(--color-ink)]">{e.from}</span>
                      <span style={{ color: REL_COLORS[e.relation] ?? "var(--color-ink-2)" }}>
                        —{e.relation}→
                      </span>
                      <span className="font-bold text-[var(--color-ink)]">{e.to}</span>
                    </div>
                    <div className="mt-1 text-[var(--color-ink-2)]">{e.rationale}</div>
                  </div>
                ))
              )}
            </div>

            {data.reason.concept_evolution.length > 0 && (
              <>
                <h3 className="text-xs font-bold text-[var(--color-ink-muted)] mt-4 mb-2" style={{ fontFamily: "var(--font-display)" }}>
                  概念演进
                </h3>
                <div className="flex flex-col gap-2">
                  {data.reason.concept_evolution.map((c, i) => (
                    <div key={i} className="rounded-md border border-[var(--color-rule)] px-3 py-2 text-xs" style={{ background: "var(--color-paper-raised)" }}>
                      <span className="font-bold text-[var(--color-ink)]">{c.concept}</span>
                      <ul className="mt-1 flex flex-col gap-1 text-[var(--color-ink-2)]">
                        {c.stages.map((st, j) => (
                          <li key={j}>《{st.paper}》 {st.stage}：{st.claim}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </>
            )}

            {data.reason.disagreements.length > 0 && (
              <>
                <h3 className="text-xs font-bold text-[var(--color-ink-muted)] mt-4 mb-2" style={{ fontFamily: "var(--font-display)" }}>
                  分歧
                </h3>
                <div className="flex flex-col gap-2">
                  {data.reason.disagreements.map((d, i) => (
                    <div key={i} className="rounded-md border border-[var(--color-rule)] px-3 py-2 text-xs" style={{ background: "var(--color-paper-raised)" }}>
                      <span className="font-bold text-[var(--color-ink)]">{d.question}</span>
                      <ul className="mt-1 flex flex-col gap-1 text-[var(--color-ink-2)]">
                        {d.sides.map((sd, j) => (
                          <li key={j}>《{sd.paper}》 {sd.stance}：{sd.evidence}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* 追问 */}
            <div className="mt-4 rounded-md border px-3 py-2" style={{ background: "var(--color-seal-soft)", borderColor: "color-mix(in oklch, var(--color-seal) 30%, transparent)" }}>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") void submitAsk(); }}
                  placeholder="追问这组书（跨书回答）…"
                  className="flex-1 min-w-0 px-2.5 py-1.5 rounded-md border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] outline-none focus:border-[var(--color-seal)] text-xs"
                />
                <button
                  type="button"
                  disabled={asking || !question.trim()}
                  onClick={() => void submitAsk()}
                  className="px-3 py-1.5 rounded-md bg-[var(--color-seal)] text-white hover:brightness-110 disabled:opacity-40 transition text-xs"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {asking ? "追问中…" : "追问"}
                </button>
              </div>
              {answer && (
                <div className="mt-2 whitespace-pre-wrap leading-relaxed text-xs text-[var(--color-ink)]">{answer}</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
