import { useEffect, useState } from "react";
import {
  deleteEntry,
  formatRelativeTime,
  getEntries,
} from "./historyStorage";
import type { QAEntry } from "./historyStorage";

// ---------------------------------------------------------------------------
// 每本书独立的历史面板
//
// 数据来源：localStorage（historyStorage.ts）
// 触发刷新：bookSessionId 变化、refreshTrigger 变化、删除某条
// ---------------------------------------------------------------------------

export interface HistoryPanelProps {
  bookSessionId: string | null;
  onSelect: (entry: QAEntry) => void;
  /** 父组件写入新记录后，递增此值即可让面板重新读 localStorage */
  refreshTrigger?: number;
}

const QUESTION_PREVIEW_LIMIT = 60;

export function HistoryPanel({
  bookSessionId,
  onSelect,
  refreshTrigger,
}: HistoryPanelProps) {
  const [entries, setEntries] = useState<QAEntry[]>([]);

  useEffect(() => {
    if (!bookSessionId) {
      setEntries([]);
      return;
    }
    setEntries(getEntries(bookSessionId));
  }, [bookSessionId, refreshTrigger]);

  if (!bookSessionId) return null;

  function handleDelete(entryId: string) {
    if (!bookSessionId) return;
    deleteEntry(bookSessionId, entryId);
    setEntries(getEntries(bookSessionId));
  }

  // 倒序：新的在上
  const sorted = [...entries].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  );

  return (
    <div className="mt-8 border-t border-[var(--color-rule)] pt-6">
      <h3 className="text-sm uppercase tracking-wider text-[var(--color-ink-muted)] mb-3">
        本书历史 · {sorted.length} 条
      </h3>
      {sorted.length === 0 ? (
        <p className="text-sm text-[var(--color-ink-muted)] italic">
          还没问过这本书
        </p>
      ) : (
        <ol className="space-y-2">
          {sorted.map((entry) => (
            <HistoryItem
              key={entry.id}
              entry={entry}
              onSelect={() => onSelect(entry)}
              onDelete={() => handleDelete(entry.id)}
            />
          ))}
        </ol>
      )}
    </div>
  );
}

function HistoryItem({
  entry,
  onSelect,
  onDelete,
}: {
  entry: QAEntry;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const preview = previewQuestion(entry.question);
  const timeText = formatRelativeTime(entry.created_at);

  return (
    <li className="flex items-start gap-2 border-l-2 border-[var(--color-rule)] hover:border-[var(--color-seal)]/50 pl-3 py-1.5 transition-colors">
      <div className="flex-1 min-w-0">
        <p
          className="text-sm leading-snug text-[var(--color-ink)] truncate"
          style={{ fontFamily: "var(--font-body)" }}
          title={entry.question}
        >
          {preview}
        </p>
        <p className="text-xs text-[var(--color-ink-muted)] mt-0.5">
          {timeText}
          {entry.citations.length > 0 && (
            <> · {entry.citations.length} 条原文</>
          )}
        </p>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <button
          type="button"
          onClick={onSelect}
          className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)]/50 text-[var(--color-ink)] transition-colors"
          style={{ fontFamily: "var(--font-display)" }}
        >
          查看
        </button>
        <button
          type="button"
          onClick={onDelete}
          aria-label="删除这条历史"
          className="text-xs px-2 py-1 rounded text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
        >
          删除
        </button>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// 工具：题面截断
// ---------------------------------------------------------------------------

function previewQuestion(text: string): string {
  const trimmed = text.trim();
  if (trimmed.length <= QUESTION_PREVIEW_LIMIT) return trimmed;
  return `${trimmed.slice(0, QUESTION_PREVIEW_LIMIT)}…`;
}
