// ---------------------------------------------------------------------------
// RelationshipTimeline — 关系编年（WP-relationship-over-time，1.5.1 重做）
//
// 旧版画的是抽象的强度曲线，看不出"为什么变""怎么变"。这一版换成「关系编年」：
// 一对人物的关系不再是一条线，而是一份有评点总判 + 逐幕编年的东西。
//   · 先选一对人（搜得到全书任何人）——便宜的全员对清单，不调 LLM。
//   · 选中一对 → 调 LLM 出这对的关系编年：
//       总判块（本质 / 走向 / 两人各自的看法 / 最尖锐一笔）
//       + 逐幕时间线（每章一幕：发生了什么、此刻什么状态、为何变、原文）。
// evidence-first：原文核不过或为空就老实标「待核」，绝不假装有。
// 敌友色温：每幕节点颜色按 valence 从暖(盟)到冷(敌)取色——这是数据色，不跟主题走。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { useVizFocus } from "./viz/vizFocus";
import { EvidencePopover } from "./viz/EvidencePopover";

// ---- 新接口契约 ----
interface Verdict {
  essence: string;
  arc: string;
  asymmetric: boolean;
  view_a_on_b: string;
  view_b_on_a: string;
  sharp_point: string;
  pivot_chapter: number | null;
}

interface Beat {
  chapter: number;
  scene: string;
  state: string;
  valence: number; // -5(死敌)..0(中立)..+5(盟友)
  change: string;
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface ChroniclePair {
  a: string;
  b: string;
  verdict: Verdict;
  beats: Beat[];
}

interface PairBrief {
  a: string;
  b: string;
  chapters: number[];
  first: number;
  last: number;
  count: number;
}

interface RelationshipTimelineProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  // 从关系网点了某个人跳过来时带上他的名字（每次点都是新对象引用，连点同一人也能重新聚焦）。
  // 不传 / 为空时跟以前完全一样。
  focusPerson?: { name: string } | null;
}

