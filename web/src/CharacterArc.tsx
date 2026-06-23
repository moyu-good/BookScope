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

  async function load() {
    setLoading(true);
    setError(null);
    setSelected(null);
    setFocusChar(null);
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

      {/* 看全部 / 单个角色 */}
      <div className="flex flex-wrap items-center gap-2 mb-2 text-xs">
        <button
          type="button"
          onClick={() => setFocusChar(null)}
          className={[
            "px-2 py-0.5 rounded border transition-colors",
            focusChar === null
              ? "border-[var(--color-seal)] text-[var(--color-seal)]"
              : "border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:border-[var(--color-seal)]",
          ].join(" ")}
        >
          看全部
        </button>
        {characters.map((c) => (
          <button
            key={c.name}
            type="button"
            onClick={() => setFocusChar((cur) => (cur === c.name ? null : c.name))}
            className={[
              "px-2 py-0.5 rounded border transition-colors flex items-center gap-1",
              focusChar === c.name
                ? "border-[var(--color-seal)] text-[var(--color-seal)]"
                : "border-[var(--color-rule)] text-[var(--color-ink)] hover:border-[var(--color-seal)]",
            ].join(" ")}
          >
            <span
              className="inline-block w-2.5 h-2.5 rounded-sm"
              style={{ background: charColor.get(c.name) }}
              aria-hidden
            />
            {c.name}
          </button>
        ))}
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
