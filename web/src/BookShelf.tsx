import { useEffect, useState } from "react";
import type { ApiError } from "./ErrorBanner";
import { formatRelativeTime } from "./historyStorage";
import { annotationStore } from "./annotationStore";

// ---------------------------------------------------------------------------
// 书柜：函套书脊 × 书目索引 的融合形态
//
// 一架函套，列成目录。整体是一份清单（本数多也好扫），但每一行最左压一条
// 按题材染色的"函套书脊条"——一眼看出是一架摆开的函套书，不是干巴巴的列表。
//
// 一行从左到右：题材色书脊条 → 书名（宋体）→ 题材签 + 语言 + 最近访问
//   → 行内「读」（朱砂实底）/「进分析台」（描边）两个动作 → 删除。
// 同名多份合一行，标「× N 份」，指向最近用过的那份 session。
//
// 数据来源：GET /api/sessions（永远 200，空 list 也合法）。
// 选中态：书脊加粗 + 书名加粗 + 整行朱砂淡底 + 左缘朱砂细线。
// 删除：行内二次确认（点"删除"变"确认 / 取消"，5 秒未点回退）。
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

/**
 * 题材 → 书脊色。
 * 取自 session.genre（封闭集：小说/历史/理论/论文/公文/诗歌/工具书/其他），
 * 也兜住 App.tsx 里那套同义写法（novel/fiction/网文/架空/玄幻 ↔ 小说；
 * paper/哲学/学术 ↔ 理论；poem/散文 ↔ 诗歌……）。认不出 / 空 genre 走中性灰。
 *
 * 公文走朱砂（与 accent 同源），小说历史走暖琥珀木调，理论论文工具书走墨青，
 * 诗歌走柔青——一架函套按题材分色，扫一眼就归得了类。
 */
function spineColor(genre: string | undefined): string {
  const g = (genre ?? "").trim().toLowerCase();
  if (!g) return "var(--color-rule)";
  if (/(公文|红头)/.test(g)) return "var(--color-seal)";
  if (/(小说|novel|fiction|网文|历史|架空|玄幻|history)/.test(g)) return "#b4763a";
  if (/(理论|论文|paper|哲学|philosophy|工具书|nonfiction|学术|工具)/.test(g))
    return "#3a6378";
  if (/(诗|poem|poetry|散文|verse)/.test(g)) return "#6f6391";
  return "var(--color-rule)";
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
          一架函套列成目录 · 每本两种用法：「读」沉浸读原文 ·「进分析台」AI 深读那套
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

  // 订阅标注变化:托管缓存异步预热到位 / 增删改后重算每本的笔记角标(本地即时、托管预热后到位)。
  const [, forceTick] = useState(0);
  useEffect(() => annotationStore.subscribe(() => forceTick((n) => n + 1)), []);

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

  // 一份目录：行与行之间用极细 rule 隔开（像书目的栏线），外面一圈函套描边。
  return (
    <ul className="flex flex-col rounded border border-[var(--color-rule)] overflow-hidden divide-y divide-[var(--color-rule)]">
      {shelf.map((entry) => {
        const s = entry.session;
        const isActive = s.session_id === activeSessionId;
        const isConfirming = s.session_id === confirmingId;
        return (
          <BookRow
            key={s.session_id}
            entry={entry}
            noteCount={annotationStore.list(s.session_id).length}
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

function BookRow(props: {
  entry: ShelfEntry;
  /** 这本书的标注数(书签 / 高亮 / 笔记 / 重点合计),>0 才显角标。 */
  noteCount: number;
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
    noteCount,
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
  const spine = spineColor(session.genre);

  // 一行 = 一条函套书脊领头的目录项。
  // active：整行朱砂淡底 + 左缘朱砂细线（与书脊条并列，强调"这本正在用"）。
  const rowClass = [
    "group relative flex items-stretch transition-colors",
    isActive
      ? "bg-[var(--color-seal-soft)]"
      : "bg-[var(--color-paper-raised)] hover:bg-[var(--color-paper-sunken)]",
  ].join(" ");

  return (
    <li className={rowClass}>
      {/* active 左缘朱砂细线——盖在书脊条外侧，一眼定位"在用的这本" */}
      {isActive ? (
        <span
          aria-hidden
          className="absolute left-0 top-0 bottom-0 w-0.5 bg-[var(--color-seal)]"
        />
      ) : null}

      {/* 题材色书脊条：一条立着的小书脊，行的辨识度全靠它 */}
      <span
        aria-hidden
        className="shrink-0 self-stretch my-1.5 ml-2 w-1.5 rounded-full"
        style={{
          backgroundColor: spine,
          // 选中 / hover 时书脊更实、略宽，像被抽出来一点
          opacity: isActive ? 1 : 0.78,
        }}
        title={genre ? `题材：${genre}` : "未分类"}
      />

      {/* 行主体：书名一行 + 找书线索一行，右侧贴行内动作 */}
      <div className="flex flex-1 items-center gap-3 min-w-0 pl-3 pr-3 py-2.5">
        {/* 书名 / 线索区整块可点 = 进分析台(修"点书没反应";「读」「删除」按钮是兄弟节点,不受影响) */}
        <div
          className="flex flex-col gap-0.5 min-w-0 flex-1 cursor-pointer"
          role="button"
          tabIndex={0}
          onClick={onSelect}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onSelect();
            }
          }}
          title={`进分析台分析《${session.book_title}》`}
        >
          {/* 书名（宋体）+ ×N 份 */}
          <div className="flex items-baseline gap-2 min-w-0">
            <span
              className="text-sm leading-snug text-[var(--color-ink)] truncate"
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
                className="shrink-0 text-caption px-1.5 py-0.5 rounded-full border border-[var(--color-rule)] text-[var(--color-ink-muted)] leading-none"
                title={`同名书上传了 ${dupeCount} 份，这行指向最近用过的那份`}
              >
                × {dupeCount} 份
              </span>
            ) : null}
            {noteCount > 0 ? (
              <span
                className="shrink-0 text-caption px-1.5 py-0.5 rounded-full leading-none"
                style={{
                  background: "var(--color-seal-soft)",
                  color: "var(--color-seal)",
                }}
                title={`你在这本书里标了 ${noteCount} 条`}
              >
                {noteCount} 条笔记
              </span>
            ) : null}
          </div>
          {/* 找书线索：题材签（空则不显）+ 语言 + 最近访问 */}
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

        {/* 行内动作：两个门 + 删除。移动端竖排铺满、桌面端横排贴右 */}
        <div className="flex flex-col items-stretch gap-2 shrink-0 sm:flex-row sm:items-center">
          <button
            type="button"
            onClick={onRead}
            aria-pressed={isActive}
            title={`读《${session.book_title}》`}
            className="text-xs px-3 py-1 rounded-full bg-[var(--color-seal)] text-white hover:brightness-110 transition flex-1 sm:flex-none"
            style={{ fontFamily: "var(--font-display)" }}
          >
            读
          </button>
          <button
            type="button"
            onClick={onSelect}
            title={`在分析台分析《${session.book_title}》`}
            className="text-xs px-3 py-1 rounded-full border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] transition-colors flex-1 sm:flex-none"
          >
            进分析台
          </button>

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
              className="text-xs px-2 py-1 rounded text-[var(--color-ink-muted)] opacity-100 md:opacity-0 md:group-hover:opacity-100 md:focus:opacity-100 hover:text-[var(--color-seal)] transition-opacity"
            >
              删除
            </button>
          )}
        </div>
      </div>
    </li>
  );
}
