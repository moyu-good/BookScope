// RedheadDocPanorama —— 单份公文全景镜头
// ---------------------------------------------------------------------------
// 目的：读懂一份红头文件不用在六七个 tab 间来回跳。把吃「单份 sessionId」的几个
// 公文分析视图拼成一个连续镜头：顶上一条吸顶锚点导航，下面每个视图一段，点导航
// 跳到那段。
//
// 整合了哪几个视图（都吃单份 sessionId，跟 App 里现挂的完全一致）：
//   1. 公文结构    RedheadDocStructure   （App mode="redhead"）
//   2. 逐条精读    RedheadCloseReading   （App mode="redhead_plain"，已含大白话 + 术语）
//   3. 利害与风向  RedheadStakes         （App mode="redhead_stakes"）
//   4. 要点提取    RedheadHardFacts      （App mode="redhead_hardfacts"，内含时序视图）
//   5. 办事清单    RedheadActionList     （App mode="redhead_actions"）
//   6. 规范性自检  RedheadFormatCheck    （App mode="redhead_formatcheck"）
//
// 排除了谁、为什么：
//   - 依据链网 / 政策演变 / 上下级一致性（RedheadDependencyGraph / RedheadPolicyEvolution
//     / RedheadLevelConsistency）吃的是 bookSessionIds（一卷宗多份），是跨文件层，跟
//     单份正交，不进本镜头。
//   - RedheadPlainLanguage / RedheadGlossary / RedheadRelevance / RedheadTimeline 这几个
//     .tsx 文件还在，但 App.tsx 已不再 import / 挂载它们（大白话 + 术语并进了逐条精读，
//     相关性并进了利害，时间轴并进了要点提取的时序视图）。本镜头只拼 App 真在挂的，
//     不捡这些孤儿文件。
//
// 怎么保住懒生成（关键）：
//   这六个组件每个都自带懒加载——内部各持一份 result 状态，!result 时只画一张「生成 X」
//   入口卡，用户点了才发 LLM 请求。本镜头只是把它们六个竖着叠成六段，不替它们预跑、
//   不在挂载时碰任何一个的 load()。所以一进全景不会把六七个分析全自动烧一遍，每段仍是
//   各自点各自的「生成」。
//
// 主 Claude 接 App 要做的（本组件不接 App）：
//   - 给 Mode 联合类型加一个 "redhead_panorama"（或沿用你定的名）。
//   - 在 currentSession 守卫内加一段 <div className={mode === "redhead_panorama" ? "" : "hidden"}>，
//     配一条 CanvasHeader，里面渲染 <RedheadDocPanorama sessionId={currentSession.session_id}
//     provider apiKey model baseUrl={effectiveBaseUrl()} />，四个 provider 相关 prop 跟现在
//     传给单份公文视图的那组一模一样。
//   - Sidebar 里把「公文结构 / 逐条精读 / 利害与风向 / 要点提取 / 办事清单 / 规范性自检」这
//     六个平铺入口收成一个「公文全景」入口（指向新 mode）；跨文件那三个 + 卷宗保持不动。
//   - 别改本镜头拼进来的六个视图组件、别动关系图那套、别动跨文件视图。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { RedheadDocStructure } from "./RedheadDocStructure";
import { RedheadCloseReading } from "./RedheadCloseReading";
import { RedheadStakes } from "./RedheadStakes";
import { RedheadHardFacts } from "./RedheadHardFacts";
import { RedheadActionList } from "./RedheadActionList";
import { RedheadFormatCheck } from "./RedheadFormatCheck";

interface RedheadDocPanoramaProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 六段的次序 + 锚点 id + 导航标题。次序按读一份公文的自然动线：
// 先看骨架（结构）→ 逐条读懂（精读）→ 跟我啥关系（利害）→ 硬信息速查（要点）→
// 照着办（办事）→ 顺手核格式（自检）。
type SectionId =
  | "structure"
  | "closereading"
  | "stakes"
  | "hardfacts"
  | "actions"
  | "formatcheck";

const SECTIONS: ReadonlyArray<{ id: SectionId; label: string }> = [
  { id: "structure", label: "结构" },
  { id: "closereading", label: "逐条精读" },
  { id: "stakes", label: "利害" },
  { id: "hardfacts", label: "要点" },
  { id: "actions", label: "办事" },
  { id: "formatcheck", label: "格式核" },
];

