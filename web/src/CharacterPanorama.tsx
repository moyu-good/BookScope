// CharacterPanorama —— 人物整合镜头
// ---------------------------------------------------------------------------
// 目的：看一本书的人物不用在四个 tab 间来回跳。把吃「单份 sessionId」的四个人物
// 视图拼成一个连续镜头：顶上一条吸顶锚点导航，下面每个视图一段，点导航跳到那段。
//
// 整合了哪四个视图（都吃 { sessionId, provider, apiKey, model, baseUrl }，跟 App 里
// 现挂的完全一致）：
//   1. 关系图    CharacterGraph        （App mode="graph"）
//   2. 关系演变  RelationshipTimeline  （App mode="reltime"）
//   3. 人物弧线  CharacterArc          （App mode="chararc"）
//   4. 声口一致  CharacterVoice        （App mode="charvoice"）
//
// 段的次序按读人物的自然动线：先看全局谁跟谁（关系图）→ 挑一对看怎么走（关系演变）
// → 看单个人一路怎么起落（人物弧线）→ 抠他说话的腔调（声口一致）。
//
// 联动是白来的（本组件不接线）：
//   关系图和关系演变都订阅了 viz/vizFocus 那根总线。关系图点一个人会 setFocus 广播，
//   关系演变读 focus 自动聚焦到他。两个都渲染进这个镜头，所以在关系图点谁，下面关系
//   演变段就自动切到他——这正是整合的价值。总线早就就绪，只要把两个都渲染进来即可，
//   不用也别去改它们的联动逻辑。
//   顺手加的一点：关系图点人时，除了广播，本镜头还把页面平滑滚到关系演变段，省得用户
//   自己往下翻。走 CharacterGraph 的可选 onSelectPerson，不影响它内部的总线广播。
//
// 怎么保住懒生成（关键）：
//   这四个组件每个都自带懒加载——内部各持一份 result 状态，没结果时只画一张「生成 X」
//   入口卡，用户点了才发 LLM 请求。本镜头只是把它们四个竖着叠成四段，不替它们预跑、
//   不在挂载时碰任何一个的 load()。所以一进镜头不会把四个分析全自动烧一遍，每段仍是
//   各自点各自的「生成」。
//
// 主 Claude 接 App 要做的（本组件不接 App）：
//   - 给 Mode 联合类型加一个 "char_panorama"（App.tsx 约 836 行和 2378 行两处 Mode 定义，
//     以及 2416 行那份 mode 白名单数组，都要加上）。
//   - 在 currentSession 守卫内加一段 <div className={mode === "char_panorama" ? "" : "hidden"}>，
//     配一条 CanvasHeader，里面渲染 <CharacterPanorama sessionId={currentSession.session_id}
//     provider={provider} apiKey={apiKey} model={model} baseUrl={effectiveBaseUrl()} />，
//     四个 provider 相关 prop 跟现在传给单个人物视图的那组一模一样。
//   - Sidebar（App.tsx 约 2450 行那个 title="人物" 的组）里，把「关系图 / 关系演变 /
//     人物弧线 / 声口一致」这四个平铺入口收成一个「人物」入口（指向新 mode "char_panorama"）。
//   - 别改本镜头拼进来的四个视图组件、别动 vizFocus 总线、别碰公文那套镜头和别的视图。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { CharacterGraph } from "./CharacterGraph";
import { RelationshipTimeline } from "./RelationshipTimeline";
import { CharacterArc } from "./CharacterArc";
import { CharacterVoice } from "./CharacterVoice";

interface CharacterPanoramaProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 四段的锚点 id + 导航标题。次序即读人物的自然动线（见文件头）。
type SectionId = "graph" | "reltime" | "chararc" | "charvoice";

const SECTIONS: ReadonlyArray<{ id: SectionId; label: string }> = [
  { id: "graph", label: "关系图" },
  { id: "reltime", label: "关系演变" },
  { id: "chararc", label: "人物弧线" },
  { id: "charvoice", label: "声口一致" },
];

export function CharacterPanorama({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: CharacterPanoramaProps) {
  // 每段一个 DOM 引用，点导航时滚到它。
  const sectionRefs = useRef<Map<SectionId, HTMLElement | null>>(new Map());
  // 当前滚到哪一段——导航高亮跟着走。用 IntersectionObserver 盯，不挂滚动监听。
  const [active, setActive] = useState<SectionId>("graph");

  // 传给各组件的公共 prop 收成一份，四段透传同一组（跟 App 现在传给单个视图的一致）。
  const shared = useMemo(
    () => ({ sessionId, provider, apiKey, model, baseUrl }),
    [sessionId, provider, apiKey, model, baseUrl],
  );

  function scrollTo(id: SectionId) {
    const el = sectionRefs.current.get(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // 盯四段谁在视口里，命中就把它设为高亮。rootMargin 顶部收一截，让吸顶导航底下
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
        aria-label="人物全景各段"
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

      {/* ── 四段视图 ──
          每段包一层带 ref + data-section + scroll-mt 的 <section>：ref 供点导航滚过来，
          scroll-mt 让滚到位后标题不被吸顶导航压住（导航约 3.25rem 高，留 scroll-mt-16）。
          段里直接渲染现成组件、只透传 shared——组件各自的懒生成入口原样保留，
          镜头不替它预跑任何一段。段与段之间用一道细朱砂规 + 留白分隔。 */}
      <PanoramaSection id="graph" refs={sectionRefs} first>
        {/* 点人时：总线广播由组件内部做（下面关系演变段自动聚焦），本镜头顺手滚过去。 */}
        <CharacterGraph
          {...shared}
          onSelectPerson={() => scrollTo("reltime")}
        />
      </PanoramaSection>

      <PanoramaSection id="reltime" refs={sectionRefs}>
        <RelationshipTimeline {...shared} />
      </PanoramaSection>

      <PanoramaSection id="chararc" refs={sectionRefs}>
        <CharacterArc {...shared} />
      </PanoramaSection>

      <PanoramaSection id="charvoice" refs={sectionRefs}>
        <CharacterVoice {...shared} />
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
