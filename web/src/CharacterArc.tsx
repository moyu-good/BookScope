// ---------------------------------------------------------------------------
// CharacterArc — 戏份 / 人物弧线曲线（WP-character-arc-curves，probe GO）
//
// 点生成 → 调 /api/agent/character-arc（整本进上下文给主要角色逐章抽戏份 + 处境）→
// 自写 SVG，同一道章节横轴叠两层：
//   · 处境弧线（fortune -5..+5）：每个角色一条折线，零轴居中，上=得势、下=落难。
//     不做平滑插值——渐变写成平滑爬升、硬扳写成直角拐弯，如实显现（呼应 exp-010 判定）。
//   · 戏份密度（presence 0-10）：横轴下方每角色一条底色带，色深 = 该章这个角色戏份多重；
//     一眼看出谁何时主导、谁中途隐没又回来。
// 可切换"看全部 / 看单个角色"。点折线上的起伏点看原文 + 是渐变还是硬扳。
// evidence-first：verified=false 的点淡化、不当确定结论画。CPU-only 不引重图库；
// 入场动画用 rAF 一次性扫过、冷却即停（同 CharacterFlow 防 CPU 空转）。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";

interface ArcPoint {
  chapter: number;
  presence: number; // 0-10
  fortune: number; // -5..+5
  evidence: string;
  verified: boolean;
  match_score: number;
}

interface ArcCharacter {
  name: string;
  points: ArcPoint[];
}

interface CharacterArcProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

const W = 760;
const PAD_LEFT = 30;
const PAD_RIGHT = 16;
const PAD_TOP = 16;
const ARC_H = 150; // 处境弧线主图区高
const GAP = 12;
const BAND_H = 13; // 单条戏份密度带高

// 角色配色取一组克制的古籍色（不刺眼、可区分），循环用
const ARC_PALETTE = [
  "#9a5b52",
  "#5f7a6b",
  "#8c6b4f",
  "#6b6f8c",
  "#8a7a4a",
  "#5b7d8a",
];

