// ---------------------------------------------------------------------------
// CharacterArc — 人物弧线（WP-character-arc-curves，probe GO）
//
// 点生成 → 调 /api/agent/character-arc（整本进上下文给主要角色逐章抽戏份 + 处境）→ 画成
// 「工笔花鸟」品读视图（见 HuaniaoArc）：每个角色一枝，枝条上扬下垂=处境起落、着花疏密=戏份，
// 点一朵花看那章原文。可切「看全部 / 单个角色」。
//
// 诚实呈现（probe 结论 + memory feedback_viz_algorithm_rigor）：presence/fortune 是模型逐章判读、
// 绝对值会抖，所以只画相对形状（枝的起伏 + 花的疏密）、明细给相对档（戏重/有戏/少戏、得势/落难/平），
// 不印"戏份 8/10"那种假精确。evidence-first：核不过的点画空心花苞、标低置信。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { type ArcCharacter, HuaniaoArc } from "./HuaniaoArc";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";

interface CharacterArcProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 角色配色取一组克制的古籍色（不刺眼、可区分），循环用
const ARC_PALETTE = ["#9a5b52", "#5f7a6b", "#8c6b4f", "#6b6f8c", "#8a7a4a", "#5b7d8a"];

// 选择器默认只列戏份最重的前几个主要角色，剩下的折进"看全部"
const MAIN_COUNT = 8;

interface SelectedPoint {
  name: string;
  chapter: number;
}

function presenceBand(p: number): string {
  if (p >= 7) return "戏重";
  if (p >= 3) return "有戏";
  return "少戏";
}

function fortuneWord(f: number): string {
  if (f > 1) return "得势";
  if (f < -1) return "落难";
  return "处境平";
}

