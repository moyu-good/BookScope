// RedheadDossierPanorama —— 卷宗全景镜头（跨文件层）
// ---------------------------------------------------------------------------
// 目的：看懂一卷宗（多份公文）里几份文件的关系，不用在三个跨文件 tab 间来回跳。
// 把吃「一组 sessionId（卷宗）」的三个跨文件视图拼成一个连续镜头：顶上一条吸顶
// 锚点导航，下面每个视图一段，点导航跳到那段。
//
// 跟 RedheadDocPanorama 的分工：那个镜头拼的是吃「单份 sessionId」的六个视图；
// 本镜头拼的是吃「一组 sessionId（卷宗）」的三个跨文件视图。两者正交，各管各的。
//
// 整合了哪三个视图（都吃 bookSessionIds，跟 App 里现挂的完全一致）：
//   1. 依据链网    RedheadDependencyGraph  （App mode="redhead_depgraph"）
//   2. 政策演变    RedheadPolicyEvolution  （App mode="redhead_policy"）
//   3. 上下级一致性 RedheadLevelConsistency （App mode="redhead_level"）
//
// 段的次序（按读一卷宗的自然动线）：
//   先看关系网（谁依据谁、谁落实谁）→ 再按时间看一项政策怎么一步步改（政策演变）→
//   最后勘对上下位文件对不对得上（上下级一致性）。
//
// 怎么保住懒生成（关键）：
//   这三个组件每个都自带懒加载——内部各持一份 result 状态，!result 时只画一张
//   「生成 X」入口卡，用户点了才发 LLM 请求。本镜头只是把它们三个竖着叠成三段，
//   不替它们预跑、不在挂载时碰任何一个的 load()。所以一进全景不会把三个分析全
//   自动烧一遍，每段仍是各自点各自的「生成」。三个视图内部都有「卷宗不足 2 份」
//   的守卫和入口提示，卷宗没选够时点了也只提示、不发请求。
//
// 联动：依据链网点一个条款会通过 vizFocus 总线广播；将来政策演变 / 上下级一致性
//   订阅了能联动。本镜头不碰总线，只把三个视图原样渲染进来。
//
// 主 Claude 接 App 要做的（本组件不接 App）：
//   - 给 Mode 联合类型加一个 "redhead_dossier_panorama"（或沿用你定的名）。
//   - 在跨文件那一层（现挂 redhead_depgraph / redhead_policy / redhead_level 的同级）
//     加一段 <div className={mode === "redhead_dossier_panorama" ? "" : "hidden"}>，
//     配一条 CanvasHeader，里面渲染 <RedheadDossierPanorama bookSessionIds={dossierIds}
//     provider apiKey model baseUrl={effectiveBaseUrl()} />，四个 provider 相关 prop
//     跟现在传给那三个跨文件视图的那组一模一样。
//   - Sidebar 里把「依据链网 / 政策演变 / 上下级一致性」这三个平铺入口收成一个
//     「卷宗全景」入口（指向新 mode）；卷宗选择器（mode="dossier" 的 Dossier）保留
//     不动——用户还是先去卷宗选一组（≥2 份），再进卷宗全景看这三段。
//   - 别改本镜头拼进来的三个视图组件、别动关系图那套、别动单份公文 / 书侧镜头、
//     别碰 vizFocus 总线。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { RedheadDependencyGraph } from "./RedheadDependencyGraph";
import { RedheadPolicyEvolution } from "./RedheadPolicyEvolution";
import { RedheadLevelConsistency } from "./RedheadLevelConsistency";

interface RedheadDossierPanoramaProps {
  bookSessionIds: string[];
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 三段的次序 + 锚点 id + 导航标题。次序按读一卷宗的自然动线：
// 先看关系网（依据链网）→ 按时间看政策怎么改（政策演变）→ 勘对上下位对不对得上（上下级）。
type SectionId = "depgraph" | "policy" | "level";

const SECTIONS: ReadonlyArray<{ id: SectionId; label: string }> = [
  { id: "depgraph", label: "依据链网" },
  { id: "policy", label: "政策演变" },
  { id: "level", label: "上下级一致性" },
];

export function RedheadDossierPanorama({
  bookSessionIds,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadDossierPanoramaProps) {
  // 每段一个 DOM 引用，点导航时滚到它。
  const sectionRefs = useRef<Map<SectionId, HTMLElement | null>>(new Map());
  // 当前滚到哪一段——导航高亮跟着走。用 IntersectionObserver 盯，不挂滚动监听。
  const [active, setActive] = useState<SectionId>("depgraph");

  // 传给各组件的公共 prop 收成一份，三段透传同一组（跟 App 现在传给那三个跨文件视图的一致）。
  const shared = useMemo(
    () => ({ bookSessionIds, provider, apiKey, model, baseUrl }),
    [bookSessionIds, provider, apiKey, model, baseUrl],
  );

  function scrollTo(id: SectionId) {
    const el = sectionRefs.current.get(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // 盯三段谁在视口里，命中就把它设为高亮。rootMargin 顶部收一截，让吸顶导航底下
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
        aria-label="卷宗全景各段"
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

      {/* ── 三段视图 ──
          每段包一层带 ref + data-section + scroll-mt 的 <section>：ref 供点导航滚过来，
          scroll-mt 让滚到位后标题不被吸顶导航压住（导航约 3.25rem 高，留 scroll-mt-16）。
          段里直接渲染现成组件、只透传 shared——组件各自的懒生成入口和卷宗守卫原样保留，
          全景不替它预跑任何一段。段与段之间用一道细朱砂规 + 留白分隔。 */}
      <PanoramaSection id="depgraph" refs={sectionRefs} first>
        <RedheadDependencyGraph {...shared} />
      </PanoramaSection>

      <PanoramaSection id="policy" refs={sectionRefs}>
        <RedheadPolicyEvolution {...shared} />
      </PanoramaSection>

      <PanoramaSection id="level" refs={sectionRefs}>
        <RedheadLevelConsistency {...shared} />
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
