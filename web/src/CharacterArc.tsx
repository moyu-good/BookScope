// ---------------------------------------------------------------------------
// CharacterArc — 人物命运线（WP-character-arc-curves，probe GO）
//
// 点生成 → 调 /api/agent/character-arc（整本进上下文给主要角色逐章抽戏份 + 处境）→ 画成
// 「命运线」品读视图（见 FateLineArc）：每个主要角色一格 mini 折线，横轴章节、纵轴处境高低，
// 线随剧情起落，命运转折章用朱砂点钉在线上。点转折看那章原文。可切「看全部 / 单个角色」。
//
// 换掉了旧的「工笔花鸟枝条」——那图好看但读不出这个人到底变没变、何时变。命运线只答一件事：
// 这个主角变没变、何时变、往上走还是往下沉。
//
// 诚实呈现（probe 结论 + memory feedback_viz_algorithm_rigor）：fortune 是模型逐章判读、
// 绝对值会抖，所以纵轴只画相对形状、不标精确刻度；只有转折点（锚原文）才是硬信息。明细给相对档
// （得势/落难/平），不印"处境 8/10"那种假精确。evidence-first：核不过的点画空心、标低置信。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { type ArcCharacter, FateLineArc } from "./HuaniaoArc";
import { FortunePresenceGrid } from "./FortunePresenceGrid";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { SealButton } from "./SealButton";
import { SealMark } from "./SealMark";
import { categoricalPalette } from "./viz/vizTokens";

interface CharacterArcProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  // 可选:预置一份弧线数据,跳过"点生成"直接进品读视图。给预览 / 测试注入真数据用,
  // 生产不传(走点生成 → fetch 那条路)。
  initialCharacters?: ArcCharacter[];
}

// 角色配色取分类盘（跟关系图 / 在场图同一套浅底色板），循环用——清爽不脏、彼此分得开
const ARC_PALETTE = categoricalPalette;

// 选择器默认只列戏份最重的前几个主要角色，剩下的折进"看全部"
const MAIN_COUNT = 8;

interface SelectedPoint {
  name: string;
  chapter: number;
}

