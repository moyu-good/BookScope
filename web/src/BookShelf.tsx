import { useEffect, useState } from "react";
import type { ApiError } from "./ErrorBanner";
import { formatRelativeTime } from "./historyStorage";

// ---------------------------------------------------------------------------
// 书柜：横向 tab strip 形态
//
// 数据来源：GET /api/sessions（永远 200，空 list 也合法）
// 选中态：印章红左竖条 + 加粗书名；非选中态：灰边框
// 删除：行内二次确认（点"删除"变"确认 / 取消"，5 秒未点回退）
//
// 父组件 props 控制：
// - activeSessionId：当前选中的 session
// - onSelect：点 tab 切书
// - onDelete：删除某 session 时通知父组件清场（如果删的是当前书）
// - refreshTrigger：父组件递增即重新拉 list（上传新书 / 删除完成后）
// ---------------------------------------------------------------------------

export interface SessionMetadata {
  session_id: string;
  book_title: string;
  language: string;
  created_at: string;
  last_accessed_at: string;
  /** 题材（#10/#14）：封闭集里的题材词，空串=未分类。左栏 nav 据此按题材显隐。 */
  genre?: string;
}

export interface BookShelfProps {
  activeSessionId: string | null;
  onSelect: (session: SessionMetadata) => void;
  /** 点「读」门：进沉浸阅读器 */
  onRead: (session: SessionMetadata) => void;
  /** 删除完成后通知父组件；若删的是当前书，父组件应清空 active session */
  onDeleted: (deletedSessionId: string) => void;
  /** 父组件递增触发重新拉列表；上传成功后 + 自身删除成功后 */
  refreshTrigger?: number;
  /** 上传成功后想让书柜自动选中的 session_id */
  pendingAutoSelectId?: string | null;
  /** 自动选中后回调清空 pendingAutoSelectId */
  onAutoSelected?: () => void;
}

type LoadState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; sessions: SessionMetadata[] }
  | { kind: "error"; error: ApiError };

const CONFIRM_AUTO_REVERT_MS = 5000;

async function parseError(resp: Response): Promise<ApiError> {
  try {
    const body = await resp.json();
    const detail = body?.detail;
    if (detail && typeof detail === "object" && "error_type" in detail) {
      return detail as ApiError;
    }
    return {
      error_type: `HTTP_${resp.status}`,
      message: typeof detail === "string" ? detail : JSON.stringify(body),
    };
  } catch {
    return { error_type: `HTTP_${resp.status}`, message: resp.statusText };
  }
}

async function fetchSessions(): Promise<SessionMetadata[]> {
  const resp = await fetch("/api/sessions");
  if (!resp.ok) throw await parseError(resp);
  const body = (await resp.json()) as { sessions: SessionMetadata[] };
  return body.sessions ?? [];
}

async function deleteSession(sessionId: string): Promise<void> {
  const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
  // 204 No Content → ok；404 → 数据已不存在，本地同步即可，不当成错误
  if (resp.status === 204 || resp.status === 404) return;
  if (!resp.ok) throw await parseError(resp);
}

export function BookShelf({
  activeSessionId,
  onSelect,
  onRead,
  onDeleted,
  refreshTrigger,
  pendingAutoSelectId,
  onAutoSelected,
}: BookShelfProps) {
  const [state, setState] = useState<LoadState>({ kind: "idle" });
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchSessions()
      .then((sessions) => {
        if (cancelled) return;
        setState({ kind: "ready", sessions });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const apiErr =
          err && typeof err === "object" && "error_type" in err
            ? (err as ApiError)
            : { error_type: "FetchFailed", message: String(err) };
        setState({ kind: "error", error: apiErr });
      });
    return () => {
      cancelled = true;
    };
  }, [refreshTrigger]);

  // 列表刷新后，若有待自动选中的 session_id，触发 onSelect
  useEffect(() => {
    if (state.kind !== "ready" || !pendingAutoSelectId) return;
    const target = state.sessions.find(
      (s) => s.session_id === pendingAutoSelectId,
    );
    if (target) {
      onSelect(target);
      onAutoSelected?.();
    }
  }, [state, pendingAutoSelectId, onSelect, onAutoSelected]);

  // 二次确认 5 秒自动回退
  useEffect(() => {
    if (!confirmingId) return;
    const timer = setTimeout(() => setConfirmingId(null), CONFIRM_AUTO_REVERT_MS);
    return () => clearTimeout(timer);
  }, [confirmingId]);

  async function handleConfirmDelete(sessionId: string) {
    setConfirmingId(null);
    // 乐观先从本地 list 移除
    if (state.kind === "ready") {
      setState({
        kind: "ready",
        sessions: state.sessions.filter((s) => s.session_id !== sessionId),
      });
    }
    try {
      await deleteSession(sessionId);
    } catch (err) {
      const apiErr =
        err && typeof err === "object" && "error_type" in err
          ? (err as ApiError)
          : { error_type: "DeleteFailed", message: String(err) };
      setState({ kind: "error", error: apiErr });
      return;
    }
    onDeleted(sessionId);
  }

  return (
    <section className="border-b border-[var(--color-rule)] pb-5">
      <div className="flex items-baseline gap-3 mb-3 flex-wrap">
        <h2 className="text-xs uppercase tracking-wider text-[var(--color-ink-muted)]">
          书柜
        </h2>
        <span className="text-xs text-[var(--color-ink-muted)]">
          点书脊就开读 · 「分析台」只跑分析不读
        </span>
      </div>
      <ShelfBody
        state={state}
        activeSessionId={activeSessionId}
        confirmingId={confirmingId}
        onSelect={onSelect}
        onRead={onRead}
        onAskDelete={(id) => setConfirmingId(id)}
        onCancelDelete={() => setConfirmingId(null)}
        onConfirmDelete={handleConfirmDelete}
      />
    </section>
  );
}

