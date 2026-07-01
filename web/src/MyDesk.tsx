// 我的案头（阅读工作台 Phase B，WP-reading-workspace §Phase B）。
//
// 一个跟 library / 各功能同级的主画布页，不是弹窗。解作者实测那条「个人用户页面在哪」——
// 托管版登录后原先只有左栏底一行账号条，没地方看「我是谁 / 我的书 / 我的笔记」。
//
// 三块：
//   1. 账号信息（只 hosted 已登录才有）：邮箱 / 注册时间 / 邮箱验证态 + 注销账号（二次确认）。
//   2. 我的书：GET /api/sessions 拉书列表，每本带标注数角标。点一本进分析台。
//   3. 我的标注汇总（跨书）：annotationStore.listAllForUser()，按书归堆。点一条进阅读器。
//
// local 模式没有账号信息块，但「我的书 + 我的笔记」照显（设计稿 §8 验收）——一个稳定入口、
// 两形态一致。这条链全程纯前端 + 读接口，不碰 LLM、不传 key（设计稿红线）。
//
// 样式走全站 app-shell 那套 CSS 变量（--color-ink / --color-seal / --color-paper 等），
// 深色自适配，不引第三方 UI。

import { useCallback, useEffect, useMemo, useState } from "react";
import type { SessionMetadata } from "./BookShelf";
import type { AuthUser, DeploymentMode } from "./authClient";
import { annotationStore } from "./annotationStore";
import type { Annotation, AnnotationKind } from "./annotationStore";

const KIND_LABEL: Record<AnnotationKind, string> = {
  bookmark: "书签",
  highlight: "高亮",
  note: "笔记",
  emphasis: "重点",
};

export interface MyDeskProps {
  deploymentMode: DeploymentMode | null;
  authUser: AuthUser | null;
  /** 注销账号：DELETE /api/auth/me，成功后 App 清令牌 + 退回书库。失败抛出来这里显错。 */
  onDeleteAccount: () => Promise<void>;
  /** 点一本书进分析台。 */
  onOpenBook: (session: SessionMetadata) => void;
  /** 点一条标注进阅读器（回到那本书接着读）。 */
  onReadBook: (session: SessionMetadata) => void;
}

export function MyDesk({
  deploymentMode,
  authUser,
  onDeleteAccount,
  onOpenBook,
  onReadBook,
}: MyDeskProps) {
  const hasAccount = deploymentMode === "hosted" && authUser !== null;

  // 书列表：GET /api/sessions（本地 / 托管都用；托管后端已按 owner 隔离，只返自己的）。
  const [sessions, setSessions] = useState<SessionMetadata[]>([]);
  useEffect(() => {
    let alive = true;
    fetch("/api/sessions")
      .then((r) => (r.ok ? r.json() : { sessions: [] }))
      .then((body: { sessions?: SessionMetadata[] }) => {
        if (alive) setSessions(body.sessions ?? []);
      })
      .catch(() => {
        /* 拉不到就空着，页面其余块照显 */
      });
    return () => {
      alive = false;
    };
  }, []);

  // 订阅标注变化：托管异步预热到位 / 增删改后重渲染（同步读接口一字不改）。
  const [, force] = useState(0);
  useEffect(() => annotationStore.subscribe(() => force((n) => n + 1)), []);
  const annotations = annotationStore.listAllForUser();

  // 每本书标注数（角标）。
  const countByBook = useMemo(() => {
    const m = new Map<string, number>();
    for (const a of annotations) {
      m.set(a.book_session_id, (m.get(a.book_session_id) ?? 0) + 1);
    }
    return m;
  }, [annotations]);

  // session_id → session（标注汇总里显书名 + 点击跳书都要它；标注本身只带 session_id）。
  const sessionById = useMemo(() => {
    const m = new Map<string, SessionMetadata>();
    for (const s of sessions) m.set(s.session_id, s);
    return m;
  }, [sessions]);

  // 标注按书归堆，书内按新→旧。
  const byBook = useMemo(() => {
    const groups = new Map<string, typeof annotations>();
    for (const a of annotations) {
      const list = groups.get(a.book_session_id) ?? [];
      list.push(a);
      groups.set(a.book_session_id, list);
    }
    for (const list of groups.values()) {
      list.sort((x, y) => (x.created_at < y.created_at ? 1 : -1));
    }
    return groups;
  }, [annotations]);

  return (
    <section className="reveal">
      <header className="mb-6">
        <h1
          className="text-2xl text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
        >
          我的案头
        </h1>
        <div
          className="mt-2 mb-3 h-px w-10"
          style={{ background: "var(--color-seal)" }}
        />
        <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
          你的书和读书时留下的标注都在这。
          {hasAccount
            ? "标注跟着账号走，换设备登录回来还在。"
            : "本地版标注存在这台机器的浏览器里。"}
        </p>
      </header>

      {hasAccount && authUser && (
        <AccountBlock authUser={authUser} onDeleteAccount={onDeleteAccount} />
      )}

      <MyBooksBlock
        sessions={sessions}
        countByBook={countByBook}
        onOpenBook={onOpenBook}
      />

      <MyAnnotationsBlock
        byBook={byBook}
        sessionById={sessionById}
        onReadBook={onReadBook}
      />
    </section>
  );
}

