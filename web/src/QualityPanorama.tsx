// QualityPanorama —— 质量·写作整合镜头
// ---------------------------------------------------------------------------
// 目的：给一本书做质量和写作层面的检查，不用在五个 tab 间来回跳。把书侧「质量·写作」
// 那组吃单份 sessionId 的视图拼成一个连续镜头：顶上一条吸顶锚点导航，下面每个视图一段，
// 点导航跳到那段。
//
// 整合了哪五个视图（前四个吃 { sessionId, provider, apiKey, model, baseUrl }，改稿清单
// 多吃一个 bookTitle，跟 App 里现挂的完全一致）：
//   1. 设定一致性  ConsistencyScan   （App mode="consistency"）
//   2. 写作手法    WritingTechnique  （App mode="technique"）
//   3. 文体体检    StyleIssues       （App mode="style"）
//   4. 改稿清单    RevisionList      （App mode="revision"，额外吃 bookTitle 做导出文件名）
//   5. 知识卡片    StudyCards        （App mode="cards"）
//
// 段的次序按读质量的自然动线：先看有没有硬伤（一致性）→ 看作者怎么写、学手艺（写作手法）
// → 抠文体毛病（文体体检）→ 把毛病攒成一份能带走的修改清单（改稿清单）→ 顺手沉淀成
// 知识卡片自测（知识卡片）。一致性和文体体检都是「找问题」，改稿清单正好把两边找出的
// 东西收口，摆在它们后面顺。
//
// 这五个视图之间没有 onJump 之类的跨段回调（都只吃 provider 那几个 prop），所以本镜头
// 不接段内滚动联动，只做锚点导航 + 高亮，跟人物镜头里那种「点人滚到关系演变」的联动无关。
//
// 怎么保住懒生成（关键）：
//   这五个组件每个都自带懒加载——内部各持一份 result 状态，没结果时只画一张「生成 X」
//   入口卡，用户点了才发 LLM 请求。本镜头只是把它们五个竖着叠成五段，不替它们预跑、
//   不在挂载时碰任何一个的 load()。所以一进镜头不会把五个分析全自动烧一遍，每段仍是
//   各自点各自的「生成」。
//
// 主 Claude 接 App 要做的（本组件不接 App）：
//   - 给 Mode 联合类型加一个 "quality_panorama"（App.tsx 里几处 Mode 定义 + mode 白名单
//     数组都要加上）。
//   - 在 currentSession 守卫内加一段 <div className={mode === "quality_panorama" ? "" : "hidden"}>，
//     配一条 CanvasHeader，里面渲染 <QualityPanorama sessionId={currentSession.session_id}
//     bookTitle={currentSession.book_title} provider={provider} apiKey={apiKey}
//     model={model} baseUrl={effectiveBaseUrl()} />。前五个 provider 相关 prop 跟现在传给
//     单个质量视图的那组一模一样，bookTitle 跟现在传给改稿清单的一样。
//   - Sidebar 里把「设定一致性 / 写作手法 / 文体体检 / 改稿清单 / 知识卡片」这五个平铺
//     入口收成一个「质量·写作」入口（指向新 mode "quality_panorama"）。
//   - 别改本镜头拼进来的五个视图组件、别碰人物镜头 / 公文镜头和别的视图。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { ConsistencyScan } from "./ConsistencyScan";
import { WritingTechnique } from "./WritingTechnique";
import { StyleIssues } from "./StyleIssues";
import { RevisionList } from "./RevisionList";
import { StudyCards } from "./StudyCards";

interface QualityPanoramaProps {
  sessionId: string;
  bookTitle: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 五段的锚点 id + 导航标题。次序即读质量的自然动线（见文件头）。
type SectionId = "consistency" | "technique" | "style" | "revision" | "cards";

const SECTIONS: ReadonlyArray<{ id: SectionId; label: string }> = [
  { id: "consistency", label: "一致性" },
  { id: "technique", label: "写作手法" },
  { id: "style", label: "文体体检" },
  { id: "revision", label: "改稿清单" },
  { id: "cards", label: "知识卡片" },
];

export function QualityPanorama({
  sessionId,
  bookTitle,
  provider,
  apiKey,
  model,
  baseUrl,
}: QualityPanoramaProps) {
  // 每段一个 DOM 引用，点导航时滚到它。
  const sectionRefs = useRef<Map<SectionId, HTMLElement | null>>(new Map());
  // 当前滚到哪一段——导航高亮跟着走。用 IntersectionObserver 盯，不挂滚动监听。
  const [active, setActive] = useState<SectionId>("consistency");

  // 传给各组件的公共 prop 收成一份，五段透传同一组（跟 App 现在传给单个视图的一致）。
  // 改稿清单还要 bookTitle，单独在那一段补上。
  const shared = useMemo(
    () => ({ sessionId, provider, apiKey, model, baseUrl }),
    [sessionId, provider, apiKey, model, baseUrl],
  );

  function scrollTo(id: SectionId) {
    const el = sectionRefs.current.get(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // 盯五段谁在视口里，命中就把它设为高亮。rootMargin 顶部收一截，让吸顶导航底下
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
        aria-label="质量写作全景各段"
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

      {/* ── 五段视图 ──
          每段包一层带 ref + data-section + scroll-mt 的 <section>：ref 供点导航滚过来，
          scroll-mt 让滚到位后标题不被吸顶导航压住（导航约 3.25rem 高，留 scroll-mt-16）。
          段里直接渲染现成组件、只透传 shared（改稿清单另补 bookTitle）——组件各自的懒生成
          入口原样保留，镜头不替它预跑任何一段。段与段之间用一道细朱砂规 + 留白分隔。 */}
      <PanoramaSection id="consistency" refs={sectionRefs} first>
        <ConsistencyScan {...shared} />
      </PanoramaSection>

      <PanoramaSection id="technique" refs={sectionRefs}>
        <WritingTechnique {...shared} />
      </PanoramaSection>

      <PanoramaSection id="style" refs={sectionRefs}>
        <StyleIssues {...shared} />
      </PanoramaSection>

      <PanoramaSection id="revision" refs={sectionRefs}>
        <RevisionList {...shared} bookTitle={bookTitle} />
      </PanoramaSection>

      <PanoramaSection id="cards" refs={sectionRefs}>
        <StudyCards {...shared} />
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