function ShelfBody(props: {
  state: LoadState;
  activeSessionId: string | null;
  confirmingId: string | null;
  onSelect: (session: SessionMetadata) => void;
  onRead: (session: SessionMetadata) => void;
  onAskDelete: (id: string) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (id: string) => void;
}) {
  const {
    state,
    activeSessionId,
    confirmingId,
    onSelect,
    onRead,
    onAskDelete,
    onCancelDelete,
    onConfirmDelete,
  } = props;

  if (state.kind === "loading" || state.kind === "idle") {
    return (
      <p className="text-sm text-[var(--color-ink-muted)] italic">
        <span className="animate-pulse">●</span> 读取书柜…
      </p>
    );
  }

  if (state.kind === "error") {
    return (
      <p className="text-sm text-[var(--color-ink-muted)]">
        书柜读取失败：{state.error.message}。刷新页面再试一次。
      </p>
    );
  }

  if (state.sessions.length === 0) {
    return (
      <p className="text-sm text-[var(--color-ink-muted)] italic">
        还没上传过书。下面贰区拖一本 epub / txt / pdf 进来即可入库。
      </p>
    );
  }

  // 排序：last_accessed_at 倒序，最近用过的排前面
  const sorted = [...state.sessions].sort((a, b) =>
    b.last_accessed_at.localeCompare(a.last_accessed_at),
  );
  // 同一本书上传过多次 → 只留最近用过的那个 session，书架不堆重复书脊
  const seen = new Set<string>();
  const shelf = sorted.filter((s) => {
    const key = s.book_title.trim();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  return (
    <ul className="flex flex-wrap gap-2">
      {shelf.map((s) => {
        const isActive = s.session_id === activeSessionId;
        const isConfirming = s.session_id === confirmingId;
        return (
          <BookTab
            key={s.session_id}
            session={s}
            isActive={isActive}
            isConfirming={isConfirming}
            onSelect={() => onSelect(s)}
            onRead={() => onRead(s)}
            onAskDelete={() => onAskDelete(s.session_id)}
            onCancelDelete={onCancelDelete}
            onConfirmDelete={() => onConfirmDelete(s.session_id)}
          />
        );
      })}
    </ul>
  );
}

function BookTab(props: {
  session: SessionMetadata;
  isActive: boolean;
  isConfirming: boolean;
  onSelect: () => void;
  onRead: () => void;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}) {
  const {
    session,
    isActive,
    isConfirming,
    onSelect,
    onRead,
    onAskDelete,
    onCancelDelete,
    onConfirmDelete,
  } = props;

  // 视觉：active 走 印章红左竖条 + 加粗 + 高对比；inactive 走 中性灰
  const containerClass = [
    "group relative flex items-stretch rounded border bg-white transition-colors",
    isActive
      ? "border-[var(--color-seal)]/60 shadow-sm"
      : "border-[var(--color-rule)] hover:border-[var(--color-seal)]/40",
  ].join(" ");

  const stripeClass = [
    "w-1 rounded-l",
    isActive ? "bg-[var(--color-seal)]" : "bg-transparent",
  ].join(" ");

  return (
    <li className={containerClass}>
      <span aria-hidden className={stripeClass} />
      <button
        type="button"
        onClick={onRead}
        aria-pressed={isActive}
        title={`读《${session.book_title}》`}
        className="flex flex-col items-start text-left pl-3 pr-2 py-2 min-w-[10rem] max-w-[16rem]"
      >
        <span
          className={[
            "text-sm leading-snug truncate w-full",
            isActive
              ? "text-[var(--color-ink)] font-semibold"
              : "text-[var(--color-ink)]",
          ].join(" ")}
          style={{ fontFamily: "var(--font-display)" }}
          title={session.book_title}
        >
          {session.book_title}
        </span>
        <span className="text-xs text-[var(--color-ink-muted)] mt-0.5">
          {session.language} · {formatRelativeTime(session.last_accessed_at)}
        </span>
      </button>
      <button
        type="button"
        onClick={onSelect}
        className="self-center shrink-0 text-xs px-2.5 py-1 rounded-full border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] mr-1"
        title={`在分析台分析《${session.book_title}》`}
      >
        分析台
      </button>
      <div className="flex items-center pr-2">
        {isConfirming ? (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={onConfirmDelete}
              className="text-xs px-2 py-1 rounded bg-[var(--color-seal)] text-white hover:brightness-110"
              style={{ fontFamily: "var(--font-display)" }}
            >
              确认
            </button>
            <button
              type="button"
              onClick={onCancelDelete}
              className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
            >
              取消
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={onAskDelete}
            aria-label={`删除 ${session.book_title}`}
            className="text-xs px-2 py-1 rounded text-[var(--color-ink-muted)] opacity-0 group-hover:opacity-100 hover:text-[var(--color-seal)] transition-opacity"
          >
            删除
          </button>
        )}
      </div>
    </li>
  );
}
