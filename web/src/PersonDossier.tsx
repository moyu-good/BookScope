// ---------------------------------------------------------------------------
// PersonDossier — 人物志(通用镜头,把一个人物的全貌收成一页)
//
// 左:全员名册(章脉派生,几百人全在、可搜、按分量排,不砍 top-N)。右:选中人的档案——
// 立场(Toulmin:综合倾向 + 争议度 + 正反两栏证据,各锚原文)+ 处境(锚原文的转折)。
//
// 两条架构约束(作者 2026-07-08）：
//   · 全员出来——名册从章脉来(整本读一次就有),几百人都在册、可点;
//   · 算法按需精确——点开某人才现跑他的精确分析(查询时代理)。此预览对主要人物预置了数据,
//     其余点开显"现算"占位(真 app 里就是调 /agent/character-stance 等现跑)。
//
// 通用:只认 {roster, stance, arc} 三份数据,跟书无关。真 app 里 roster 来自关系图节点、
// stance/arc 点谁现调端点谁。此组件是装配层,不重造 ①④⑧(关系图/处境/立场各自的组件仍在)。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { SealMark } from "./SealMark";
import { StanceQuadrant, type QuadPoint } from "./StanceQuadrant";

export interface DossierRosterEntry {
  name: string;
  chapters?: number; // 出场章数（章脉派生有；live 从关系图节点来时可缺）
  hasStance: boolean;
}
export interface DossierEvid {
  原文: string;
  说明: string;
  verified?: boolean;
}
export interface DossierStance {
  name: string;
  faction: string;
  net: number;
  dispute: number;
  dispute_reason?: string;
  pro: DossierEvid[];
  con: DossierEvid[];
}
export interface DossierArcPoint {
  chapter: number;
  fortune: number;
  evidence: string;
  verified: boolean;
}
export interface DossierArc {
  name: string;
  points: DossierArcPoint[];
}

interface Props {
  roster: DossierRosterEntry[];
  stance: DossierStance[];
  arc: DossierArc[];
  axisPos?: string; // 立场轴正端标签(如 尊汉扶主)
  axisNeg?: string;
  // 点名册里的人时回调（真 app 用来现跑他的精确分析；fixture 预览不传）
  onSelectPerson?: (name: string) => void;
  // 正在现跑分析的那个人名（真 app 传，显"分析中"）
  loadingName?: string | null;
  // 立场格局主视图：前端一次批量定位好的点（net + dispute 粗定位）；空 = 不画象限。
  quadPoints?: QuadPoint[];
  // 批量定位还在跑（象限位置显 loading 占位）。
  quadLoading?: boolean;
  // 处境弧线还在取（没立场轴的书，靠它分清是"有处境可点"还是"这类书不适配这个镜头"）。
  arcLoading?: boolean;
}

const FACTION_COLOR: Record<string, string> = {
  魏: "#3E6E9A",
  蜀: "#a8322a",
  吴: "#2E8B6E",
};

// v1 不做派系：全员归一组、一个颜色（象限只用 net×戏份两维，颜色不承载信息）。
const QUAD_GROUP_COLOR: Record<string, string> = { 人物: "var(--color-seal)" };