export function CharacterArc({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  initialCharacters,
}: CharacterArcProps) {
  const [characters, setCharacters] = useState<ArcCharacter[] | null>(
    initialCharacters ?? null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [selected, setSelected] = useState<SelectedPoint | null>(null);
  const [focusChar, setFocusChar] = useState<string | null>(null);
  // 选择器：搜人名过滤 + 默认只列主要角色、"看全部"展开
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  // 两个品读视图：命运线（小多图折线）↔ 处境在场（章×人热力格），共用同一份数据 + 下面的档案面板
  const [view, setView] = useState<"line" | "grid">("line");

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
      <FeatureEntryCard
        title="人物命运线"
        lead="给每个主要角色画一条命运线：横轴章节、纵轴处境高低，线随剧情起落，命运转折的章用朱砂点标出。点转折看那章原文。"
        actionLabel="生成人物命运线"
        loadingLabel="读全书出命运线中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书出章脉，约 1 分钟；命中缓存秒出"
        error={error}
      >
        {loading && (
          <RunningProcess
            label="读全书出人物命运线"
            hint="整本书喂进模型，给主要角色逐章判处境起落，每个点都回原文核验，约 1 分钟。"
          />
        )}
      </FeatureEntryCard>
    );
  }

  // 要展开档案的角色：优先点中的那个点所属角色，其次聚焦的那个角色。
  // 这样点一个转折 → 出这个人的整份命运档案（不只那一句），聚焦一个人也直接出档案。
  const profileName = selected?.name ?? focusChar;
  const profileChar = profileName
    ? characters.find((c) => c.name === profileName) ?? null
    : null;
  // 档案只列"锚了原文的处境转折"（有 evidence 的点）——在场但没判过处境的填充章不进档案，
  // 免得一屏"没依据/待核"（那是 densify 造的在场填充，剔掉、只留硬的）。
  const profilePoints = profileChar
    ? profileChar.points.filter((p) => p.evidence && p.evidence.trim())
    : [];
  // 命运线也只喂"锚原文的转折点"——去掉在场填充，线才不假装连续精确起伏。
  const groundedChars = characters
    .map((c) => ({ ...c, points: c.points.filter((p) => p.evidence && p.evidence.trim()) }))
    .filter((c) => c.points.length > 0);

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          人物命运线
        </h3>
        <SealButton
          size="sm"
          label="重新生成"
          loadingLabel="重出中…"
          loading={loading}
          onClick={load}
        />
      </div>

      {/* 视图开关：命运线（折线起落）↔ 处境在场（章×人热力格）。同一份数据两种看法。 */}
      <div className="inline-flex mb-2 rounded border border-[var(--color-rule)] overflow-hidden text-sm">
        {(["line", "grid"] as const).map((v) => {
          const on = view === v;
          return (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              className="px-3 py-1 transition-colors"
              style={{
                fontFamily: "var(--font-display)",
                background: on ? "var(--color-seal)" : "transparent",
                color: on ? "var(--color-paper)" : "var(--color-ink-muted)",
              }}
            >
              {v === "line" ? "命运线" : "处境在场"}
            </button>
          );
        })}
      </div>

      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        {view === "line"
          ? "命运线只画锚了原文的处境转折点（点看那章原文）：点往上=那一刻转好、往下=转坏；连线只表先后，不标精确刻度、不吹连续起伏。"
          : "章 × 人的格子墙：淡底=在场（章脉逐章、真），朱 / 墨格=锚了原文的处境转折（向好朱 / 转坏墨，可点看原文）。没判过处境的不上色、不编。"}
      </p>

      {/* ── 选择器：搜人名 + 按戏份排序的角色清单（几百号人也挑得动） ── */}
      <div className="mb-3">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜人名，如「刘备」，只看他一枝"
          className="w-full text-sm px-3 py-2 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] focus:border-[var(--color-seal)] outline-none"
        />
        <div className="mt-2 max-h-44 overflow-y-auto rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)]">
          {/* 看全部：回到全员小多图 */}
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
              看全部（命运起落最大的几人）
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

      {view === "line" ? (
        <FateLineArc
          characters={groundedChars}
          charColor={charColor}
          focusChar={focusChar}
          selected={selected}
          onSelect={(name, chapter) => setSelected({ name, chapter })}
          onClearFocus={() => {
            setFocusChar(null);
            setSelected(null);
          }}
        />
      ) : (
        <FortunePresenceGrid
          characters={characters}
          focusChar={focusChar}
          selected={selected}
          onSelect={(name, chapter) => setSelected({ name, chapter })}
        />
      )}

      {/* 人物命运档案：点一个转折 / 聚焦一个人，就在这里铺开这个人的多个命运时刻——
          每个点一条（原文 + 钤印核验），按章序，像一份小人物志（接 CBDB 人物志的厚度），
          不是只显最后点那一句。没原文的标"待核"，不编。 */}
      {profileChar && profilePoints.length > 0 && (
        <div className="mt-3 rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] overflow-hidden">
          {/* 档案抬头：谁 · 活跃于第 X–Y 章 · 共几个命运时刻 · 核验计数 */}
          <div className="px-3 py-2.5 border-b border-[var(--color-rule)] bg-[var(--color-paper)]">
            <p
              className="text-sm font-bold text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              「{profileChar.name}」命运档案
            </p>
            <p className="mt-0.5 text-xs text-[var(--color-ink-muted)]">
              原文转折在第 {profilePoints[0].chapter}–{profilePoints[profilePoints.length - 1].chapter} 章
              {" · "}
              {profilePoints.length} 个锚原文的转折
              {(() => {
                const ok = profilePoints.filter((p) => p.verified && p.evidence).length;
                return ok > 0 ? ` · ${ok} 处原文已核验` : "";
              })()}
            </p>
          </div>

          {/* 逐个命运时刻：章号 + 处境一句 + 原文 + 钤印/待核。点中的那个高亮。 */}
          <ul className="max-h-96 overflow-y-auto divide-y divide-[var(--color-rule)]">
            {profilePoints.map((p) => {
              const active = selected?.name === profileChar.name && selected.chapter === p.chapter;
              const verified = p.verified && !!p.evidence;
              return (
                <li
                  key={`prof-${p.chapter}`}
                  className="px-3 py-2.5"
                  style={active ? { background: "var(--color-seal-soft)" } : undefined}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm text-[var(--color-ink)]">
                      <span className="font-bold" style={{ fontFamily: "var(--font-display)" }}>
                        第 {p.chapter} 章
                      </span>
                      <span className="text-[var(--color-ink-muted)]"> · {p.note ?? (p.fortune > 0 ? "转折向好" : p.fortune < 0 ? "转折转坏" : "转折")}</span>
                    </p>
                    {verified ? (
                      <SealMark size={20} title="原文已核验" />
                    ) : (
                      <span className="shrink-0 text-xs text-[var(--color-ink-muted)] px-1.5 py-0.5 rounded border border-[var(--color-rule)]">
                        待核
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-sm text-[var(--color-ink)] leading-relaxed">
                    {p.evidence || "（这章没给出原文依据）"}
                  </p>
                </li>
              );
            })}
          </ul>

          <p className="px-3 py-2 text-xs text-[var(--color-ink-muted)] border-t border-[var(--color-rule)]">
            盖「鉴」印的原文已在书中逐字比对核验；标「待核」的没在书里比对命中，仅供参考。
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
