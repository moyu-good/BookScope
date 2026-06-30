// ---------------------------------------------------------------------------
// EntityRecall — 实体回溯快查（功能队列第 1 个）
//
// 输一个实体（人/物/地点/概念）→ 调 /api/agent/entity-recall（整本进上下文回溯它的
// 全书出现处）→ 竖向轨迹。每处带章节 / 在做什么 / 原文出处，核验过的盖朱砂钤印。
// 与「全书透视」一键功能的区别：要先输实体名再跑。沿用时间线竖向样式 + SealMark。
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

interface Appearance {
  order: number;
  chapter: number;
  what: string;
  snippet: string;
  verified?: boolean;
}

interface EntityRecallProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  /** 从 agent 编排 drill-into 进来时预填的实体名 + 一个变化令牌，到了就自动跑一次。 */
  prefill?: { value: string; token: number } | null;
}

export function EntityRecall({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  prefill,
}: EntityRecallProps) {
  const [entity, setEntity] = useState("");
  const [queried, setQueried] = useState<string | null>(null);
  const [appearances, setAppearances] = useState<Appearance[] | null>(null);
  const [scanned, setScanned] = useState(true);
  // 空值三态（task #29 根一）：扫过全书确实没这个实体 = 确证全书未出现（这是答案，不是搜漏）。
  const [confirmedAbsent, setConfirmedAbsent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);

  // drill-into：prefill 令牌变化时填入实体名并自动跑（apiKey 缺时只填不跑）。
  useEffect(() => {
    if (!prefill || !prefill.value.trim()) return;
    setEntity(prefill.value);
    if (apiKey) void loadFor(prefill.value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.token]);

  async function load() {
    await loadFor(entity);
  }

  async function loadFor(raw: string) {
    const e = raw.trim();
    if (!e) return;
    setLoading(true);
    setError(null);
    setOpenIdx(null);
    setAppearances(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        entity: e,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/entity-recall", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const j = (await resp.json().catch(() => null)) as
          | { detail?: { message?: string } }
          | null;
        throw new Error(j?.detail?.message ?? `请求失败（${resp.status}）`);
      }
      const data = (await resp.json()) as {
        entity: string;
        appearances: Appearance[];
        scanned: boolean;
        confirmed_absent?: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      setScanned(data.scanned);
      setConfirmedAbsent(!!data.confirmed_absent);
      setAppearances(data.appearances);
      setQueried(data.entity);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="pt-4">
      <p className="text-sm text-[var(--color-ink-muted)] mb-3 leading-relaxed">
        输一个人 / 物 / 地点 / 概念，回溯它在全书每次出现，在做什么、在哪一章、带原文出处。
      </p>

      <form
        onSubmit={(ev) => {
          ev.preventDefault();
          load();
        }}
        className="flex gap-2 mb-5"
      >
        <input
          value={entity}
          onChange={(e) => setEntity(e.target.value)}
          placeholder="比如：安禄山 / 灵宝之战 / 某个设定"
          className="flex-1 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] px-3 py-2 text-sm focus:border-[var(--color-seal)] outline-none"
          style={{ fontFamily: "var(--font-display)" }}
        />
        <button
          type="submit"
          disabled={loading || !apiKey || !entity.trim()}
          className="shrink-0 text-sm px-4 py-2 rounded bg-[var(--color-seal)] text-white hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {loading ? "回溯中（约 1 分钟）…" : "回溯"}
        </button>
      </form>

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label={`回溯「${entity.trim()}」`} />}

      {!scanned && appearances && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          这本书太大，暂不支持实体回溯。
        </p>
      )}

      {/* 确证全书未出现（空值三态 task #29）：扫过全书确实没这个实体——这是答案，笃定地说，
          不是"搜漏了 / 换个写法再试"那种像系统没找到的口吻。区别于 scanned=false 的"扫失败"。 */}
      {scanned && appearances && appearances.length === 0 && queried && (
        <div
          className="rounded-md px-3.5 py-3 flex items-start gap-2.5"
          style={{
            background: "rgba(79, 122, 82, 0.07)",
            border: "1px solid rgba(79, 122, 82, 0.28)",
          }}
        >
          <SealMark size={18} title="扫过全书" className="mt-0.5" />
          <div>
            <p
              className="text-sm font-bold"
              style={{ color: "#4f7a52", fontFamily: "var(--font-display)" }}
            >
              全书未出现「{queried}」
            </p>
            <p className="mt-0.5 text-[13px] leading-relaxed text-[var(--color-ink)]">
              回溯了全书每一章，这本书里确实没有「{queried}」。这是个确定的答案——不是没扫到。
              {confirmedAbsent ? "" : "（若怀疑是别名 / 别的写法，可换个说法再查。）"}
            </p>
          </div>
        </div>
      )}

      {appearances && appearances.length > 0 && (
        <>
          <p className="text-xs text-[var(--color-ink-muted)] mb-3">
            「{queried}」在全书 {appearances.length} 处出现：
          </p>
          <ol className="relative border-l border-[var(--color-rule)] ml-2">
            {appearances.map((ap, i) => (
              <li key={i} className="mb-4 ml-4">
                <span
                  className="absolute -left-[5px] w-2.5 h-2.5 rounded-full"
                  style={{ background: "var(--color-seal)" }}
                  aria-hidden="true"
                />
                <button
                  type="button"
                  onClick={() => setOpenIdx(openIdx === i ? null : i)}
                  className="text-left w-full"
                >
                  <div
                    className="text-[14px] leading-relaxed text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {ap.what || "（出现）"}
                  </div>
                  <div className="text-xs text-[var(--color-ink-muted)] mt-1 flex items-center gap-1.5">
                    <span>第 {ap.chapter} 章</span>
                    {ap.verified && <SealMark size={17} title="原文已核验" />}
                    <span className="ml-auto opacity-60">
                      {openIdx === i ? "收起原文" : "看原文"}
                    </span>
                  </div>
                </button>
                {openIdx === i && ap.snippet && (
                  <div
                    className="mt-1.5 border-l-2 border-[var(--color-seal)]/40 pl-3 py-1 text-[13px] leading-relaxed text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {ap.snippet}
                  </div>
                )}
              </li>
            ))}
          </ol>
          {!loading && <RunStats trace={trace} />}
        </>
      )}
    </div>
  );
}
