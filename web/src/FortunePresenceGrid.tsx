// ---------------------------------------------------------------------------
// FortunePresenceGrid — 处境在场热力（CharacterArc 的第二个品读视图）
//
// 跟命运线（FateLineArc）用同一份 character-arc 数据，只换画法：章 × 人的格子墙。
//   · 行 = 主要角色（按戏份降序），列 = 章节推进；
//   · 格子点亮 = 这章他在场；颜色 = 这章处境（得势朱砂 / 落难墨 / 平淡灰）；深浅 = 戏份轻重。
//   · 一行扫下来 = 这个人一生的冷暖起落 + 何时在场何时退场，不是打卡出勤表。
//   · 点格子 = 看那章原文（跟命运线共用下面那份「命运档案」面板）。
//
// 为什么不是又一张热力矩阵：格子编码的是「处境」这个有意义的维度（他过得好不好），
// 不是「第几章出现」这种机械事实。这一版按作者「④ 信息再变一下：从在不在场→过得怎样」来。
//
// 通用：任何有人物、有 character-arc 的书都能开（小说 / 网文 / 史书），不是史书专属。
// 诚实呈现：fortune 是模型逐章判读、绝对值会抖，所以只分三档色（得势 / 落难 / 平），
// 不印精确分；核不过原文的点在档案里标「待核」（那份面板已处理）。
// ---------------------------------------------------------------------------

import { useMemo } from "react";
import type { ArcCharacter, ArcPoint } from "./HuaniaoArc";

interface FortunePresenceGridProps {
  characters: ArcCharacter[];
  focusChar: string | null;
  selected: { name: string; chapter: number } | null;
  onSelect: (name: string, chapter: number) => void;
}

// 默认铺戏份最重的前 N 行；聚焦某人时把他单独拎到最前
const MAX_ROWS = 14;

// 有原文依据 = 这一章"判过处境"。没原文的只算"在场"，不硬塞处境色、不编、不塞待核。
function grounded(pt: ArcPoint | undefined): boolean {
  return !!(pt && pt.evidence && pt.evidence.trim());
}

// 一格的底色:
//   · 不在场 → null(透明,只留网格线);
//   · 在场但没判过处境 → 中性淡底(只表在场,深浅按戏份);
//   · 锚了原文的转折 → 按方向染色(向好朱 / 转坏墨)、压深,跳出在场底。
function cellBg(
  pt: ArcPoint | undefined,
): { background: string; opacity: number; grounded: boolean } | null {
  if (!pt || pt.presence <= 0) return null;
  if (!grounded(pt)) {
    return {
      background: "var(--color-ink-muted)",
      opacity: 0.16 + Math.min(0.24, (pt.presence / 10) * 0.24),
      grounded: false,
    };
  }
  const f = pt.fortune;
  const color = f > 0 ? "var(--color-seal)" : f < 0 ? "var(--color-ink)" : "var(--color-ink-muted)";
  return { background: color, opacity: 0.92, grounded: true };
}

