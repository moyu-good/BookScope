// ---------------------------------------------------------------------------
// RedheadDocStructure — 公文结构解读（1.6 红头文件垂直·第一块前端）
//
// 点"生成"→ 调 /api/agent/redhead/doc-structure（整份公文进上下文）→ 拆成两块：
//   头要素 —— 永远 8 条骨架（发文字号 / 文种 / 发文机关 / 主送机关 / 抄送机关 /
//     标题事由 / 成文日期 / 签发人），对照 GB/T 9704 公文格式。抽不到的标"待核"，
//     不藏起来——读者一眼看出这份缺了哪一项。
//   逐条款 —— 按出现顺序排开，每条说清：管的什么事、是硬要求还是软倡导、谁去做、
//     什么期限、依据哪份上位文件，再钉一句原文。
//
// evidence-first（跟全站一个规矩）：原文核验过的盖"鉴"印；没核上的老实标"未在原文
// 比对命中·仅供参考"；抽不到 value 标"待核"，绝不编。
// instruction_type 是封闭集四标签（硬要求 / 软倡导 / 信息告知 / 依据陈述），渲染成
// 带色小标签——它是分类不是打分，所以不画进度条、不报分数。
// scanned=false 或没真东西 → 优雅退场，不画空壳。
//
// 数字善本水准的艺术化（1.6·只动视觉不动数据）：借红头公文自己的气质——
//   头要素区做成"红头公文版头"：顶上一道朱红粗线（红头）、标题事由居中大宋体、
//     发文字号 / 成文日期分列版头两侧（公文版头的真实站位）、其余要素列在朱红细线下；
//   逐条款像"案牍批注"：朱砂序号墨钉 + 宋体事项 + 版心朱砂短线起承，原文引文走宋体留白；
//   钤印「鉴」核验过的角上盖（用现成 SealMark）。
// 克制是高级——朱砂只落在版头红线、序号墨钉、钤印、版心短线这几个语义位，绝不当大色块
// 分隔；instruction_type 彩标颜色一律不动（数据色）。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（已固定，对着写，别改后端） ----

interface HeadElement {
  field: string; // 8 个之一：发文字号 / 文种 / 发文机关 / 主送机关 / 抄送机关 / 标题事由 / 成文日期 / 签发人
  value: string; // 抽到的值；空 + status 决定显"无/不适用"还是"待核"
  evidence: string;
  verified: boolean;
  match_score: number;
  // 空值三态（task #29 根一）：present 抽到了 / absent_confirmed 确证为无（带 reason，显笃定的
  // "公开 / 无 / 不适用"）/ unverified 真没抽到（才显"待核"）。不再把笃定的"无"显成像系统故障的待核。
  status?: "present" | "absent_confirmed" | "unverified";
  reason?: string; // absent_confirmed 的依据（公开件无密级 / 此文种无签发人栏 / 平件…），小字附在后
  not_applicable?: boolean; // 与 absent_confirmed 同义的旧字段：不计入分母 / 不报缺席（向后兼容）
}

interface Clause {
  chapter: number;
  matter: string; // 这条管的事
  instruction_type: string; // 封闭集：硬要求 / 软倡导 / 信息告知 / 依据陈述
  actor: string; // 谁去做（可能空）
  deadline: string; // 期限（可能空）
  basis_ref: string; // 依据的上位文件（可能空）
  evidence: string;
  verified: boolean;
  match_score: number;
}

// 看结构（结构即信号）层 —— doc 级研判，与 head/clauses 并列（后端 structure_read）。
// 它是**研判不是核验事实**：权威刻度的"分量"判断 + 结构信号都是推断，所以视觉上区别于盖
// 「鉴」印的头要素——不盖印，标"研判"口径。后端文种判不出时整个字段缺省，FE 据此不渲染该带。
interface StructureAuthority {
  level: string; // 效力层级标签（封闭集：公布令/法规、地方性法规、指令性公文、一般公文、商洽函…）
  rank: number; // 排序权重，越小效力越高
  doc_type: string; // 引到的已抽文种
  doc_type_evidence: string;
  issuer: string; // 引到的已抽发文机关（可能空）
  issuer_evidence: string;
  agency_level?: string; // 发文机关行政层级：最高 / 高 / 中低 / 空（task #29 根二，判不出为空）
  appraisal: string; // 一句研判：多大分量 / 能管到谁 / 会否被上位覆盖（推断）
  verified_basis: boolean; // 文种+机关是否都来自已核 head（false=研判依据更薄）
}

interface StructureSignal {
  kind: string; // missing（缺身份要素=存疑）/ ordering（排序=牵头）/ weight（篇幅构成=性质）
  element: string; // 指向的具体要素 / 条款（不空说）
  note: string; // 这缺席 / 排序 / 篇幅暗示什么
}