export function RedheadDocPanorama({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadDocPanoramaProps) {
  // 每段一个 DOM 引用，点导航时滚到它。
  const sectionRefs = useRef<Map<SectionId, HTMLElement | null>>(new Map());
  // 当前滚到哪一段——导航高亮跟着走。用 IntersectionObserver 盯，不挂滚动监听。
  const [active, setActive] = useState<SectionId>("structure");

  // 传给各组件的公共 prop 收成一份，六段透传同一组（跟 App 现在传给单份视图的一致）。
  const shared = useMemo(
    () => ({ sessionId, provider, apiKey, model, baseUrl }),
    [sessionId, provider, apiKey, model, baseUrl],
  );

  function scrollTo(id: SectionId) {
    const el = sectionRefs.current.get(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // 盯六段谁在视口里，命中就把它设为高亮。rootMargin 顶部收一截，让吸顶导航底下
  // 那段才算「当前」，不是刚冒头就抢高亮。
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        // 取当前相交里最靠上的那段作高亮，避免多段同时可见来回跳。
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length > 0) {
          const id = (visible[0].target as HTMLElement).dataset.section as SectionId;
          if (id) setActive(id);
        }
      },
      { rootMargin: "-88px 0px -55% 0px", threshold: 0 },
    );
    const els = sectionRefs.current;
    for (const id of SECTIONS.map((s) => s.id)) {
      const el = els.get(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <div className="pt-2">
      {/* ── 吸顶锚点导航 ──
          sticky top-14 让它落在移动端固定顶栏（h-14）之下；桌面无固定栏，贴视口顶也不挡。
          底下一道细朱砂规收边，跟数字善本的分隔语言一致。 */}
      <nav
        className="sticky top-14 md:top-0 z-10 -mx-1 mb-2 flex flex-wrap items-center gap-1.5 bg-[var(--color-paper)]/95 px-1 py-2 backdrop-blur"
        style={{ borderBottom: "1px solid var(--color-rule)" }}
        aria-label="公文全景各段"
      >
        <span
          className="mr-1 h-3.5 w-[3px] rounded-full bg-[var(--color-seal)]"
          aria-hidden="true"
        />
        {SECTIONS.map((s) => {
          const on = active === s.id;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => scrollTo(s.id)}
              aria-current={on ? "true" : undefined}
              className="rounded px-2.5 py-1 text-[13px] transition-colors"
              style={{
                fontFamily: "var(--font-display)",
                color: on ? "var(--color-seal)" : "var(--color-ink-muted)",
                background: on ? "var(--color-seal-soft)" : "transparent",
                fontWeight: on ? 700 : 500,
              }}
            >
              {s.label}
            </button>
          );
        })}
      </nav>

      {/* ── 六段视图 ──
          每段包一层带 ref + data-section + scroll-mt 的 <section>：ref 供点导航滚过来，
          scroll-mt 让滚到位后标题不被吸顶导航压住（导航约 3.25rem 高，留 scroll-mt-16）。
          段里直接渲染现成组件、只透传 shared——组件各自的懒生成入口原样保留，
          全景不替它预跑任何一段。段与段之间用一道细朱砂规 + 留白分隔。 */}
      <PanoramaSection
        id="structure"
        refs={sectionRefs}
        first
      >
        <RedheadDocStructure
          {...shared}
          onJumpToCloseReading={() => scrollTo("closereading")}
        />
      </PanoramaSection>

      <PanoramaSection id="closereading" refs={sectionRefs}>
        <RedheadCloseReading
          {...shared}
          onJumpToStructure={() => scrollTo("structure")}
        />
      </PanoramaSection>

      <PanoramaSection id="stakes" refs={sectionRefs}>
        <RedheadStakes {...shared} />
      </PanoramaSection>

      <PanoramaSection id="hardfacts" refs={sectionRefs}>
        <RedheadHardFacts {...shared} />
      </PanoramaSection>

      <PanoramaSection id="actions" refs={sectionRefs}>
        <RedheadActionList
          {...shared}
          onJumpToFacts={() => scrollTo("hardfacts")}
        />
      </PanoramaSection>

      <PanoramaSection id="formatcheck" refs={sectionRefs}>
        <RedheadFormatCheck {...shared} />
      </PanoramaSection>
    </div>
  );
}

// 一段的外壳：登记 ref、贴 data-section 给 observer 认、留吸顶偏移，段前画分隔规。
function PanoramaSection({
  id,
  refs,
  first,
  children,
}: {
  id: SectionId;
  refs: React.MutableRefObject<Map<SectionId, HTMLElement | null>>;
  first?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      ref={(el) => {
        refs.current.set(id, el);
      }}
      data-section={id}
      className="scroll-mt-16"
    >
      {/* 段间分隔：细朱砂规 + 上下留白。首段不画，免得贴着导航多一条线。 */}
      {!first && (
        <div
          className="my-8"
          aria-hidden="true"
          style={{
            height: "1px",
            background:
              "linear-gradient(to right, transparent, var(--color-seal) 12%, var(--color-seal) 88%, transparent)",
            opacity: 0.28,
          }}
        />
      )}
      {children}
    </section>
  );
}
