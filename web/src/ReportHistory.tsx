// ---------------------------------------------------------------------------
// ReportHistory —— 报告历史（localStorage 记录已生成的报告，可重新打开）
//
// 报告是交付物，生成后应可重开（重新生成成本低：章脉缓存秒出）。
// 记录：单书报告（sessionId）/ 对照报告（sessionIds）/ 标题 / 时间。
// ---------------------------------------------------------------------------

export interface ReportHistoryEntry {
  id: string;
  title: string;
  type: "book" | "cross" | "cluster";
  sessionId?: string;
  sessionIds?: string[];
  /** 簇关系网报告保存的来源组名，重开时原样回传后端 */
  clusterName?: string;
  fileName: string;
  createdAt: string;
}

const HISTORY_KEY = "bookscope_report_history";
const MAX_HISTORY = 50;

export function loadReportHistory(): ReportHistoryEntry[] {
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw) as ReportHistoryEntry[];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export function saveReportHistory(entry: ReportHistoryEntry): void {
  try {
    const cur = loadReportHistory();
    const next = [entry, ...cur.filter((x) => x.id !== entry.id)].slice(0, MAX_HISTORY);
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  } catch {
    /* localStorage 不可用时静默 */
  }
}

export function deleteReportHistoryEntry(id: string): void {
  try {
    const cur = loadReportHistory().filter((x) => x.id !== id);
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(cur));
  } catch {
    /* localStorage 不可用时静默 */
  }
}

export function ReportHistoryModal({
  history,
  onReopen,
  onDelete,
  onClose,
}: {
  history: ReportHistoryEntry[];
  onReopen: (entry: ReportHistoryEntry) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-[210] flex items-center justify-center bg-black/30 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="报告历史"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg max-h-[70vh] flex flex-col rounded-lg border border-[var(--color-rule)] shadow-xl"
        style={{ background: "var(--color-paper-raised)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--color-rule)]">
          <span className="text-sm font-bold text-[var(--color-seal)]" style={{ fontFamily: "var(--font-display)" }}>
            📚 报告历史
          </span>
          <span className="text-xs text-[var(--color-ink-muted)]">最近 {history.length} 份</span>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto text-xs px-2 py-1 rounded border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
          >
            关闭
          </button>
        </div>
        <div className="flex-1 overflow-y-auto divide-y divide-[var(--color-rule)]">
          {history.length === 0 ? (
            <p className="px-4 py-6 text-sm text-[var(--color-ink-muted)] text-center">
              还没有生成过报告。书柜里点「出报告」或「对照」就会记在这里。
            </p>
          ) : (
            history.map((h) => (
              <div key={h.id} className="px-4 py-2.5 flex items-center gap-3">
                <span className="text-xs px-1.5 py-0.5 rounded border border-[var(--color-rule)] text-[var(--color-ink-muted)] shrink-0">
                  {h.type === "cluster" ? "簇网" : h.type === "cross" ? "对照" : "书鉴"}
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
                  重新打开
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(h.id)}
                  title="删除这条历史"
                  className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] shrink-0"
                >
                  删除
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