interface StructureRead {
  authority: StructureAuthority;
  signals: StructureSignal[];
}

interface DocStructureResponse {
  head: HeadElement[];
  clauses: Clause[];
  structure_read?: StructureRead; // 可选：后端文种判不出时缺省
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface RedheadDocStructureProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  // 整合 round2 A：砍了逐条款层,给一句「逐条读这份 →」跳逐条精读。不传则不显。
  onJumpToCloseReading?: () => void;
}

// 一条头要素是否真有内容（value 非空白才算抽到了）。
function hasValue(v: string): boolean {
  return v.trim().length > 0;
}

// 确证为无（absent_confirmed）时，按字段给一个笃定的短词——不是"待核"那种像系统故障的口吻。
// 密级特殊：确证无密级 = 这是公开件，直接说"公开"最贴用户的认知；其余给"无"。
function confirmedAbsentLabel(field: string): string {
  if (field === "密级") return "公开 · 无密级";
  if (field === "紧急程度") return "平件 · 未标紧急";
  return "无";
}

// 一条头要素当前是哪一态（present / absent_confirmed / unverified）。后端给了 status 就认它；
// 没给（旧数据）就退回老逻辑：not_applicable 当 absent_confirmed，否则按有没有值分 present/unverified。
function headStatus(h: HeadElement): "present" | "absent_confirmed" | "unverified" {
  if (h.status) return h.status;
  if (hasValue(h.value)) return "present";
  if (h.not_applicable) return "absent_confirmed";
  return "unverified";
}

// 结构信号三类 → 一个短中文标签（缺席 / 排序 / 篇幅），渲染成研判带里的小角标。
// 它们都是推断，不配核验色——统一走墨色/木褐这类研判色，绝不用盖印的朱砂。
const SIGNAL_KIND_LABEL: Record<string, string> = {
  missing: "缺席",
  ordering: "排序",
  weight: "篇幅",
};

function signalKindLabel(kind: string): string {
  return SIGNAL_KIND_LABEL[kind] ?? "信号";
}

