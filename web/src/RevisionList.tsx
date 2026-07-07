// ---------------------------------------------------------------------------
// RevisionList — 改稿清单（WP-revision-loop）
//
// 把已跑过的诊断（设定一致性 / 伏笔 / 节奏 / 文体）的发现，归一成一份带三态
// （待改 / 已改 / 不改）的修改清单。每条挂原文证据，可点跳出处，可一键导出 markdown。
//
// 聚合来源：「一键汇总全书诊断」按钮去拉已建的诊断端点（consistency-scan /
// foreshadow-arcs / pacing-curve / style-issues），把它们已经过 LLM 跑出来、且过
// 原文核验的发现拎进清单——本视图不跑任何新的 LLM 抽取，只做收集 + 过滤 + 去重。
//
// evidence-first：聚合逻辑（revisionStore.findingsFrom*）只收核验过 + 带原文的发现，
// 核不过的进不了清单。三态是纯前端状态，连同清单本身存 localStorage（CPU-only、不碰后端）。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useState } from "react";
import { SealMark } from "./SealMark";
import { SealButton } from "./SealButton";
import {
  CATEGORY_LABEL,
  buildRevisionMarkdown,
  findingsFromConsistency,
  findingsFromForeshadow,
  findingsFromPacing,
  findingsFromStyle,
  getItems,
  mergeFindings,
  saveItems,
} from "./revisionStore";
import type {
  FindingCategory,
  NewFinding,
  RevisionItem,
  RevisionStatus,
} from "./revisionStore";