// ── 账号信息 + 注销（只 hosted 已登录）─────────────────────────────────────

function AccountBlock({
  authUser,
  onDeleteAccount,
}: {
  authUser: AuthUser;
  onDeleteAccount: () => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [err, setErr] = useState("");

  const handleDelete = useCallback(async () => {
    setDeleting(true);
    setErr("");
    try {
      await onDeleteAccount();
      // 成功后 App 会切走这个页面，这里不用复位状态。
    } catch (e) {
      setErr(e instanceof Error ? e.message : "注销没成功，稍后再试。");
      setDeleting(false);
      setConfirming(false);
    }
  }, [onDeleteAccount]);

  return (
    <div
      className="mb-6 rounded-lg border p-5"
      style={{
        borderColor: "var(--color-rule)",
        background: "var(--color-paper-raised)",
      }}
    >
      <SectionTitle>账号</SectionTitle>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
        <dt className="text-[var(--color-ink-muted)]">邮箱</dt>
        <dd className="text-[var(--color-ink)]">{authUser.email}</dd>
        <dt className="text-[var(--color-ink-muted)]">注册时间</dt>
        <dd className="text-[var(--color-ink)]">{fmtDate(authUser.created_at)}</dd>
        <dt className="text-[var(--color-ink-muted)]">邮箱验证</dt>
        <dd className="text-[var(--color-ink)]">
          {authUser.email_verified ? "已验证" : "未验证"}
        </dd>
      </dl>

      <div className="mt-5 pt-4 border-t" style={{ borderColor: "var(--color-rule)" }}>
        {err && (
          <p
            className="mb-2 text-xs px-3 py-2 rounded"
            style={{ background: "var(--color-seal-soft)", color: "var(--color-seal)" }}
          >
            {err}
          </p>
        )}
        {!confirming ? (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="text-xs px-3 py-1.5 rounded border transition-colors"
            style={{ borderColor: "var(--color-rule)", color: "var(--color-ink-muted)" }}
          >
            注销账号
          </button>
        ) : (
          <div className="flex flex-col gap-2">
            <p className="text-xs text-[var(--color-ink)] leading-relaxed">
              注销会把你的书和标注一起删干净，删了找不回。确定吗？
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleting}
                className="text-xs px-3 py-1.5 rounded text-white disabled:opacity-50"
                style={{ background: "var(--color-seal)" }}
              >
                {deleting ? "注销中" : "确定注销，全删掉"}
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={deleting}
                className="text-xs px-3 py-1.5 rounded border disabled:opacity-50"
                style={{ borderColor: "var(--color-rule)", color: "var(--color-ink-muted)" }}
              >
                再想想
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── 我的书（带标注数角标）──────────────────────────────────────────────

function MyBooksBlock({
  sessions,
  countByBook,
  onOpenBook,
}: {
  sessions: SessionMetadata[];
  countByBook: Map<string, number>;
  onOpenBook: (session: SessionMetadata) => void;
}) {
  return (
    <div className="mb-6">
      <SectionTitle>我的书</SectionTitle>
      {sessions.length === 0 ? (
        <p className="mt-3 text-sm text-[var(--color-ink-muted)]">
          书架还是空的，去书库上传一本就能开始读。
        </p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {sessions.map((s) => {
            const n = countByBook.get(s.session_id) ?? 0;
            return (
              <li key={s.session_id}>
                <button
                  type="button"
                  onClick={() => onOpenBook(s)}
                  className="w-full text-left rounded-md border px-4 py-3 flex items-center justify-between gap-3 transition-colors hover:border-[var(--color-seal)]"
                  style={{
                    borderColor: "var(--color-rule)",
                    background: "var(--color-paper)",
                  }}
                >
                  <span
                    className="text-[15px] text-[var(--color-ink)] truncate"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {s.book_title}
                  </span>
                  {n > 0 && (
                    <span
                      className="shrink-0 text-[11px] px-2 py-0.5 rounded-full"
                      style={{
                        background: "var(--color-seal-soft)",
                        color: "var(--color-seal)",
                      }}
                    >
                      {n} 条标注
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── 我的标注汇总（跨书）────────────────────────────────────────────────

function MyAnnotationsBlock({
  byBook,
  sessionById,
  onReadBook,
}: {
  byBook: Map<string, Annotation[]>;
  sessionById: Map<string, SessionMetadata>;
  onReadBook: (session: SessionMetadata) => void;
}) {
  const books = [...byBook.keys()];
  return (
    <div>
      <SectionTitle>我的标注</SectionTitle>
      {books.length === 0 ? (
        <p className="mt-3 text-sm text-[var(--color-ink-muted)]">
          还没有标注。打开一本书，划一句就能加书签 / 高亮 / 笔记 / 重点。
        </p>
      ) : (
        <div className="mt-3 flex flex-col gap-5">
          {books.map((bookId) => {
            const session = sessionById.get(bookId);
            const list = byBook.get(bookId) ?? [];
            return (
              <div key={bookId}>
                <button
                  type="button"
                  disabled={!session}
                  onClick={() => session && onReadBook(session)}
                  className="text-sm text-[var(--color-ink)] hover:text-[var(--color-seal)] disabled:hover:text-[var(--color-ink)] transition-colors"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {session ? session.book_title : "（已删除的书）"}
                  <span className="ml-2 text-[11px] text-[var(--color-ink-muted)]">
                    {list.length} 条
                  </span>
                </button>
                <ul className="mt-2 flex flex-col gap-2">
                  {list.map((a) => (
                    <li
                      key={a.id}
                      className="rounded-md border px-3 py-2"
                      style={{
                        borderColor: "var(--color-rule)",
                        background: "var(--color-paper)",
                      }}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className="text-[10.5px] px-1.5 py-0.5 rounded"
                          style={{
                            background: "var(--color-seal-soft)",
                            color: "var(--color-seal)",
                          }}
                        >
                          {KIND_LABEL[a.kind]}
                        </span>
                      </div>
                      {a.anchor.quote && (
                        <p className="text-[13px] text-[var(--color-ink)] leading-relaxed line-clamp-2">
                          {a.anchor.quote}
                        </p>
                      )}
                      {a.note_text && (
                        <p className="mt-1 text-[12px] text-[var(--color-ink-muted)] leading-relaxed">
                          {a.note_text}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── 小件 ─────────────────────────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="text-[13px] tracking-wider text-[var(--color-ink-muted)] uppercase"
      style={{ fontFamily: "var(--font-display)" }}
    >
      {children}
    </h2>
  );
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}