export function RedheadDocStructure({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  onJumpToCloseReading,
}: RedheadDocStructureProps) {
  const [result, setResult] = useState<DocStructureResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 头要素里某条点开看原文出处（field → 开/合）
  const [openHead, setOpenHead] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setOpenHead(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/doc-structure", {
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
      const data = (await resp.json()) as DocStructureResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // 抽到没：scanned 为真，且头要素有值的或条款里有东西
  const gotSomething =
    !!result &&
    result.scanned &&
    ((result.head ?? []).some((h) => hasValue(h.value)) ||
      (result.clauses ?? []).length > 0);

  // ---- 未生成：入口卡片 ----
  if (!result) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1 flex items-center gap-2"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {/* 红头点缀：标题前一道朱砂短脊，预告这是红头公文视图 */}
          <span
            className="h-4 w-[3px] rounded-full bg-[var(--color-seal)]"
            aria-hidden="true"
          />
          公文结构解读
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          把一份红头文件拆开看——先列发文字号、发文机关、成文日期这八项头要素，对照公文格式标准看缺没缺；再把正文逐条排开：这条管什么事、是硬要求还是软倡导、谁去做、什么期限、依据哪份上位文件，每条钉在原文。适合党政公文 / 红头文件。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读这份公文出结构中（约 1 分钟）…" : "生成公文结构解读"}
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
            label="读这份公文出结构"
            hint="整份公文喂进模型，先认头要素八项、再逐条拆正文，每一项都回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没抽到：优雅退场，不画空壳 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        <div className="flex items-center justify-between mb-3">
          <h3
            className="text-base font-bold text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            公文结构解读
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
        {loading ? (
          <RunningProcess label="读这份公文出结构" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            没抽到公文结构——这份可能不是规范的红头文件，或者格式太特殊。换一份规范公文，或稍后重试。
          </p>
        )}
      </div>
    );
  }

  const head = result.head ?? [];
  const headFilled = head.filter((h) => hasValue(h.value)).length;
  // 分母只数"本文种该有"的要素——法规本体没有发文字号/密级/签发人这些,标了 N/A 的不算分母,
  // 免得一份条例显"3/10"像抽坏了(其实适用的 4 项都抽到了 → 显"4/4")。
  const headApplicable = head.filter((h) => !h.not_applicable).length;

  // 版头意象：标题事由抽出来当版头大标题（公文版头正中那行），其余八项照常列在红线下。
  // 抽不到标题就不提，版头退成一道素净的红线 + 标签，绝不造假。
  const titleEl = head.find((h) => h.field === "标题事由" && hasValue(h.value));

  // 看结构（结构即信号）研判：后端文种判得出才有；它是**研判不是核验事实**，所以下面这条
  // "效力与结构"带视觉上区别于盖印的头要素——不盖鉴印、明标"研判"口径。
  const structureRead = result.structure_read;

  // ---- 已抽到：头要素清单 + 逐条款 ----
  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          公文结构解读
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

      {/* ── 头要素：八项骨架，做成"红头公文版头"意象 ── */}
      {/* 红头：版头顶上那道标志性的朱红粗线（公文之所以叫"红头"）。克制——只此一道。 */}
      <div
        className="h-[3px] rounded-full"
        style={{
          background:
            "linear-gradient(90deg, var(--color-seal), color-mix(in oklch, var(--color-seal) 72%, transparent))",
        }}
      />
      {/* 版头标题区：标题事由抽到了就居中提为大宋体版头标题（公文正中那行） */}
      <div className="mt-3 mb-2.5 text-center">
        {titleEl ? (
          <div className="flex items-start justify-center gap-1.5 px-2">
            <h4
              className="text-[15px] font-bold text-[var(--color-ink)] leading-snug"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {titleEl.value}
            </h4>
            {/* 标题事由核验过 → 版头角上盖一枚「鉴」印（版头求净，只盖印不展开原文） */}
            {titleEl.verified && (
              <SealMark size={16} title="标题已核验" className="mt-0.5" />
            )}
          </div>
        ) : (
          <p
            className="text-sm text-[var(--color-ink-muted)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            头要素 · 八项骨架
          </p>
        )}
        {/* 版心短线：版头标题下一道朱砂细线收束，仿公文版头分隔线（红线在心不在面） */}
        <div className="mt-2 flex items-center justify-center gap-2">
          <span className="h-px w-8 bg-[var(--color-seal)] opacity-40" />
          <span className="text-[11px] text-[var(--color-ink-muted)] tabular-nums">
            头要素 抽到 {headFilled}/{headApplicable || head.length || 8}
          </span>
          <span className="h-px w-8 bg-[var(--color-seal)] opacity-40" />
        </div>
      </div>

      <div className="rounded border border-[var(--color-rule)] bg-white overflow-hidden">
        {head.map((h, i) => {
          // 标题事由已提为版头大标题，清单里就不重复列了（提到版头的那条跳过）
          if (titleEl && h.field === "标题事由") return null;
          const filled = hasValue(h.value);
          const canOpen = filled && !!h.evidence;
          const isOpen = openHead === h.field;
          const status = headStatus(h);
          return (
            <div
              key={h.field || i}
              className="border-b border-[var(--color-rule)] last:border-b-0"
            >
              <div className="flex items-start gap-3 px-3 py-2">
                {/* 左：要素名——版心朱砂短钉起头，仿公文版头各项前的领格 */}
                <span
                  className="text-sm text-[var(--color-ink-muted)] shrink-0 w-20 relative pl-2.5"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  <span
                    className="absolute left-0 top-1.5 h-3 w-[2px] rounded-full"
                    style={{
                      background: "var(--color-seal)",
                      opacity: filled ? 0.55 : 0.2,
                    }}
                    aria-hidden="true"
                  />
                  {h.field}
                </span>
                {/* 右：值 + 核验状态 */}
                <div className="flex-1 min-w-0">
                  {filled ? (
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className="text-sm text-[var(--color-ink)]"
                        style={{ fontFamily: "var(--font-display)" }}
                      >
                        {h.value}
                      </span>
                      {h.verified ? (
                        <SealMark size={17} title="原文已核验" />
                      ) : (
                        <span className="text-[11px] text-[var(--color-ink-muted)]">
                          未在原文比对命中·仅供参考
                        </span>
                      )}
                      {canOpen && (
                        <button
                          type="button"
                          onClick={() =>
                            setOpenHead((cur) =>
                              cur === h.field ? null : h.field,
                            )
                          }
                          className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                        >
                          {isOpen ? "收起原文" : "看原文出处"}
                        </button>
                      )}
                    </div>
                  ) : status === "absent_confirmed" ? (
                    // 确证为无：笃定地说"公开 / 无 / 平件"，不是像故障的"待核"。后端给了
                    // reason（公开件无密级 / 此文种无签发人栏…）就当小字依据附在后头。
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="text-sm text-[var(--color-ink)]">
                        {confirmedAbsentLabel(h.field)}
                      </span>
                      {h.reason && (
                        <span className="text-[11px] text-[var(--color-ink-muted)]">
                          {h.reason}
                        </span>
                      )}
                    </div>
                  ) : (
                    <span className="text-sm text-[var(--color-ink-muted)] italic">
                      待核
                    </span>
                  )}
                  {/* 点开的原文出处 */}
                  {canOpen && isOpen && (
                    <p
                      className="mt-1.5 text-[13px] leading-relaxed text-[var(--color-ink)] border-l-2 border-[var(--color-seal)]/40 pl-3"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {h.evidence}
                    </p>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── 效力与结构研判带（看结构层）── */}
      {/* 区别于盖「鉴」印的头要素：这是**研判不是核验事实**——浅木褐底 + 木褐边、明标"研判"，
          绝不盖朱砂鉴印。权威刻度的"分量"判断引到已抽文种/机关；结构信号各引具体要素/条款。 */}
      {structureRead && (
        <div
          className="mt-4 rounded-md px-3.5 py-3"
          style={{
            background: "rgba(138, 107, 63, 0.06)",
            border: "1px solid rgba(138, 107, 63, 0.28)",
          }}
        >
          <div className="flex items-center gap-2 mb-1.5">
            <span
              className="text-xs font-bold"
              style={{ color: "#8a6b3f", fontFamily: "var(--font-display)" }}
            >
              效力与结构
            </span>
            {/* "研判"角标——明说这是推断不是核验事实，不配鉴印 */}
            <span
              className="text-[10px] px-1.5 py-0.5 rounded"
              style={{ color: "#8a6b3f", background: "rgba(138, 107, 63, 0.12)" }}
            >
              研判 · 非核验
            </span>
          </div>

          {/* 权威刻度：层级标签 + 一句分量研判，引到已抽文种/机关 */}
          <div className="flex items-baseline gap-2 flex-wrap">
            <span
              className="text-sm font-bold text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {structureRead.authority.level}
            </span>
            {/* 发文机关行政层级（根二）：最高 / 高层级单独标出来——这类文件分量重，
                绝不是"一般公文"。最高用朱砂强调，高用木褐，中低/空不另标（信息已在层级里）。 */}
            {(structureRead.authority.agency_level === "最高" ||
              structureRead.authority.agency_level === "高") && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded font-bold"
                style={
                  structureRead.authority.agency_level === "最高"
                    ? {
                        color: "#9a3a2e",
                        background: "rgba(154, 58, 46, 0.10)",
                      }
                    : {
                        color: "#8a6b3f",
                        background: "rgba(138, 107, 63, 0.12)",
                      }
                }
              >
                {structureRead.authority.agency_level === "最高"
                  ? "最高层级机关"
                  : "高层级机关"}
              </span>
            )}
            {structureRead.authority.doc_type && (
              <span className="text-[11px] text-[var(--color-ink-muted)]">
                据文种「{structureRead.authority.doc_type}」
                {structureRead.authority.issuer
                  ? ` + 发文机关「${structureRead.authority.issuer}」`
                  : ""}
                判
              </span>
            )}
            {/* 研判依据是否落在已核要素上——薄了如实说，不蒙混 */}
            {!structureRead.authority.verified_basis && (
              <span className="text-[10px] text-[var(--color-ink-muted)] italic">
                （文种/机关未在原文核实，依据较薄）
              </span>
            )}
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-[var(--color-ink)]">
            {structureRead.authority.appraisal}
          </p>

          {/* 结构信号：缺席/排序/篇幅，各引具体要素，标研判 */}
          {structureRead.signals.length > 0 && (
            <div className="mt-2.5 space-y-1.5">
              {structureRead.signals.map((sig, i) => (
                <div key={i} className="flex items-start gap-2">
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded shrink-0 mt-0.5"
                    style={{
                      color: "#8a6b3f",
                      background: "rgba(138, 107, 63, 0.12)",
                    }}
                  >
                    {signalKindLabel(sig.kind)}
                  </span>
                  <p className="text-[12px] leading-relaxed text-[var(--color-ink)]">
                    {sig.element && (
                      <span className="text-[var(--color-ink-muted)]">
                        {sig.element} ——{" "}
                      </span>
                    )}
                    {sig.note}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 逐条款层砍了（跟逐条精读重叠、是它的更差子集，WP-consolidation-round2 A 块）。
          公文结构专做「鸟瞰」：头要素 + 效力研判。逐条钻去逐条精读（大白话 + 术语 + 弦外
          + 纯表态识别，完整体验）。这里给一个跳过去的交叉引用。 */}
      {onJumpToCloseReading && (
        <button
          type="button"
          onClick={onJumpToCloseReading}
          className="mt-6 w-full text-left rounded border border-[var(--color-rule)] px-4 py-3 text-sm text-[var(--color-ink-muted)] hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] transition-colors"
          style={{ background: "var(--color-paper)" }}
        >
          想逐条吃透这份公文（每条给大白话 + 术语 + 弦外之意）→ 去
          <span className="text-[var(--color-seal)]"> 逐条精读</span>
        </button>
      )}

      {!loading && (
        <RunStats
          trace={trace}
          note={`头要素 ${headFilled}/${head.length || 8}`}
        />
      )}
    </div>
  );
}