export function CharacterArc({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: CharacterArcProps) {
  const [characters, setCharacters] = useState<ArcCharacter[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [selected, setSelected] = useState<SelectedPoint | null>(null);
  const [focusChar, setFocusChar] = useState<string | null>(null);
  // 选择器：搜人名过滤 + 默认只列主要角色、"看全部"展开
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    setSelected(null);
    setFocusChar(null);
    setQuery("");
    setShowAll(false);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/character-arc", {
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
        characters: ArcCharacter[];
        scanned?: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      if (!data.characters || data.characters.length === 0) {
        setError("没抽出人物弧线，稍后重试。");
      } else {
        setCharacters(
          data.characters.map((c) => ({
            ...c,
            points: [...c.points].sort((p, q) => p.chapter - q.chapter),
          })),
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const charColor = useMemo(() => {
    const map = new Map<string, string>();
    if (!characters) return map;
    characters.forEach((c, i) => map.set(c.name, ARC_PALETTE[i % ARC_PALETTE.length]));
    return map;
  }, [characters]);

  // 角色按"戏份"降序——戏份 = 全书各章 presence 之和（跟花鸟里挑枝同一口径）。
  // 顺带带上出场章数，列表里给用户看一眼分量。
  const ranked = useMemo(() => {
    if (!characters) return [] as { name: string; weight: number; chapters: number }[];
    return [...characters]
      .map((c) => ({
        name: c.name,
        weight: c.points.reduce((s, p) => s + p.presence, 0),
        chapters: c.points.length,
      }))
      .sort((a, b) => b.weight - a.weight);
  }, [characters]);

  // 搜索过滤：输"刘备"只剩名字含刘备的
  const filtered = useMemo(() => {
    const q = query.trim();
    if (!q) return ranked;
    return ranked.filter((r) => r.name.includes(q));
  }, [ranked, query]);

  // 默认只列前 MAIN_COUNT 个主要角色；点"看全部"或正在搜索时铺开全部命中
  const visibleList = showAll || query.trim() ? filtered : filtered.slice(0, MAIN_COUNT);

  if (!characters) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          人物弧线
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          给主要角色各画一枝——枝条上扬下垂是处境起落，着花疏密是戏份多寡。点一朵花看那章原文。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读全书出弧线中（约 1 分钟）…" : "生成人物弧线"}
        </button>
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {!apiKey && (
          <p className="mt-3 text-xs text-[var(--color-ink-muted)]">填了 API key 才能生成。</p>
        )}
        {loading && (
          <RunningProcess
            label="读全书出人物弧线"
            hint="整本书喂进模型，给主要角色逐章判戏份与处境——每个点都回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  const sel = selected
    ? characters
        .find((c) => c.name === selected.name)
        ?.points.find((p) => p.chapter === selected.chapter)
    : null;

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          人物弧线
        </h3>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "重出中…" : "重新生成"}
        </button>
      </div>

      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        每个角色一枝：枝条上扬=得势、下垂=落难，着花越繁=这章戏越重。点一朵花看那章原文；淡空心花=原文没核验上。处境/戏份只画相对起落（模型判读，不报精确分）。
      </p>

      {/* ── 选择器：搜人名 + 按戏份排序的角色清单（几百号人也挑得动） ── */}
      <div className="mb-3">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜人名，如「刘备」——只看他一枝"
          className="w-full text-sm px-3 py-2 rounded border border-[var(--color-rule)] bg-white focus:border-[var(--color-seal)] outline-none"
        />
        <div className="mt-2 max-h-44 overflow-y-auto rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)]">
          {/* 看全部一枝不挑：回到全员小多图 */}
          <button
            type="button"
            onClick={() => {
              setFocusChar(null);
              setSelected(null);
            }}
            className="w-full text-left px-3 py-2 flex items-center gap-2 border-b border-[var(--color-rule)] hover:bg-[var(--color-seal-soft)] transition-colors"
            style={focusChar === null ? { background: "var(--color-seal-soft)" } : undefined}
          >
            <span className="inline-block w-2.5 h-2.5 rounded-sm bg-[var(--color-ink-muted)]" aria-hidden />
            <span
              className="text-sm"
              style={{ color: focusChar === null ? "var(--color-seal)" : "var(--color-ink)" }}
            >
              看全部（戏份最重的几枝）
            </span>
          </button>

          {visibleList.length === 0 ? (
            <p className="px-3 py-3 text-xs text-[var(--color-ink-muted)]">
              没找到名字含「{query}」的角色。
            </p>
          ) : (
            <ul>
              {visibleList.map((r) => {
                const on = focusChar === r.name;
                return (
                  <li key={r.name}>
                    <button
                      type="button"
                      onClick={() => {
                        setFocusChar((cur) => (cur === r.name ? null : r.name));
                        setSelected(null);
                      }}
                      className="w-full text-left px-3 py-2 flex items-center justify-between gap-2 border-b border-[var(--color-rule)] last:border-b-0 hover:bg-[var(--color-seal-soft)] transition-colors"
                      style={on ? { background: "var(--color-seal-soft)" } : undefined}
                    >
                      <span className="flex items-center gap-2 min-w-0">
                        <span
                          className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                          style={{ background: charColor.get(r.name) }}
                          aria-hidden
                        />
                        <span
                          className="text-sm truncate"
                          style={{
                            fontFamily: "var(--font-display)",
                            color: on ? "var(--color-seal)" : "var(--color-ink)",
                          }}
                        >
                          {r.name}
                        </span>
                      </span>
                      <span className="text-xs text-[var(--color-ink-muted)] tabular-nums shrink-0">
                        {r.chapters} 章
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* 默认折叠时给一个"看全部"展开；正在搜索就不显示（搜索已铺开命中项） */}
        {!query.trim() && filtered.length > MAIN_COUNT && (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="mt-1.5 text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
          >
            {showAll
              ? "收起，只看主要角色"
              : `看全部 ${filtered.length} 个角色 ›`}
          </button>
        )}
      </div>

      <HuaniaoArc
        characters={characters}
        charColor={charColor}
        focusChar={focusChar}
        selected={selected}
        onSelect={(name, chapter) => setSelected({ name, chapter })}
      />

      {sel && selected && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            「{selected.name}」· 第 {sel.chapter} 章 · {presenceBand(sel.presence)} ·{" "}
            {fortuneWord(sel.fortune)}
            <span className="font-normal text-[var(--color-ink-muted)]">（模型判读）</span>
          </p>
          <p className="mt-1 text-sm text-[var(--color-ink)] leading-relaxed">
            {sel.evidence || "（这章没给出原文依据）"}
          </p>
          <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
            {sel.verified ? "原文已核验" : "原文未在书中比对命中——这点仅供参考"}
          </p>
        </div>
      )}

      {loading ? (
        <RunningProcess label="重出人物弧线" />
      ) : (
        <RunStats trace={trace} note={`${characters.length} 个主要角色`} />
      )}
    </div>
  );
}