export function PersonDossier({
  roster,
  stance,
  arc,
  axisPos = "尊汉扶主",
  axisNeg = "篡逆自立",
  onSelectPerson,
  loadingName = null,
  quadPoints = [],
  quadLoading = false,
  arcLoading = false,
}: Props) {
  // 有立场轴才画格局；没轴（工具书 / 诗集，suggest 返空）优雅退，名册照常。
  const stanceEnabled = Boolean(axisPos && axisNeg);
  const stanceByName = useMemo(
    () => new Map(stance.map((s) => [s.name, s])),
    [stance],
  );
  const arcByName = useMemo(() => new Map(arc.map((a) => [a.name, a])), [arc]);
  const [sel, setSel] = useState<string>(
    () => roster.find((r) => r.hasStance)?.name ?? roster[0]?.name ?? "",
  );
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim();
    return q ? roster.filter((r) => r.name.includes(q)) : roster;
  }, [roster, query]);

  const s = stanceByName.get(sel);
  const a = arcByName.get(sel);
  const selEntry = roster.find((r) => r.name === sel);
  const factionColor = (f?: string) => (f ? FACTION_COLOR[f] ?? "#8a7f6a" : "#8a7f6a");

  // 有没有任何可展开的处境：没立场轴时靠它分流——有处境=点开看起落；一个都没有=这类书不适配这个镜头。
  const hasAnyArc = useMemo(
    () => arc.some((x) => x.points.some((p) => p.evidence?.trim())),
    [arc],
  );
  const hasArcForSel = Boolean(a && a.points.some((p) => p.evidence?.trim()));
  // 既没立场轴、也没任何人有处境，且不在取数中 = 理论 / 论述类，这个镜头没东西可给，整块别摆。
  const nothingToShow = !stanceEnabled && !arcLoading && !hasAnyArc;

  return (
    <div className="space-y-4">
      {/* 立场格局主视图（大、在最上）：全员一口气打在立场轴上，一次通读的粗定位 */}
      {stanceEnabled ? (
        quadPoints.length > 0 ? (
          <div>
            <StanceQuadrant
              points={quadPoints}
              axisX={{ label: "戏份", low: "配角", high: "主角" }}
              axisY={{ label: "立场", low: axisNeg, high: axisPos }}
              groupColor={QUAD_GROUP_COLOR}
              selected={sel}
              onSelect={(name) => {
                if (name) {
                  setSel(name);
                  onSelectPerson?.(name);
                }
              }}
              showDetail={false}
            />
            <p className="mt-1.5 px-1 text-xs text-[var(--color-ink-muted)] leading-relaxed">
              轴上是通读全书的一次
              <span className="font-semibold text-[var(--color-ink)]">粗定位</span>
              ：左右看戏份，上下看立场倾向。点开某个人，才正反两面取原文、看他真正的争议度；戏份轻的在下面名册里搜。
            </p>
          </div>
        ) : quadLoading ? (
          <div className="rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-6 text-center text-sm text-[var(--color-ink-muted)]">
            正在把主要人物一次定位到立场格局上，通读全书约二十秒…
          </div>
        ) : null
      ) : arcLoading ? (
        <div className="rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-6 text-center text-sm text-[var(--color-ink-muted)]">
          正在把主要人物的处境理一遍，看有没有可展开的轨迹…
        </div>
      ) : hasAnyArc ? (
        <div className="rounded border border-dashed border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-4 text-sm text-[var(--color-ink-muted)] leading-relaxed">
          这本书没有明显的立场对立，就不画立场格局了。下面点开有处境记录的人，看他的起落，每条都取自原文。
        </div>
      ) : (
        <div className="rounded border border-dashed border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-5 text-sm text-[var(--color-ink-muted)] leading-relaxed">
          <p className="mb-1.5">
            这本书更像理论 / 论述类。立场格局看的是人物的阵营立场和命运起落，这类书里出现的人，多是被引用的学者或举例提到的人物，没有这样的轨迹，就不展开了。
          </p>
          <p>想看谁被反复提到、彼此怎么关联，去「人物关系图」。</p>
        </div>
      )}

      {/* 名册（次要）+ 选中人详情；理论 / 论述类没东西可点就整块不出（上面已给说明） */}
      {!nothingToShow && (
      <div className="rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] overflow-hidden">
      <div className="flex flex-col md:flex-row" style={{ minHeight: 360 }}>
        {/* 左:全员名册 */}
        <div
          className="md:w-56 shrink-0 border-b md:border-b-0 md:border-r border-[var(--color-rule)] bg-[var(--color-paper)] flex flex-col"
          style={{ maxHeight: 520 }}
        >
          <div className="p-2 border-b border-[var(--color-rule)]">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`搜人名（全书 ${roster.length} 人）`}
              className="w-full text-sm px-2.5 py-1.5 rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] text-[var(--color-ink)] focus:border-[var(--color-seal)] outline-none"
            />
          </div>
          <ul className="overflow-y-auto flex-1">
            {filtered.map((r) => {
              const on = r.name === sel;
              return (
                <li key={r.name}>
                  <button
                    type="button"
                    onClick={() => {
                      setSel(r.name);
                      onSelectPerson?.(r.name);
                    }}
                    className="w-full text-left px-3 py-1.5 flex items-center justify-between gap-2 border-b border-[var(--color-rule)] last:border-b-0 hover:bg-[var(--color-seal-soft)] transition-colors"
                    style={on ? { background: "var(--color-seal-soft)" } : undefined}
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <span
                        className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                        style={{ background: r.hasStance ? "var(--color-seal)" : "var(--color-rule)" }}
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
                    {r.chapters ? (
                      <span className="text-xs text-[var(--color-ink-muted)] tabular-nums shrink-0">
                        {r.chapters} 章
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        {/* 右:选中人档案 */}
        <div className="flex-1 p-4 overflow-y-auto" style={{ maxHeight: 520 }}>
          <div className="flex items-baseline gap-3 flex-wrap">
            <span
              className="text-2xl font-bold text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {sel}
            </span>
            {s && s.faction && (
              <span
                className="text-sm px-2.5 py-0.5 rounded"
                style={{ border: `0.5px solid ${factionColor(s.faction)}`, color: factionColor(s.faction) }}
              >
                {s.faction}
              </span>
            )}
            {selEntry?.chapters ? (
              <span className="text-xs text-[var(--color-ink-muted)]">出场 {selEntry.chapters} 章</span>
            ) : null}
          </div>

          {stanceEnabled && !s &&
            (loadingName === sel ? (
              <div className="mt-4 rounded border border-[var(--color-rule)] p-4 text-sm text-[var(--color-ink-muted)]">
                正在分析「{sel}」的立场：通读全书，正反两面找证据，每条都取自原文，约 15 秒…
              </div>
            ) : (
              <div className="mt-4 rounded border border-dashed border-[var(--color-rule)] p-4 text-sm text-[var(--color-ink-muted)] leading-relaxed">
                {onSelectPerson ? (
                  <>
                    这个人在名单里。要看他的立场，点一下马上分析。
                    <button
                      type="button"
                      onClick={() => onSelectPerson(sel)}
                      className="ml-1 px-2.5 py-0.5 rounded text-[var(--color-paper)]"
                      style={{ background: "var(--color-seal)", fontFamily: "var(--font-display)" }}
                    >
                      分析他的立场
                    </button>
                  </>
                ) : (
                  "这个人在名单里（全书的人都在）。他的立场和处境，点开才分析，每条都取自原文。这个预览只给主要人物备了数据。"
                )}
              </div>
            ))}

          {/* 立场（Toulmin：倾向 + 争议度 + 正反两栏） */}
          {s && (
            <div className="mt-4">
              <div className="text-sm font-medium text-[var(--color-seal)] mb-1.5">
                立场 · {axisPos} ↔ {axisNeg}
              </div>
              <p className="text-sm text-[var(--color-ink)] mb-1">
                综合倾向{" "}
                <span className="font-bold">
                  {s.net > 1 ? `偏${axisPos}` : s.net < -1 ? `偏${axisNeg}` : "中立"}（{s.net > 0 ? `+${s.net}` : s.net}）
                </span>
                <span className="text-[var(--color-ink-muted)]">
                  {s.dispute >= 3 ? ` · 争议度 ${s.dispute}（别当定论）` : ` · 争议度 ${s.dispute}`}
                </span>
              </p>
              {s.dispute_reason && (
                <p className="text-xs text-[var(--color-ink-muted)] mb-2 leading-relaxed">{s.dispute_reason}</p>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <EvidCol title={`${axisPos}的证据`} tint="var(--color-seal)" items={s.pro} />
                <EvidCol title={`${axisNeg}的证据`} tint="var(--color-ink)" items={s.con} />
              </div>
            </div>
          )}

          {/* 处境（锚原文的转折） */}
          {a && a.points.filter((p) => p.evidence?.trim()).length > 0 && (
            <div className="mt-5">
              <div className="text-sm font-medium text-[var(--color-seal)] mb-1.5">处境转折 · 每条都取自原文</div>
              <ul className="space-y-1.5">
                {a.points
                  .filter((p) => p.evidence?.trim())
                  .map((p) => (
                    <li key={p.chapter} className="text-sm text-[var(--color-ink)] leading-relaxed flex gap-2">
                      <span className="shrink-0 text-[var(--color-ink-muted)] tabular-nums">第{p.chapter}章</span>
                      <span
                        className="shrink-0"
                        style={{ color: p.fortune > 0 ? "var(--color-seal)" : "var(--color-ink-muted)" }}
                      >
                        {p.fortune > 0 ? "↑" : p.fortune < 0 ? "↓" : "·"}
                      </span>
                      <span className="min-w-0">
                        {p.verified ? <SealMark size={15} title="原文已核验" /> : null} {p.evidence}
                      </span>
                    </li>
                  ))}
              </ul>
            </div>
          )}

          {/* 没立场轴、这个人也没处境轨迹：老实说没有，别留空白 */}
          {!stanceEnabled &&
            !hasArcForSel &&
            (arcLoading ? (
              <div className="mt-4 rounded border border-[var(--color-rule)] p-4 text-sm text-[var(--color-ink-muted)]">
                正在整理「{sel}」的处境…
              </div>
            ) : (
              <div className="mt-4 rounded border border-dashed border-[var(--color-rule)] p-4 text-sm text-[var(--color-ink-muted)] leading-relaxed">
                这本书没有立场对立的格局，「{sel}」在正文里也没有留下处境起落的轨迹。理论 / 论述类里，很多人是被引用或举例提到的。
              </div>
            ))}
        </div>
      </div>
      <p className="px-3 py-2 text-xs text-[var(--color-ink-muted)] border-t border-[var(--color-rule)]">
        左边是全书 {roster.length} 个人的完整名单，能搜、不删减；右边每个人的立场和处境都取自原文，有争议的把正反两面都摆出来，不替你下定论。点开谁，才分析谁。
      </p>
      </div>
      )}
    </div>
  );
}

function EvidCol({ title, tint, items }: { title: string; tint: string; items: DossierEvid[] }) {
  return (
    <div>
      <div className="text-xs font-medium mb-1" style={{ color: tint }}>
        {title}（{items.length}）
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-[var(--color-ink-muted)]">原文里没找到这方证据。</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((e, i) => (
            <li key={i} className="text-sm text-[var(--color-ink)] leading-relaxed">
              {e.verified ? (
                <SealMark size={15} title="原文已核验" />
              ) : (
                <span className="text-[10px] text-[var(--color-ink-muted)] px-1 rounded border border-[var(--color-rule)] mr-1">待核</span>
              )}{" "}
              {e.原文}
              {e.说明 && <span className="text-xs text-[var(--color-ink-muted)]">（{e.说明}）</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