// 敌友色温：valence -5..+5 → 暖(盟，朱) ←→ 冷(敌，青)。0 取中间灰青。
// 这是数据色，写死 hex，不跟随主题（主题里没有"敌友"这维）。
const WARM = [0xc0, 0x51, 0x2e]; // #C0512E 暖·盟
const MID = [0x8a, 0x82, 0x7a]; // 中性灰
const COOL = [0x2e, 0x6b, 0x82]; // #2E6B82 冷·敌
function lerp(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t);
}
function valenceColor(v: number): string {
  const x = Math.max(-5, Math.min(5, v));
  let rgb: number[];
  if (x >= 0) {
    // 0..+5：中性 → 暖
    const t = x / 5;
    rgb = [0, 1, 2].map((k) => lerp(MID[k], WARM[k], t));
  } else {
    // 0..-5：中性 → 冷
    const t = -x / 5;
    rgb = [0, 1, 2].map((k) => lerp(MID[k], COOL[k], t));
  }
  return `#${rgb.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

// 一对人的稳定 key，跟人名顺序无关（清单里 a/b 顺序未必和编年一致）。
function pairKey(a: string, b: string): string {
  return [a, b].sort().join("|");
}

export function RelationshipTimeline({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  focusPerson,
}: RelationshipTimelineProps) {
  // 全员对清单（不传 pair 的那次返回）
  const [pairs, setPairs] = useState<PairBrief[] | null>(null);
  const [listTrace, setListTrace] = useState<RunTrace | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  // 选择器
  const [query, setQuery] = useState("");
  const [selKey, setSelKey] = useState<string | null>(null);

  // 选中一对的编年（按 pairKey 缓存，切回来不重复请求）
  const [chronicles, setChronicles] = useState<Record<string, ChroniclePair>>(
    {},
  );
  const [pairLoading, setPairLoading] = useState(false);
  const [pairError, setPairError] = useState<string | null>(null);
  const [pairTrace, setPairTrace] = useState<RunTrace | null>(null);

  // pivot 点击滚动到对应那一幕
  const beatRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const [flashCh, setFlashCh] = useState<number | null>(null);

  // 联动总线：也订阅它，从关系图点一个人这里就跟着聚焦。
  const { focus } = useVizFocus();
  // 有效聚焦人 = 总线优先、prop 兜底。总线上是 person 就取它的 label 当人名。
  const effectiveFocus =
    (focus?.kind === "person" ? { name: focus.label } : null) ?? focusPerson;

  // 记住已处理过的那次聚焦，免得 pairs/effect 重跑时重复触发。
  // 总线的 focus 每次渲染是新对象，所以按名字（值）去重，不按对象引用。
  const handledFocusRef = useRef<string | null>(null);

  function reqBody(extra?: Record<string, unknown>): Record<string, unknown> {
    const body: Record<string, unknown> = {
      book_session_id: sessionId,
      provider,
      api_key: apiKey,
    };
    if (model) body.model = model;
    if (baseUrl) body.base_url = baseUrl;
    return { ...body, ...extra };
  }

  // 第一步：拉全员对清单（不传 pair，便宜，不调 LLM）
  async function loadPairs() {
    setListLoading(true);
    setListError(null);
    try {
      const resp = await fetch("/api/agent/relationship-timeline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody()),
      });
      if (!resp.ok) {
        const j = (await resp.json().catch(() => null)) as
          | { detail?: { message?: string } }
          | null;
        throw new Error(j?.detail?.message ?? `请求失败（${resp.status}）`);
      }
      const data = (await resp.json()) as {
        pairs?: PairBrief[];
        trace?: RunTrace;
      };
      setListTrace(data.trace ?? null);
      const ps = (data.pairs ?? [])
        .filter((p) => p && p.a && p.b)
        .sort((x, y) => y.count - x.count);
      if (ps.length === 0) {
        setListError("没扫出有来往的人物对，稍后重试。");
        return;
      }
      setPairs(ps);
      // 默认自动选 count 最高的那对
      const top = ps[0];
      const k = pairKey(top.a, top.b);
      setSelKey(k);
      void loadChronicle(top.a, top.b, k);
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e));
    } finally {
      setListLoading(false);
    }
  }

  // 第二步：拉某一对的关系编年（传 pair_a/pair_b，调 LLM）。已缓存就不重复请求。
  async function loadChronicle(a: string, b: string, key: string) {
    if (chronicles[key]) {
      setSelKey(key);
      return;
    }
    setPairLoading(true);
    setPairError(null);
    setSelKey(key);
    try {
      const resp = await fetch("/api/agent/relationship-timeline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody({ pair_a: a, pair_b: b })),
      });
      if (!resp.ok) {
        const j = (await resp.json().catch(() => null)) as
          | { detail?: { message?: string } }
          | null;
        throw new Error(j?.detail?.message ?? `请求失败（${resp.status}）`);
      }
      const data = (await resp.json()) as {
        relations?: ChroniclePair[];
        trace?: RunTrace;
      };
      setPairTrace(data.trace ?? null);
      const cp = data.relations?.[0];
      if (!cp || !cp.verdict) {
        setPairError("这一对没抽出关系编年，换一对或稍后重试。");
        return;
      }
      setChronicles((prev) => ({ ...prev, [key]: cp }));
    } catch (e) {
      setPairError(e instanceof Error ? e.message : String(e));
    } finally {
      setPairLoading(false);
    }
  }

  // 搜索过滤：输入"刘备"过滤出所有含刘备的对
  const filtered = useMemo(() => {
    if (!pairs) return [];
    const q = query.trim();
    if (!q) return pairs;
    return pairs.filter((p) => p.a.includes(q) || p.b.includes(q));
  }, [pairs, query]);

  const cur = selKey ? chronicles[selKey] ?? null : null;

  // 从关系图点了某个人跳过来（走总线，或旧的 focusPerson prop）：先确保有清单（没拉过就拉一次），
  // 再把搜索框填成他的名字（列表立刻只剩含他的对）。若含他的对里有明显最重的一对，顺手下钻。
  useEffect(() => {
    if (!effectiveFocus) return;
    const name = effectiveFocus.name;
    // 同一个人只处理一次（按名字去重，总线的 focus 对象每渲染都新）。
    if (handledFocusRef.current === name) return;

    // 还没拉清单：拉一次（会先按全局 top 自动选一对），等 pairs 到了 effect 会重跑再聚焦。
    if (!pairs) {
      if (apiKey && !listLoading) void loadPairs();
      return; // 先别标已处理——等 pairs 回来重跑这个 effect 才真正聚焦
    }

    handledFocusRef.current = name;
    setQuery(name);

    // 含这个人的所有对里挑 count 最高的下钻（pairs 已按 count 降序，第一个命中即最重）。
    const hit = pairs.find((p) => p.a === name || p.b === name);
    if (hit) {
      const k = pairKey(hit.a, hit.b);
      void loadChronicle(hit.a, hit.b, k);
    }
    // loadPairs / loadChronicle 是稳定闭包，effectiveFocus 的名字 / pairs 变化才需重跑
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveFocus?.name, pairs]);

  function scrollToBeat(ch: number) {
    const el = beatRefs.current[ch];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setFlashCh(ch);
      window.setTimeout(() => setFlashCh((c) => (c === ch ? null : c)), 1600);
    }
  }

  // ---- 未生成：入口卡片 ----
  if (!pairs) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          关系演变
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          挑一对人，看他俩的关系一章章怎么走到今天，先给一句本质总判，再一幕幕排开：哪章发生了什么、此刻是敌是友、为什么变，每一笔都钉在原文。（谁和谁的整张关系网看「关系图」。）
        </p>
        <button
          type="button"
          onClick={loadPairs}
          disabled={listLoading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {listLoading ? "扫全书人物来往中…" : "生成关系演变"}
        </button>
        {listError && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {listError}
          </p>
        )}
        {!apiKey && (
          <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
            填了 API key 才能生成。
          </p>
        )}
        {listLoading && (
          <RunningProcess
            label="扫全书人物来往"
            hint="先快扫一遍谁和谁有来往，列出全书所有人物对，这一步不调模型、很快。选定一对后再细读那对的关系编年。"
          />
        )}
      </div>
    );
  }

  // ---- 已有清单：选择器 + 编年 ----
  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          关系演变
        </h3>
        <button
          type="button"
          onClick={() => {
            setPairs(null);
            setSelKey(null);
            setChronicles({});
            setQuery("");
            setPairError(null);
            void loadPairs();
          }}
          disabled={listLoading}
          className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {listLoading ? "重出中…" : "重新生成"}
        </button>
      </div>

      {!listLoading && (
        <RunStats trace={listTrace} note={`全书 ${pairs.length} 对人物来往`} />
      )}

      {/* ── 选择器：搜索框 + 对列表 ── */}
      <div className="mt-3">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜人名，如「刘备」，列出含他的所有关系对"
          className="w-full text-sm px-3 py-2 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] focus:border-[var(--color-seal)] outline-none"
        />
        <div className="mt-2 max-h-44 overflow-y-auto rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)]">
          {filtered.length === 0 ? (
            <p className="px-3 py-3 text-xs text-[var(--color-ink-muted)]">
              没找到含「{query}」的关系对。
            </p>
          ) : (
            <ul>
              {filtered.map((p) => {
                const k = pairKey(p.a, p.b);
                const on = k === selKey;
                return (
                  <li key={k}>
                    <button
                      type="button"
                      onClick={() => void loadChronicle(p.a, p.b, k)}
                      className="w-full text-left px-3 py-2 flex items-center justify-between gap-2 border-b border-[var(--color-rule)] last:border-b-0 hover:bg-[var(--color-seal-soft)] transition-colors"
                      style={on ? { background: "var(--color-seal-soft)" } : undefined}
                    >
                      <span
                        className="text-sm"
                        style={{
                          fontFamily: "var(--font-display)",
                          color: on ? "var(--color-seal)" : "var(--color-ink)",
                        }}
                      >
                        {p.a}—{p.b}
                      </span>
                      <span className="text-xs text-[var(--color-ink-muted)] tabular-nums shrink-0">
                        {p.count} 章 · 第 {p.first}–{p.last} 章
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      {/* ── 选中一对的编年 ── */}
      {pairLoading && (
        <RunningProcess
          label="细读这一对的关系编年"
          hint="整本书喂进模型，逐章梳理他俩的来往，本质、走向、每一幕怎么变，每一笔回原文核验，约几十秒。"
        />
      )}

      {!pairLoading && pairError && (
        <p className="mt-3 text-sm" style={{ color: "var(--color-seal)" }}>
          {pairError}
        </p>
      )}

      {!pairLoading && cur && (
        <Chronicle
          cur={cur}
          trace={pairTrace}
          beatRefs={beatRefs}
          flashCh={flashCh}
          onPivot={scrollToBeat}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 一对人的关系编年：总判块 + 逐幕时间线
// ---------------------------------------------------------------------------
function Chronicle({
  cur,
  trace,
  beatRefs,
  flashCh,
  onPivot,
}: {
  cur: ChroniclePair;
  trace: RunTrace | null;
  beatRefs: React.MutableRefObject<Record<number, HTMLDivElement | null>>;
  flashCh: number | null;
  onPivot: (ch: number) => void;
}) {
  const { a, b, verdict, beats } = cur;
  const total = beats.length;
  const verified = beats.filter((bt) => bt.verified && bt.evidence).length;
  const v = verdict;

  return (
    <div className="mt-4">
      {/* 顶部统计 */}
      <p className="text-xs text-[var(--color-ink-muted)] mb-3">
        <span style={{ fontFamily: "var(--font-display)" }}>
          {a}—{b}
        </span>
        {" · "}共 {total} 幕 · 原文核验 {verified}/{total}
      </p>

      {/* ── 总判块 ── */}
      <div className="p-4 rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)]">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          总判 · 评点
        </span>

        {v.essence && (
          <p
            className="mt-2 text-[var(--color-ink)] leading-snug"
            style={{ fontFamily: "var(--font-display)", fontSize: "18px" }}
          >
            {v.essence}
          </p>
        )}

        {v.arc && (
          <p className="mt-1.5 text-sm text-[var(--color-ink-muted)]">
            总体走向 · {v.arc}
          </p>
        )}

        {/* asymmetric=true 才画两栏；两人各自怎么看对方 */}
        {v.asymmetric && (v.view_a_on_b || v.view_b_on_a) && (
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="p-3 rounded border border-[var(--color-rule)] bg-white">
              <p className="text-xs text-[var(--color-ink-muted)] mb-1">
                {a}眼中的{b}
              </p>
              <p className="text-sm text-[var(--color-ink)] leading-relaxed">
                {v.view_a_on_b || "—"}
              </p>
            </div>
            <div className="p-3 rounded border border-[var(--color-rule)] bg-white">
              <p className="text-xs text-[var(--color-ink-muted)] mb-1">
                {b}眼中的{a}
              </p>
              <p className="text-sm text-[var(--color-ink)] leading-relaxed">
                {v.view_b_on_a || "—"}
              </p>
            </div>
          </div>
        )}

        {/* 最尖锐一笔 */}
        {v.sharp_point && (
          <div className="mt-3 pt-3 border-t border-[var(--color-rule)]">
            {v.pivot_chapter != null ? (
              <button
                type="button"
                onClick={() => onPivot(v.pivot_chapter as number)}
                className="text-left text-sm leading-relaxed hover:underline"
                style={{ color: "var(--color-seal)" }}
              >
                {v.sharp_point}
                <span className="ml-1 text-xs opacity-80">
                  （第 {v.pivot_chapter} 章 ›）
                </span>
              </button>
            ) : (
              <p className="text-sm leading-relaxed" style={{ color: "var(--color-seal)" }}>
                {v.sharp_point}
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── 逐幕编年（竖向时间线） ── */}
      <div className="mt-4">
        {beats.map((bt, idx) => {
          const color = valenceColor(bt.valence);
          const flash = flashCh === bt.chapter;
          const isLast = idx === beats.length - 1;
          return (
            <div key={`${bt.chapter}-${idx}`}>
              {/* 幕间「为何变」连接说明（首幕 change 常为空，空就不显示） */}
              {idx > 0 && bt.change && (
                <div className="flex">
                  <div className="w-6 flex justify-center shrink-0">
                    <span
                      className="w-px h-full"
                      style={{ background: "var(--color-rule)" }}
                    />
                  </div>
                  <p className="py-1.5 text-xs text-[var(--color-ink-muted)] leading-relaxed">
                    为何变 · {bt.change}
                  </p>
                </div>
              )}

              {/* 一幕 */}
              <div className="flex">
                {/* 左侧时间轴：竖线 + 节点圆点（颜色 = 敌友色温） */}
                <div className="w-6 flex flex-col items-center shrink-0">
                  <span
                    className="w-3 h-3 rounded-full mt-1.5 shrink-0"
                    style={{ background: color, boxShadow: `0 0 0 2px var(--color-paper)` }}
                  />
                  {!isLast && (
                    <span
                      className="w-px flex-1 mt-1"
                      style={{ background: "var(--color-rule)" }}
                    />
                  )}
                </div>

                {/* 幕卡 */}
                <div
                  ref={(el) => {
                    beatRefs.current[bt.chapter] = el;
                  }}
                  className="flex-1 mb-3 p-3 rounded border bg-white transition-colors"
                  style={{
                    borderColor: flash ? "var(--color-seal)" : "var(--color-rule)",
                    borderWidth: "0.5px",
                    background: flash ? "var(--color-seal-soft)" : undefined,
                  }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-bold text-[var(--color-ink)] leading-snug">
                      第{bt.chapter}章 · {bt.scene || "（这一幕没给场景）"}
                    </p>
                    {bt.state && (
                      <span
                        className="text-xs px-2 py-0.5 rounded-full shrink-0 whitespace-nowrap"
                        style={{ color, border: `0.5px solid ${color}` }}
                      >
                        {bt.state}
                      </span>
                    )}
                  </div>

                  {/* 原文收进浮层：hover / 聚焦「原文」二字才浮出引文 + 章号 + 证据强度徽记。
                      没原文时浮层自己显「待核」，evidence-first 那条不丢。幕卡里只留一个紧凑触发签。 */}
                  <div className="mt-2">
                    <EvidencePopover
                      quote={bt.evidence}
                      chapter={bt.chapter}
                      verified={bt.verified}
                      matchScore={bt.match_score}
                    >
                      <span
                        className="text-xs cursor-help text-[var(--color-ink-muted)]"
                        style={{
                          borderBottom: "1px dotted var(--color-rule)",
                        }}
                      >
                        原文
                      </span>
                    </EvidencePopover>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {!!trace && <RunStats trace={trace} note={`${a}—${b} 共 ${total} 幕`} />}
    </div>
  );
}