// 选中的起伏点：唯一标识 = 角色名 + 章号
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
}: CharacterArcProps) {
  const [characters, setCharacters] = useState<ArcCharacter[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [selected, setSelected] = useState<SelectedPoint | null>(null);
  // null = 看全部；具体角色名 = 只看这一个（弧线 + 戏份带都聚焦它）
  const [focusChar, setFocusChar] = useState<string | null>(null);

  // 入场动画：0→1 一次性扫过，冷却即停（rAF，硬帧上限）
  const [reveal, setReveal] = useState(0);
  const rafRef = useRef<number | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setSelected(null);
    setFocusChar(null);
    setReveal(0);
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

  // 入场动画：弧线从左扫到右（reveal 0→1），冷却即停。带硬帧上限防 CPU 空转。
  useEffect(() => {
    if (!characters) return;
    let frames = 0;
    const MAX_FRAMES = 60; // ~1s @60fps 后必停
    const step = () => {
      frames += 1;
      setReveal((r) => {
        const next = Math.min(1, r + 0.035);
        return next;
      });
      if (frames < MAX_FRAMES) {
        rafRef.current = requestAnimationFrame(step);
      }
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [characters]);

  // 角色名 → 固定颜色（按出场顺序分配）
  const charColor = useMemo(() => {
    const map = new Map<string, string>();
    if (!characters) return map;
    characters.forEach((c, i) => {
      map.set(c.name, ARC_PALETTE[i % ARC_PALETTE.length]);
    });
    return map;
  }, [characters]);

  // 全书章节范围（横轴）——取所有角色所有点的 min/max 章号
  const chapterDomain = useMemo(() => {
    if (!characters) return { min: 1, max: 1 };
    let min = Infinity;
    let max = -Infinity;
    for (const c of characters) {
      for (const p of c.points) {
        if (p.chapter < min) min = p.chapter;
        if (p.chapter > max) max = p.chapter;
      }
    }
    if (!isFinite(min)) return { min: 1, max: 1 };
    return { min, max: Math.max(max, min) };
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
          给主要角色画两条曲线——谁何时主导这本书（戏份密度）、谁过得顺不顺（处境升降）。渐变写成平滑爬升、硬扳写成直角拐弯，点拐点看原文。
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
          <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
            填了 API key 才能生成。
          </p>
        )}
        {loading && (
          <RunningProcess
            label="读全书出人物弧线"
            hint="整本书喂进模型，给主要角色逐章判戏份与处境——每个起伏点都回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  // 横轴：章号 → x
  const innerW = W - PAD_LEFT - PAD_RIGHT;
  const span = Math.max(1, chapterDomain.max - chapterDomain.min);
  const xAt = (chapter: number) =>
    PAD_LEFT + ((chapter - chapterDomain.min) / span) * innerW;

  // 处境弧线区：零轴居中，±5 映射到 ±(ARC_H/2)
  const arcBottom = PAD_TOP + ARC_H;
  const zeroY = PAD_TOP + ARC_H / 2;
  const fortuneY = (f: number) =>
    zeroY - (Math.max(-5, Math.min(5, f)) / 5) * (ARC_H / 2);

  // 看全部 / 聚焦单个
  const shown = focusChar
    ? characters.filter((c) => c.name === focusChar)
    : characters;

  // 戏份密度带区起点（在弧线区下方）
  const bandsTop = arcBottom + GAP + 14;
  const bandH = BAND_H;
  const bandGap = 4;
  const totalH =
    bandsTop + shown.length * (bandH + bandGap) + 18;

  const selChar = selected
    ? characters.find((c) => c.name === selected.name)
    : null;
  const selPoint = selChar
    ? selChar.points.find((p) => p.chapter === selected!.chapter)
    : null;

  // 折线点串：只到 reveal 进度处的章号（入场从左扫到右）
  const revealCutoff =
    chapterDomain.min + reveal * (chapterDomain.max - chapterDomain.min);

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
        上图折线 = 处境升降（零轴上方得势、下方落难，平滑爬升=渐变、直角拐弯=硬扳）；下方色带 = 戏份密度（越深戏越重，淡=这章基本没出场）。淡化的点 = 原文没核验上。点折线上的点看依据。
      </p>

      {/* 角色切换：看全部 / 单个 */}
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
            onClick={() =>
              setFocusChar((cur) => (cur === c.name ? null : c.name))
            }
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

      <svg
        viewBox={`0 0 ${W} ${totalH}`}
        className="w-full border border-[var(--color-rule)] rounded bg-white"
      >
        {/* 处境参考横线 + 零轴 */}
        {[-4, -2, 2, 4].map((lvl) => (
          <line
            key={`g-${lvl}`}
            x1={PAD_LEFT}
            y1={fortuneY(lvl)}
            x2={W - PAD_RIGHT}
            y2={fortuneY(lvl)}
            stroke="var(--color-rule)"
            strokeWidth={0.5}
          />
        ))}
        <line
          x1={PAD_LEFT}
          y1={zeroY}
          x2={W - PAD_RIGHT}
          y2={zeroY}
          stroke="var(--color-ink-muted)"
          strokeWidth={0.7}
          strokeDasharray="2 2"
          opacity={0.6}
        />
        {/* 顺/逆方向标 */}
        <text x={4} y={PAD_TOP + 8} fontSize={8} fill="var(--color-ink-muted)">
          顺
        </text>
        <text x={4} y={arcBottom - 2} fontSize={8} fill="var(--color-ink-muted)">
          逆
        </text>

        {/* 每个角色一条处境折线（不平滑：硬扳=直角拐弯如实显现） */}
        {shown.map((c) => {
          const color = charColor.get(c.name) ?? "var(--color-ink)";
          const visible = c.points.filter((p) => p.chapter <= revealCutoff + 0.5);
          const pts = visible.map((p) => `${xAt(p.chapter)},${fortuneY(p.fortune)}`).join(" ");
          const dim = focusChar && focusChar !== c.name;
          return (
            <g key={`arc-${c.name}`} opacity={dim ? 0.15 : 1}>
              {visible.length >= 2 && (
                <polyline
                  points={pts}
                  fill="none"
                  stroke={color}
                  strokeWidth={focusChar === c.name ? 2.2 : 1.6}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  opacity={0.85}
                />
              )}
              {visible.map((p) => {
                const active =
                  selected?.name === c.name && selected.chapter === p.chapter;
                return (
                  <circle
                    key={`pt-${c.name}-${p.chapter}`}
                    cx={xAt(p.chapter)}
                    cy={fortuneY(p.fortune)}
                    r={active ? 4 : 2.4}
                    fill={p.verified ? color : "var(--color-paper)"}
                    stroke={color}
                    strokeWidth={p.verified ? 0 : 1.2}
                    opacity={p.verified ? 0.95 : 0.5}
                    style={{ cursor: "pointer" }}
                    onClick={() =>
                      setSelected({ name: c.name, chapter: p.chapter })
                    }
                  />
                );
              })}
            </g>
          );
        })}

        {/* 戏份密度带：横轴下方每角色一条，色深 = presence */}
        {shown.map((c, row) => {
          const color = charColor.get(c.name) ?? "var(--color-ink)";
          const y = bandsTop + row * (bandH + bandGap);
          const byChapter = new Map(c.points.map((p) => [p.chapter, p]));
          const dim = focusChar && focusChar !== c.name;
          return (
            <g key={`band-${c.name}`} opacity={dim ? 0.2 : 1}>
              <text
                x={PAD_LEFT - 4}
                y={y + bandH - 3}
                textAnchor="end"
                fontSize={9}
                fill="var(--color-ink)"
              >
                {c.name.length > 5 ? c.name.slice(0, 5) + "…" : c.name}
              </text>
              {/* 逐章格：每章一格，色深按 presence；这章没点 = 极淡（没出场） */}
              {Array.from(
                { length: chapterDomain.max - chapterDomain.min + 1 },
                (_, k) => {
                  const chapter = chapterDomain.min + k;
                  if (chapter > revealCutoff + 0.5) return null;
                  const p = byChapter.get(chapter);
                  const presence = p ? p.presence : 0;
                  const cw = innerW / (chapterDomain.max - chapterDomain.min + 1);
                  const cx = PAD_LEFT + k * cw;
                  const o = p
                    ? (p.verified ? 0.18 + (presence / 10) * 0.62 : 0.1)
                    : 0.04;
                  return (
                    <rect
                      key={`cell-${c.name}-${chapter}`}
                      x={cx}
                      y={y}
                      width={Math.max(1, cw - 0.5)}
                      height={bandH}
                      fill={color}
                      opacity={o}
                      style={{ cursor: p ? "pointer" : "default" }}
                      onClick={
                        p
                          ? () => setSelected({ name: c.name, chapter })
                          : undefined
                      }
                    />
                  );
                },
              )}
            </g>
          );
        })}

        {/* 章号刻度（隔几章标一个，标在戏份带下方） */}
        {Array.from(
          { length: chapterDomain.max - chapterDomain.min + 1 },
          (_, k) => {
            const chapter = chapterDomain.min + k;
            const cnt = chapterDomain.max - chapterDomain.min + 1;
            if (!(cnt <= 20 || k % 5 === 0)) return null;
            const cw = innerW / cnt;
            return (
              <text
                key={`x-${chapter}`}
                x={PAD_LEFT + k * cw + cw / 2}
                y={totalH - 5}
                textAnchor="middle"
                fontSize={8}
                fill="var(--color-ink-muted)"
              >
                {chapter}
              </text>
            );
          },
        )}
      </svg>

      {selPoint && selChar && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            「{selChar.name}」· 第 {selPoint.chapter} 章 · 戏份 {selPoint.presence}
            /10 · 处境{" "}
            {selPoint.fortune > 0 ? "↑" : selPoint.fortune < 0 ? "↓" : "→"}
            {selPoint.fortune}
          </p>
          <p className="mt-1 text-sm text-[var(--color-ink)] leading-relaxed">
            {selPoint.evidence || "（这章没给出原文依据）"}
          </p>
          <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
            {selPoint.verified
              ? "原文已核验"
              : "原文未在书中比对命中——这点仅供参考"}
          </p>
        </div>
      )}

      {loading ? (
        <RunningProcess label="重出人物弧线" />
      ) : (
        <RunStats
          trace={trace}
          note={`${characters.length} 个主要角色`}
        />
      )}
    </div>
  );
}
