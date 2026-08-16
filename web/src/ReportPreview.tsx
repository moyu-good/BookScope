// ---------------------------------------------------------------------------
// ReportPreview —— 书鉴/对照报告预览（产品内交付物，不只是下载文件）
//
// 报告是主轴交付物：点「出报告」不再只下载，而是先在应用内 iframe 预览，
// 可随时下载 / 关闭 / 追问。解决"HTML 文件打不开/看不到"的断点，也让
// 静态报告获得"可追问"能力（答案由 App 调后端生成，展示在预览下方）。
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react";

export interface ReportPreviewState {
  url: string;
  title: string;
  fileName: string;
  /** 单书报告带 session_id，用于报告内追问 */
  sessionId?: string;
  /** 对照报告带多本书 session_id，用于跨文本追问 */
  sessionIds?: string[];
  /** 报告覆盖状态：structure=结构版 / partial:N/M=部分 / full=完整 */
  coverage?: string;
}

export function ReportPreview({
  preview,
  onAsk,
  onRegenerate,
  progressProvider,
  progressModel,
  onClose,
}: {
  preview: ReportPreviewState;
  /** 追问回调：问题 → 答案文本（由 App 调 /agent/ask）；不传则隐藏追问框 */
  onAsk?: (question: string, chapter?: number) => Promise<string>;
  /** 重新生成（结构版/部分版时可用，拉取更全版本） */
  onRegenerate?: () => Promise<void>;
  /** 进度查询用的 provider/model（与报告请求同款，避免默认模型对不上） */
  progressProvider?: string;
  progressModel?: string;
  onClose: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [chapter, setChapter] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [regenerating, setRegenerating] = useState(false);
  const [buildProgress, setBuildProgress] = useState<{ built: number; total: number } | null>(null);
  const [buildReady, setBuildReady] = useState(false);

  // 结构版/部分版：后台章脉预建中，轮询 spine-progress 显示实时进度
  useEffect(() => {
    const sessionId = preview.sessionId;
    const isBuilding = preview.coverage === "structure" || preview.coverage?.startsWith("partial:");
    if (!sessionId || !isBuilding) return;
    setBuildProgress(null);
    setBuildReady(false);
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const fetchOnce = async () => {
      try {
        const params = new URLSearchParams({ ids: sessionId });
        if (progressModel) params.set("model", progressModel);
        if (progressProvider) params.set("provider", progressProvider);
        const resp = await fetch(`/api/agent/spine-progress?${params.toString()}`);
        if (!resp.ok || cancelled) return;
        const data = (await resp.json()) as { books?: { session_id: string; built: number; total: number; ready: boolean }[] };
        const b = data.books?.find((x) => x.session_id === sessionId);
        if (!b || cancelled) return;
        setBuildProgress({ built: b.built, total: b.total });
        if (b.ready) {
          setBuildReady(true);
          if (timer) {
            clearInterval(timer);
            timer = null;
          }
        }
      } catch {
        /* 轮询失败下一轮再试 */
      }
    };
    void fetchOnce();
    timer = setInterval(() => void fetchOnce(), 5000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [preview.sessionId, preview.coverage, progressProvider, progressModel]);

  const download = () => {
    const a = document.createElement("a");
    a.href = preview.url;
    a.download = preview.fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const openInNewTab = () => {
    window.open(preview.url, "_blank", "noopener");
  };

  const printReport = () => {
    const w = window.open(preview.url, "_blank");
    if (w) {
      // 等待加载后调打印（可存 PDF）
      w.addEventListener("load", () => {
        try {
          w.print();
        } catch {
          /* 跨域/拦截时忽略 */
        }
      });
    }
  };

  const submitAsk = async () => {
    const q = question.trim();
    if (!q || !onAsk || asking) return;
    const ch = chapter.trim() ? Number(chapter.trim()) : undefined;
    if (chapter.trim() && (!Number.isInteger(ch) || (ch ?? 0) < 1)) {
      setError("章号要是正整数");
      return;
    }
    setAsking(true);
    setError("");
    try {
      const ans = await onAsk(q, ch);
      setAnswer(ans);
    } catch (e) {
      setError(e instanceof Error ? e.message : "追问失败");
    } finally {
      setAsking(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[200] flex flex-col bg-[var(--color-paper)] reveal"
      role="dialog"
      aria-modal="true"
      aria-label={`报告预览：${preview.title}`}
    >
      {/* 顶栏：标题 + 下载 + 关闭 */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 border-b border-[var(--color-rule)]"
        style={{ background: "linear-gradient(135deg, var(--color-seal-soft), transparent 60%), var(--color-paper-raised)", boxShadow: "var(--shadow-soft)" }}
      >
        <span className="text-sm font-bold text-[var(--color-seal)] truncate" style={{ fontFamily: "var(--font-display)" }}>
          📜 {preview.title}
        </span>
        <span className="text-xs text-[var(--color-ink-muted)] hidden sm:inline">
          书鉴报告 · 可下载后分享 / 存档
        </span>
        {preview.coverage === "structure" && (
          <span className="text-[10px] px-2 py-0.5 rounded-full border border-[var(--color-gold,#9C7A2E)] text-[var(--color-gold,#9C7A2E)]">
            结构版 · 深度分析后台构建中
          </span>
        )}
        {preview.coverage && preview.coverage.startsWith("partial:") && (
          <span className="text-[10px] px-2 py-0.5 rounded-full border border-[var(--color-gold,#9C7A2E)] text-[var(--color-gold,#9C7A2E)]">
            已覆盖 {preview.coverage.slice("partial:".length)} 章 · 后台补建中
          </span>
        )}
        {buildProgress && buildProgress.total > 0 && !buildReady && (
          <span className="text-[10px] px-2 py-0.5 rounded-full border border-[var(--color-gold,#9C7A2E)] text-[var(--color-gold,#9C7A2E)]">
            深度构建中 {buildProgress.built}/{buildProgress.total}
          </span>
        )}
        {buildReady && preview.coverage && preview.coverage !== "full" && (
          <span className="text-[10px] px-2 py-0.5 rounded-full border border-[var(--color-seal)] text-[var(--color-seal)]">
            深度构建完成 · 可重新生成完整版
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {onAsk && (
            <div className="flex items-center gap-1.5 mr-2">
              <input
                type="number"
                min={1}
                value={chapter}
                onChange={(e) => setChapter(e.target.value)}
                placeholder="章"
                title="可选：只精读这一章回答"
                className="w-14 text-xs px-2 py-1.5 rounded-md border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] outline-none focus:border-[var(--color-seal)]"
              />
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void submitAsk();
                }}
                placeholder="追问这份报告…"
                className="w-52 text-xs px-2.5 py-1.5 rounded-md border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] outline-none focus:border-[var(--color-seal)]"
              />
              <button
                type="button"
                onClick={() => void submitAsk()}
                disabled={asking || !question.trim()}
                className="text-xs px-3 py-1.5 rounded-md bg-[var(--color-seal)] text-white hover:brightness-110 disabled:opacity-40 transition"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {asking ? "追问中…" : "追问"}
              </button>
            </div>
          )}
          {onRegenerate && preview.coverage && preview.coverage !== "full" && (
            <button
              type="button"
              onClick={() => {
                setRegenerating(true);
                void onRegenerate().finally(() => setRegenerating(false));
              }}
              disabled={regenerating}
              className="text-xs px-3 py-1.5 rounded-md border border-[var(--color-gold,#9C7A2E)] text-[var(--color-gold,#9C7A2E)] hover:brightness-110 disabled:opacity-40 transition"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {regenerating ? "更新中…" : "重新生成更全版"}
            </button>
          )}
          <button
            type="button"
            onClick={openInNewTab}
            title="在新标签打开"
            className="text-xs px-3 py-1.5 rounded-md border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition"
          >
            新窗口
          </button>
          <button
            type="button"
            onClick={printReport}
            title="打印 / 存 PDF"
            className="text-xs px-3 py-1.5 rounded-md border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition"
          >
            打印 / PDF
          </button>
          <button
            type="button"
            onClick={download}
            className="text-xs px-3 py-1.5 rounded-md bg-[var(--color-seal)] text-white hover:brightness-110 transition"
            style={{ fontFamily: "var(--font-display)" }}
          >
            下载 HTML
          </button>
          <button
            type="button"
            onClick={onClose}
            className="text-xs px-3 py-1.5 rounded-md border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] transition"
          >
            关闭
          </button>
        </div>
      </div>
      {/* 追问答案区（有答案才显示） */}
      {(answer || error) && (
        <div
          className="px-4 py-2 border-b border-[var(--color-rule)] text-xs leading-relaxed"
          style={{
            background: error ? "color-mix(in oklch, var(--color-seal) 8%, transparent)" : "var(--color-seal-soft)",
          }}
        >
          {error ? (
            <span className="text-[var(--color-seal)]">⚠️ {error}</span>
          ) : (
            <>
              <span className="font-bold text-[var(--color-seal)]">❓ {question}</span>
              <div className="mt-1 text-[var(--color-ink)] whitespace-pre-wrap">{answer}</div>
            </>
          )}
        </div>
      )}
      {/* 报告本体：iframe 全屏预览 */}
      <iframe
        src={preview.url}
        title={preview.title}
        className="flex-1 w-full border-0"
        style={{ background: "white" }}
      />
    </div>
  );
}
