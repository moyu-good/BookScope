import { useEffect, useState } from "react";
import type { ApiError } from "./ErrorBanner";
import { formatRelativeTime } from "./historyStorage";

// ---------------------------------------------------------------------------
// 书柜：函套卡片网格形态
//
// 数据来源：GET /api/sessions（永远 200，空 list 也合法）
// 一本书一张卡。读 / 进分析台是卡脚两个明确的按钮，不再靠"点书脊"猜动作。
// 选中态：印章红左竖条 + 加粗书名 + 朱砂淡底。
// 删除：卡脚行内二次确认（点"删除"变"确认 / 取消"，5 秒未点回退）。
//
// 同一本书上传过多次 → 合并成一张卡，指向最近用过的那份 session，
// 卡上标「× N 份」，不在书架堆重复书脊。
//
// 父组件 props 控制：
// - activeSessionId：当前选中的 session
// - onSelect：进分析台
// - onRead：进沉浸阅读器
// - onDeleted：删除某 session 时通知父组件清场（如果删的是当前书）
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

/** 一张卡 = 一本书。dupeCount 是同名书的上传份数（≥2 才显示）。 */
interface ShelfEntry {
  session: SessionMetadata;
  dupeCount: number;
}

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

/**
 * 排序 + 同名合并。
 * 先按 last_accessed_at 倒序（最近用过的排前面），再把同 book_title 的多份
 * 收成一张卡——卡指向最近那份 session，dupeCount 记总份数。
 */
function buildShelf(sessions: SessionMetadata[]): ShelfEntry[] {
  const sorted = [...sessions].sort((a, b) =>
    b.last_accessed_at.localeCompare(a.last_accessed_at),
  );
  const byTitle = new Map<string, ShelfEntry>();
  for (const s of sorted) {
    const key = s.book_title.trim();
    const existing = byTitle.get(key);
    if (existing) {
      existing.dupeCount += 1;
    } else {
      byTitle.set(key, { session: s, dupeCount: 1 });
    }
  }
  return [...byTitle.values()];
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
          每本两个门：「读」进阅读器 · 「进分析台」只跑分析
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

  const shelf = buildShelf(state.sessions);

  return (
    <ul className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(15rem,1fr))]">
      {shelf.map((entry) => {
        const s = entry.session;
        const isActive = s.session_id === activeSessionId;
        const isConfirming = s.session_id === confirmingId;
        return (
          <BookCard
            key={s.session_id}
            entry={entry}
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

function BookCard(props: {
  entry: ShelfEntry;
  isActive: boolean;
  isConfirming: boolean;
  onSelect: () => void;
  onRead: () => void;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}) {
  const {
    entry,
    isActive,
    isConfirming,
    onSelect,
    onRead,
    onAskDelete,
    onCancelDelete,
    onConfirmDelete,
  } = props;
  const { session, dupeCount } = entry;
  const genre = session.genre?.trim();

  // 视觉：active 走 印章红左竖条 + 朱砂淡底 + 高对比；inactive 走 中性纸面
  const cardClass = [
    "group relative flex items-stretch rounded border bg-[var(--color-paper-raised)] transition-colors",
    isActive
      ? "border-[var(--color-seal)]/60 bg-[var(--color-seal-soft)] shadow-sm"
      : "border-[var(--color-rule)] hover:border-[var(--color-seal)]/40",
  ].join(" ");

  const stripeClass = [
    "w-1 shrink-0 rounded-l",
    isActive ? "bg-[var(--color-seal)]" : "bg-transparent",
  ].join(" ");

  return (
    <li className={cardClass}>
      <span aria-hidden className={stripeClass} />
      <div className="flex flex-col flex-1 min-w-0 pl-3 pr-3 py-2.5 gap-2">
        {/* 书名 + 题材标 */}
        <div className="flex flex-col gap-1 min-w-0">
          <div className="flex items-start gap-2 min-w-0">
            <span
              className="text-sm leading-snug text-[var(--color-ink)] flex-1 min-w-0 truncate"
              style={{
                fontFamily: "var(--font-display)",
                fontWeight: isActive ? 600 : 400,
              }}
              title={session.book_title}
            >
              {session.book_title}
            </span>
            {dupeCount > 1 ? (
              <span
                className="shrink-0 text-[0.65rem] px-1.5 py-0.5 rounded-full border border-[var(--color-rule)] text-[var(--color-ink-muted)] leading-none mt-0.5"
                title={`同名书上传了 ${dupeCount} 份，这张卡指向最近用过的那份`}
              >
                × {dupeCount} 份
              </span>
            ) : null}
          </div>
          {/* 找书线索：题材标（空则不显）+ 语言 + 最近访问 */}
          <div className="flex items-center gap-1.5 flex-wrap text-xs text-[var(--color-ink-muted)]">
            {genre ? (
              <span className="px-1.5 py-0.5 rounded-full bg-[var(--color-paper-sunken)] border border-[var(--color-rule)] leading-none text-[var(--color-ink)]">
                {genre}
              </span>
            ) : null}
            <span>{session.language}</span>
            <span aria-hidden>·</span>
            <span title={`最近访问：${session.last_accessed_at}`}>
              {formatRelativeTime(session.last_accessed_at)}
            </span>
          </div>
        </div>

        {/* 卡脚：两个明确的门 + 删除 */}
        <div className="flex items-center gap-2 mt-0.5">
          <button
            type="button"
            onClick={onRead}
            aria-pressed={isActive}
            title={`读《${session.book_title}》`}
            className="text-xs px-3 py-1 rounded-full bg-[var(--color-seal)] text-white hover:brightness-110 transition"
            style={{ fontFamily: "var(--font-display)" }}
          >
            读
          </button>
          <button
            type="button"
            onClick={onSelect}
            title={`在分析台分析《${session.book_title}》`}
            className="text-xs px-3 py-1 rounded-full border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] transition-colors"
          >
            进分析台
          </button>

          <div className="ml-auto flex items-center">
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
                  className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
                >
                  取消
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={onAskDelete}
                aria-label={`删除 ${session.book_title}`}
                className="text-xs px-2 py-1 rounded text-[var(--color-ink-muted)] opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-[var(--color-seal)] transition-opacity"
              >
                删除
              </button>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}
