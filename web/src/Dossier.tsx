// ---------------------------------------------------------------------------
// Dossier — 卷宗（1.6 红头文件垂直·跨文件视图的入口）
//
// 单份公文的功能（公文结构 / 办事清单 …）认「案上当前书」一份；跨文件功能（依据链网 /
// 政策演变 / 上下级一致性）要的是**一组**公文。这块就管这件事：从书库已上传的文档里多选
// 一组，组成一份「卷宗」，三个跨文件视图都跑这一组。
//
// 状态不在这里存——选中的 session_id 集合由 App 顶层持有并落 localStorage（跟 LLM 配置
// 一个套路：刷新不丢、跨视图共享）。这里只负责「列书库 + 勾选 + 把选中集合报给 App」。
//
// 意象 = 案卷归档（把相关文牍归进一只函套）：每份公文一行「卷内文书」条，左侧勾选、点亮的
// 行朱砂左竖条（同书柜选中态）；顶上一行说清「这卷宗收了几份」。克制——不堆装饰，看得清、
// 勾得动（可用性优先）。
//
// 注意：卷宗里的「文档」复用现有 book session（一份上传的公文 = 一个 session）。不新建
// 后端概念，卷宗纯是前端把几个 session_id 攒一组。
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react";
import type { ApiError } from "./ErrorBanner";
import type { SessionMetadata } from "./BookShelf";
import { formatRelativeTime } from "./historyStorage";

interface DossierProps {
  /** 当前卷宗里选中的 session_id 集合（App 顶层持有） */
  selectedIds: string[];
  /** 勾 / 取消某份；App 负责更新集合 + 落 localStorage */
  onToggle: (sessionId: string) => void;
  /** 全清空 */
  onClear: () => void;
  /** 上传 / 删除后让书库重新拉 list */
  refreshTrigger?: number;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; sessions: SessionMetadata[] }
  | { kind: "error"; error: ApiError };

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

export function Dossier({
  selectedIds,
  onToggle,
  onClear,
  refreshTrigger,
}: DossierProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const selected = new Set(selectedIds);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetch("/api/sessions")
      .then(async (resp) => {
        if (!resp.ok) throw await parseError(resp);
        const body = (await resp.json()) as { sessions: SessionMetadata[] };
        if (cancelled) return;
        setState({ kind: "ready", sessions: body.sessions ?? [] });
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

  if (state.kind === "loading") {
    return (
      <p className="text-sm text-[var(--color-ink-muted)] italic pt-2">
        <span className="animate-pulse">●</span> 读取书库…
      </p>
    );
  }

  if (state.kind === "error") {
    return (
      <p className="text-sm text-[var(--color-ink-muted)] pt-2">
        书库读取失败：{state.error.message}。刷新页面再试。
      </p>
    );
  }

  if (state.sessions.length === 0) {
    return (
      <p className="text-sm text-[var(--color-ink-muted)] italic pt-2">
        书库里还没有文档。先在「书库」上传几份公文（epub / txt / pdf），再回这里把相关的几份归进一份卷宗。
      </p>
    );
  }

  // 排序：最近用过的在前（跟书柜一致）
  const sorted = [...state.sessions].sort((a, b) =>
    b.last_accessed_at.localeCompare(a.last_accessed_at),
  );
  const count = selectedIds.length;

  return (
    <div className="pt-1">
      {/* 卷宗题署：收了几份 + 清空 */}
      <div className="mb-3 flex items-center gap-2.5 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          本卷宗 · {count} 份公文
        </span>
        {count < 2 ? (
          <span className="text-xs text-[var(--color-ink-muted)]">
            跨文件视图至少要选 2 份——勾上相关的几份（如一份上位规定 + 几份配套实施件）。
          </span>
        ) : (
          <span className="text-xs text-[var(--color-ink-muted)]">
            选好了——去左栏「依据链网」「政策演变」「上下级一致性」跑这一组。
          </span>
        )}
        {count > 0 && (
          <button
            type="button"
            onClick={onClear}
            className="ml-auto text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
          >
            清空卷宗
          </button>
        )}
      </div>

      {/* 卷内文书：每份一行，勾选归卷 */}
      <ul className="space-y-1.5">
        {sorted.map((s) => {
          const on = selected.has(s.session_id);
          return (
            <li key={s.session_id}>
              <label
                className="group relative flex items-center gap-3 rounded border bg-white px-3 py-2.5 cursor-pointer transition-colors"
                style={
                  on
                    ? { borderColor: "color-mix(in oklch, var(--color-seal) 55%, transparent)" }
                    : { borderColor: "var(--color-rule)" }
                }
              >
                {/* 选中态朱砂左竖条（同书柜） */}
                <span
                  aria-hidden
                  className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r"
                  style={{ background: on ? "var(--color-seal)" : "transparent" }}
                />
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => onToggle(s.session_id)}
                  className="w-4 h-4 accent-[var(--color-seal)] cursor-pointer shrink-0 ml-1"
                />
                <div className="min-w-0 flex-1">
                  <div
                    className="text-sm leading-snug truncate text-[var(--color-ink)]"
                    style={{
                      fontFamily: "var(--font-display)",
                      fontWeight: on ? 600 : 400,
                    }}
                    title={s.book_title}
                  >
                    {s.book_title}
                  </div>
                  <div className="text-[11px] text-[var(--color-ink-muted)] mt-0.5">
                    {s.language} · {formatRelativeTime(s.last_accessed_at)}
                  </div>
                </div>
              </label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
