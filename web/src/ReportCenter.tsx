// ---------------------------------------------------------------------------
// ReportCenter —— 报告中心（聚合视图）
//
// 一个全屏面板看全局：统计 + 每本书状态/最近报告/快捷操作 + 报告历史。
// 数据自己拉（/api/sessions + spine-progress + localStorage history），
// 不依赖书柜内部状态。报告是主轴交付物，这里就是交付物的"家"。
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react";
import { loadReportHistory, type ReportHistoryEntry } from "./ReportHistory";
import type { SessionMetadata } from "./BookShelf";

interface SpineState {
  built: number;
  total: number;
  ready: boolean;
}

export function ReportCenter({
  onOpenReport,
  onReopen,
  onCompareMany,
  onClose,
}: {
  onOpenReport: (session: SessionMetadata) => void;
  onReopen: (entry: ReportHistoryEntry) => void;
  onCompareMany: (sessions: SessionMetadata[]) => void;
  onClose: () => void;
}) {
  const [sessions, setSessions] = useState<SessionMetadata[] | null>(null);
  const [progress, setProgress] = useState<Record<string, SpineState>>({});
  const [history] = useState<ReportHistoryEntry[]>(() => loadReportHistory());
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/sessions");
        if (!resp.ok) throw new Error(`sessions ${resp.status}`);
        const body = (await resp.json()) as { sessions: SessionMetadata[] };
        if (cancelled) return;
        const list = body.sessions ?? [];
        setSessions(list);
        if (list.length > 0) {
          const ids = list.map((x) => x.session_id).join(",");
          const pr = await fetch(`/api/agent/spine-progress?ids=${encodeURIComponent(ids)}&model=deepseek-v4-flash`);
          if (pr.ok) {
            const data = (await pr.json()) as { books?: { session_id: string; built: number; total: number; ready: boolean }[] };
            if (!cancelled && data.books) {
              const map: Record<string, SpineState> = {};
              for (const b of data.books) map[b.session_id] = { built: b.built, total: b.total, ready: b.ready };
              setProgress(map);
            }
          }
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "加载失败");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const readyCount = sessions?.filter((s) => progress[s.session_id]?.ready).length ?? 0;
  const recentBySession = new Map<string, ReportHistoryEntry>();
  for (const h of history) {
    if (h.type === "book" && h.sessionId && !recentBySession.has(h.sessionId)) {
      recentBySession.set(h.sessionId, h);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[210] flex flex-col bg-[var(--color-paper)]"
      role="dialog"
      aria-modal="true"
      aria-label="报告中心"
    >
      {/* 顶栏 */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 border-b border-[var(--color-rule)]"
        style={{ background: "var(--color-paper-raised)" }}
      >
        <span className="text-sm font-bold text-[var(--color-seal)]" style={{ fontFamily: "var(--font-display)" }}>
          📚 报告中心
        </span>
        <span className="text-xs text-[var(--color-ink-muted)]">
          {sessions ? `${sessions.length} 本 · ${readyCount} 本就绪 · ${history.length} 份报告` : "加载中…"}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto text-xs px-3 py-1.5 rounded-md border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] transition"
        >
          关闭
        </button>
      </div>

      {error && (
        <div className="px-4 py-2 text-xs text-[var(--color-seal)]">⚠️ {error}</div>
      )}

      <div className="flex-1 overflow-y-auto p-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 左：每本书状态卡 */}
        <div>
          <h3 className="text-xs font-bold text-[var(--color-ink-muted)] mb-2" style={{ fontFamily: "var(--font-display)" }}>
            书
          </h3>
          {!sessions ? (
            <p className="text-sm text-[var(--color-ink-muted)] italic">读取书柜…</p>
          ) : sessions.length === 0 ? (
            <p className="text-sm text-[var(--color-ink-muted)] italic">还没有书。</p>
          ) : (
            <>
            {(() => {
              const groups = new Map<string, SessionMetadata[]>();
              for (const s of sessions) {
                const src = s.source_folder?.trim() || "手动上传";
                if (!groups.has(src)) groups.set(src, []);
                groups.get(src)!.push(s);
              }
              return [...groups.entries()].map(([src, list]) => (
                <div key={src} className="mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold text-[var(--color-ink-muted)]">{src}</span>
                    <span className="text-[10px] text-[var(--color-ink-muted)] opacity-70">{list.length} 本</span>
                    {list.length >= 2 && (
                      <button
                        type="button"
                        onClick={() => onCompareMany(list)}
                        className="ml-auto text-[10px] px-2 py-0.5 rounded-full border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                      >
                        整组对照
                      </button>
                    )}
                  </div>
                </div>
              ));
            })()}
            <div className="flex flex-col gap-2">
              {sessions.map((s) => {
                const p = progress[s.session_id];
                const recent = recentBySession.get(s.session_id);
                return (
                  <div
                    key={s.session_id}
                    className="rounded-md border border-[var(--color-rule)] p-3 flex items-center gap-3"
                    style={{ background: "var(--color-paper-raised)" }}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-bold text-[var(--color-ink)] truncate">{s.book_title}</div>
                      <div className="text-[10px] text-[var(--color-ink-muted)]">
                        {s.source_folder ? `来源：${s.source_folder}` : "手动上传"}
                        {p && p.total > 0
                          ? p.ready
                            ? " · 章脉就绪"
                            : ` · 章脉 ${p.built}/${p.total}`
                          : " · 章脉待建"}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => onOpenReport(s)}
                      className="text-xs px-2.5 py-1 rounded bg-[var(--color-seal)] text-white hover:brightness-110 shrink-0"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      出报告
                    </button>
                    {recent && (
                      <button
                        type="button"
                        onClick={() => onReopen(recent)}
                        title={`重开最近报告`}
                        className="text-xs px-2.5 py-1 rounded border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] shrink-0"
                      >
                        最近报告
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
            </>
          )}
        </div>

        {/* 右：报告历史 */}
        <div>
          <h3 className="text-xs font-bold text-[var(--color-ink-muted)] mb-2" style={{ fontFamily: "var(--font-display)" }}>
            报告历史
          </h3>
          {history.length === 0 ? (
            <p className="text-sm text-[var(--color-ink-muted)] italic">还没有生成过报告。</p>
          ) : (
            <div className="flex flex-col gap-2">
              {history.map((h) => (
                <div
                  key={h.id}
                  className="rounded-md border border-[var(--color-rule)] px-3 py-2 flex items-center gap-3"
                  style={{ background: "var(--color-paper-raised)" }}
                >
                  <span className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--color-rule)] text-[var(--color-ink-muted)] shrink-0">
                    {h.type === "cross" ? "对照" : "书鉴"}
                  </span>
                  <span className="text-sm text-[var(--color-ink)] truncate flex-1">{h.title}</span>
                  <span className="text-[10px] text-[var(--color-ink-muted)] shrink-0">
                    {new Date(h.createdAt).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                  </span>
                  <button
                    type="button"
                    onClick={() => onReopen(h)}
                    className="text-xs px-2.5 py-1 rounded bg-[var(--color-seal)] text-white hover:brightness-110 shrink-0"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    重开
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