export function FortunePresenceGrid({
  characters,
  focusChar,
  selected,
  onSelect,
}: FortunePresenceGridProps) {
  // 章节全域：所有角色所有点的最小—最大章
  const { minCh, maxCh } = useMemo(() => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const c of characters) {
      for (const p of c.points) {
        if (p.chapter < lo) lo = p.chapter;
        if (p.chapter > hi) hi = p.chapter;
      }
    }
    if (!Number.isFinite(lo)) return { minCh: 1, maxCh: 1 };
    return { minCh: lo, maxCh: hi };
  }, [characters]);

  const chapters = useMemo(() => {
    const arr: number[] = [];
    for (let c = minCh; c <= maxCh; c++) arr.push(c);
    return arr;
  }, [minCh, maxCh]);

  // 行：按戏份（各章 presence 之和）降序取前 MAX_ROWS；聚焦某人时把他置顶保证可见
  const rows = useMemo(() => {
    const ranked = [...characters]
      .map((c) => ({
        char: c,
        weight: c.points.reduce((s, p) => s + p.presence, 0),
        byCh: new Map(c.points.map((p) => [p.chapter, p])),
      }))
      .sort((a, b) => b.weight - a.weight);
    let top = ranked.slice(0, MAX_ROWS);
    if (focusChar && !top.some((r) => r.char.name === focusChar)) {
      const f = ranked.find((r) => r.char.name === focusChar);
      if (f) top = [f, ...top.slice(0, MAX_ROWS - 1)];
    }
    if (focusChar) {
      top = [...top].sort((a, b) =>
        a.char.name === focusChar ? -1 : b.char.name === focusChar ? 1 : 0,
      );
    }
    return top;
  }, [characters, focusChar]);

  // 顶栏章号刻度：均匀取 ~6 个，别把每章号都堆上去
  const ticks = useMemo(() => {
    const n = chapters.length;
    if (n <= 1) return chapters;
    const step = Math.max(1, Math.round(n / 6));
    const out: number[] = [];
    for (let i = 0; i < n; i += step) out.push(chapters[i]);
    if (out[out.length - 1] !== chapters[n - 1]) out.push(chapters[n - 1]);
    return out;
  }, [chapters]);

  const LABEL_W = 68;

  return (
    <div className="rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-3">
      {/* 图例 */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mb-2 text-xs text-[var(--color-ink-muted)]">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ background: "var(--color-seal)" }} />
          转折向好
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ background: "var(--color-ink)" }} />
          转折转坏
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ background: "var(--color-ink-muted)", opacity: 0.3 }} />
          在场
        </span>
        <span>空格＝未登场</span>
        <span>朱/墨格＝锚了原文的转折</span>
      </div>

      {/* 顶栏章号刻度 */}
      <div className="flex items-end mb-1" style={{ paddingLeft: LABEL_W }}>
        <div className="relative flex-1 h-4">
          {ticks.map((c) => {
            const left = chapters.length <= 1 ? 0 : ((c - minCh) / (maxCh - minCh)) * 100;
            return (
              <span
                key={`tick-${c}`}
                className="absolute text-[10px] text-[var(--color-ink-muted)] tabular-nums -translate-x-1/2"
                style={{ left: `${left}%` }}
              >
                {c}
              </span>
            );
          })}
        </div>
      </div>

      {/* 行：每个角色一条，格子墙 */}
      <div className="space-y-1">
        {rows.map(({ char, byCh }) => {
          const on = focusChar === char.name;
          return (
            <div key={char.name} className="flex items-center gap-1">
              <span
                className="shrink-0 text-xs truncate text-right"
                style={{
                  width: LABEL_W,
                  fontFamily: "var(--font-display)",
                  color: on ? "var(--color-seal)" : "var(--color-ink)",
                  fontWeight: on ? 700 : 400,
                }}
                title={char.name}
              >
                {char.name}
              </span>
              <div className="flex-1 flex gap-px">
                {chapters.map((c) => {
                  const pt = byCh.get(c);
                  const bg = cellBg(pt);
                  const isSel = selected?.name === char.name && selected.chapter === c;
                  return (
                    <button
                      key={`${char.name}-${c}`}
                      type="button"
                      disabled={!bg?.grounded}
                      onClick={() => bg?.grounded && onSelect(char.name, c)}
                      title={
                        pt && pt.presence > 0
                          ? bg?.grounded
                            ? `${char.name} · 第${c}章 · ${(pt.evidence || "").slice(0, 24)}`
                            : `${char.name} · 第${c}章 · 在场`
                          : undefined
                      }
                      className="flex-1 rounded-[1px]"
                      style={{
                        height: 16,
                        minWidth: 3,
                        background: bg?.background ?? "var(--color-paper)",
                        opacity: bg?.opacity ?? 1,
                        cursor: bg?.grounded ? "pointer" : "default",
                        outline: isSel
                          ? "1.5px solid var(--color-seal)"
                          : bg?.grounded
                            ? "1px solid var(--color-paper-raised)"
                            : "none",
                        outlineOffset: isSel ? "1px" : undefined,
                        boxShadow: bg ? "none" : "inset 0 0 0 0.5px var(--color-rule)",
                      }}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
        一行＝一个人：淡底＝在场（章脉逐章、真），朱/墨格＝锚了原文的处境转折（可点看那句原文）。中间没判过的不编、不上暧昧档词。
      </p>
    </div>
  );
}