interface RevisionListProps {
  sessionId: string;
  bookTitle: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

const STATUS_OPTIONS: { value: RevisionStatus; label: string }[] = [
  { value: "todo", label: "待改" },
  { value: "done", label: "已改" },
  { value: "wontfix", label: "不改" },
];

// 汇总要拉的四个诊断端点 + 各自的取数器 + 字段名——按需 fetch，逐个跑。
const DIGEST_SOURCES: {
  category: FindingCategory;
  path: string;
  /** 从端点 JSON 里抠出候选发现 */
  extract: (data: Record<string, unknown>) => NewFinding[];
}[] = [
  {
    category: "consistency",
    path: "/api/agent/consistency-scan",
    extract: (d) =>
      findingsFromConsistency(
        Array.isArray(d.contradictions)
          ? (d.contradictions as Parameters<typeof findingsFromConsistency>[0])
          : [],
      ),
  },
  {
    category: "foreshadow",
    path: "/api/agent/foreshadow-arcs",
    extract: (d) =>
      findingsFromForeshadow(
        Array.isArray(d.arcs)
          ? (d.arcs as Parameters<typeof findingsFromForeshadow>[0])
          : [],
      ),
  },
  {
    category: "pacing",
    path: "/api/agent/pacing-curve",
    extract: (d) =>
      findingsFromPacing(
        Array.isArray(d.points)
          ? (d.points as Parameters<typeof findingsFromPacing>[0])
          : [],
      ),
  },
  {
    category: "style",
    path: "/api/agent/style-issues",
    extract: (d) =>
      findingsFromStyle(
        Array.isArray(d.issues)
          ? (d.issues as Parameters<typeof findingsFromStyle>[0])
          : [],
      ),
  },
];

export function RevisionList({
  sessionId,
  bookTitle,
  provider,
  apiKey,
  model,
  baseUrl,
}: RevisionListProps) {
  const [items, setItems] = useState<RevisionItem[]>([]);
  const [digesting, setDigesting] = useState(false);
  // 汇总进度：当前在拉哪一类 + 已加了几条 + 是否有端点失败
  const [digestStage, setDigestStage] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [failures, setFailures] = useState<string[]>([]);

  // 换书 / 进视图时从 localStorage 恢复
  useEffect(() => {
    setItems(getItems(sessionId));
    setLastResult(null);
    setFailures([]);
  }, [sessionId]);

  function persist(next: RevisionItem[]) {
    setItems(next);
    saveItems(sessionId, next);
  }

  function setStatus(id: string, status: RevisionStatus) {
    persist(items.map((it) => (it.id === id ? { ...it, status } : it)));
  }

  function removeItem(id: string) {
    persist(items.filter((it) => it.id !== id));
  }

  function clearAll() {
    persist([]);
  }

  // 一键汇总：逐个拉诊断端点，把过证据的发现并进清单（去重）。
  // 不调新 LLM——这些端点本就是用户在各面板手动跑的同一批诊断。
  async function runDigest() {
    if (!apiKey || digesting) return;
    setDigesting(true);
    setLastResult(null);
    setFailures([]);
    let working = getItems(sessionId); // 拿最新盘上数据，避免覆盖别处改动
    let totalAdded = 0;
    const failed: string[] = [];

    for (const src of DIGEST_SOURCES) {
      setDigestStage(CATEGORY_LABEL[src.category]);
      try {
        const body: Record<string, unknown> = {
          book_session_id: sessionId,
          provider,
          api_key: apiKey,
        };
        if (model) body.model = model;
        if (baseUrl) body.base_url = baseUrl;
        const resp = await fetch(src.path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!resp.ok) {
          failed.push(CATEGORY_LABEL[src.category]);
          continue;
        }
        const data = (await resp.json()) as Record<string, unknown>;
        const findings = src.extract(data);
        const merged = mergeFindings(working, findings);
        working = merged.items;
        totalAdded += merged.added;
      } catch {
        failed.push(CATEGORY_LABEL[src.category]);
      }
    }

    setDigestStage(null);
    persist(working);
    setFailures(failed);
    setLastResult(
      totalAdded > 0
        ? `汇总完成，新加 ${totalAdded} 条`
        : "汇总完成，没有新发现进清单（已有的或没核过证据的不重复加）",
    );
    setDigesting(false);
  }

  function handleExport() {
    if (items.length === 0) return;
    const md = buildRevisionMarkdown(bookTitle, items);
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `bookscope-改稿清单-${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const counts = useMemo(() => {
    const c = { todo: 0, done: 0, wontfix: 0 };
    for (const it of items) c[it.status] += 1;
    return c;
  }, [items]);

  // 按类分组展示——同 WP 的「按类分组」
  const groups = useMemo(() => {
    const order: FindingCategory[] = [
      "consistency",
      "foreshadow",
      "pacing",
      "style",
    ];
    return order
      .map((cat) => ({ cat, list: items.filter((it) => it.category === cat) }))
      .filter((g) => g.list.length > 0);
  }, [items]);

  return (
    <div className="pt-2">
      {/* 工具条：汇总 + 计数 + 导出 */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <SealButton
          size="sm"
          label="一键汇总全书诊断"
          loadingLabel={`汇总中 · 正在拉「${digestStage ?? ""}」…`}
          loading={digesting}
          disabled={!apiKey}
          onClick={runDigest}
        />
        <button
          type="button"
          onClick={handleExport}
          disabled={items.length === 0}
          className="text-xs px-3 py-1.5 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-40 transition-colors"
        >
          导出 Markdown
        </button>
        {items.length > 0 && (
          <button
            type="button"
            onClick={clearAll}
            disabled={digesting}
            className="text-xs px-2.5 py-1.5 rounded border border-transparent text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] disabled:opacity-40 transition-colors"
          >
            清空
          </button>
        )}
        {items.length > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] ml-auto">
            共 {items.length} · 待改 {counts.todo} · 已改 {counts.done} · 不改{" "}
            {counts.wontfix}
          </span>
        )}
      </div>

      {/* 汇总结果 / 失败提示 */}
      {lastResult && (
        <p className="text-xs text-[var(--color-ink-muted)] mb-2">{lastResult}</p>
      )}
      {failures.length > 0 && (
        <p className="text-xs mb-3" style={{ color: "var(--color-seal)" }}>
          这几类没拉成（可单独去对应面板重试）：{failures.join(" / ")}
        </p>
      )}

      {/* 空态 */}
      {items.length === 0 && !digesting && (
        <div className="rounded-md border border-dashed border-[var(--color-rule)] px-4 py-8 text-center">
          <p className="text-sm text-[var(--color-ink)] mb-1">
            清单还是空的。
          </p>
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            点上面「一键汇总全书诊断」，把这本书已扫出的矛盾 / 断伏笔 / 塌节奏 /
            文体毛病攒成一份带原文的修改清单，核不过原文的发现不会进来。
          </p>
        </div>
      )}

      {/* 清单：按类分组 */}
      <div className="space-y-6">
        {groups.map((g) => (
          <div key={g.cat}>
            <div
              className="text-sm mb-2"
              style={{
                fontFamily: "var(--font-display)",
                fontWeight: 600,
                color: "var(--color-seal)",
              }}
            >
              {CATEGORY_LABEL[g.cat]} · {g.list.length}
            </div>
            <ul className="space-y-3">
              {g.list.map((it) => (
                <li
                  key={it.id}
                  className="rounded-md border pl-4 pr-3 py-3"
                  style={{
                    borderColor: "var(--color-folio-edge)",
                    background: "var(--color-paper-raised)",
                    opacity: it.status === "wontfix" ? 0.6 : 1,
                  }}
                >
                  {/* 问题描述 + 三态 + 删 */}
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <p
                      className="text-body leading-relaxed text-[var(--color-ink)]"
                      style={{
                        fontFamily: "var(--font-display)",
                        textDecoration:
                          it.status === "done" ? "line-through" : "none",
                      }}
                    >
                      {it.problem}
                    </p>
                    <button
                      type="button"
                      onClick={() => removeItem(it.id)}
                      aria-label="从清单移除"
                      title="从清单移除"
                      className="shrink-0 text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                    >
                      ✕
                    </button>
                  </div>

                  {/* 三态切换：分段按钮 */}
                  <div
                    className="inline-flex rounded border border-[var(--color-rule)] overflow-hidden mb-2.5"
                    role="group"
                    aria-label="改稿状态"
                  >
                    {STATUS_OPTIONS.map((opt) => {
                      const active = it.status === opt.value;
                      return (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setStatus(it.id, opt.value)}
                          className="text-caption px-2.5 py-1 transition-colors"
                          style={
                            active
                              ? {
                                  background: "var(--color-seal)",
                                  color: "var(--color-paper)",
                                }
                              : {
                                  background: "transparent",
                                  color: "var(--color-ink-muted)",
                                }
                          }
                        >
                          {opt.label}
                        </button>
                      );
                    })}
                  </div>

                  {/* 原文证据：可一处或两处（跨章类带「另一处」） */}
                  <div className="space-y-2">
                    {it.evidence.map((ev, j) => (
                      <div
                        key={j}
                        className="border-l-2 border-[var(--color-seal)]/40 pl-3 py-1"
                      >
                        <div className="text-xs text-[var(--color-ink-muted)] mb-1 flex items-center gap-1.5">
                          <span>第 {ev.chapter} 章</span>
                          {ev.role === "counterpart" && (
                            <span className="italic">· 牵连的另一处</span>
                          )}
                          {ev.verified && (
                            <SealMark size={16} title="原文已核验" />
                          )}
                        </div>
                        <div
                          className="text-body-sm leading-relaxed text-[var(--color-ink)]"
                          style={{ fontFamily: "var(--font-display)" }}
                        >
                          {ev.snippet}
                        </div>
                      </div>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
