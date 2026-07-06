// NarrativePanorama —— 情节脉络整合镜头
// ---------------------------------------------------------------------------
// 目的：看一本书的情节走向不用在五个 tab 间来回跳。把书侧「情节脉络」那组吃单份
// sessionId 的视图拼成一个连续镜头：顶上一条吸顶锚点导航，下面每个视图一段，点导航
// 跳到那段。
//
// 整合了哪几个视图（都吃单份 sessionId，跟 App 里现挂的完全一致）：
//   1. 叙事曲线  NarrativeCurve  （App mode="narrative"）
//   2. 叙事流    CharacterFlow   （App mode="flow"）
//   3. 时间线    Timeline        （App mode="timeline"）
//   4. 支线编织  SubplotWeave    （App mode="subplot"）
//   5. 伏笔回收  ForeshadowArcs  （App mode="foreshadow"）
//
// 这五个的 props 完全一致，都是 { sessionId, provider, apiKey, model, baseUrl }，没有额外
// 的跳转回调（公文镜头里那几个 onJumpTo* 是公文组件独有的，这五个没有），所以本镜头
// 给五段透传同一份 shared 就够。
//
// 段的次序（读情节的自然动线）：先看整本节奏起伏（叙事曲线）→ 人物线怎么穿过全书
// （叙事流）→ 关键事件先后（时间线）→ 支线怎么编织（支线编织）→ 埋的坑填没填
// （伏笔回收）。
//
// 怎么保住懒生成（关键）：
//   这五个组件每个都自带懒加载——内部各持一份 result 状态，没生成时只画一张「生成 X」
//   入口卡，用户点了才发 LLM 请求（没有挂载即拉数据的 useEffect）。本镜头只是把它们五个
//   竖着叠成五段，不替它们预跑、不在挂载时碰任何一个的 load()。所以一进全景不会把五个
//   分析全自动烧一遍，每段仍是各自点各自的「生成」。
//
// 主 Claude 接 App 要做的（本组件不接 App）：
//   - 给 Mode 联合类型加一个 "plot_panorama"。
//   - 在 currentSession 守卫内加一段 <div className={mode === "plot_panorama" ? "" : "hidden"}>，
//     配一条 CanvasHeader，里面渲染 <NarrativePanorama sessionId={currentSession.session_id}
//     provider apiKey model baseUrl={effectiveBaseUrl()} />，四个 provider 相关 prop 跟现在
//     传给叙事曲线 / 叙事流 / 时间线 / 支线编织 / 伏笔回收 的那组一模一样。
//   - Sidebar 里把「叙事曲线 / 叙事流 / 时间线 / 支线编织 / 伏笔回收」这五个平铺入口收成
//     一个「情节脉络」入口（指向新 mode）；人物那组、公文那套、关系图那套都保持不动。
//   - 别改本镜头拼进来的五个视图组件、别动人物镜头、别动公文镜头。
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { NarrativeCurve } from "./NarrativeCurve";
import { CharacterFlow } from "./CharacterFlow";
import { Timeline } from "./Timeline";
import { SubplotWeave } from "./SubplotWeave";
import { ForeshadowArcs } from "./ForeshadowArcs";

interface NarrativePanoramaProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 五段的次序 + 锚点 id + 导航标题。次序按读情节的自然动线：
// 先看整本节奏起伏（曲线）→ 人物线怎么穿过全书（流）→ 关键事件先后（时间线）→
// 支线怎么编织（编织）→ 埋的坑填没填（伏笔）。
type SectionId =
  | "curve"
  | "flow"
  | "timeline"
  | "subplot"
  | "foreshadow";

const SECTIONS: ReadonlyArray<{ id: SectionId; label: string }> = [
  { id: "curve", label: "叙事曲线" },
  { id: "flow", label: "叙事流" },
  { id: "timeline", label: "时间线" },
  { id: "subplot", label: "支线编织" },
  { id: "foreshadow", label: "伏笔回收" },
];

export function NarrativePanorama({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: NarrativePanoramaProps) {
  // 每段一个 DOM 引用，点导航时滚到它。
  const sectionRefs = useRef<Map<SectionId, HTMLElement | null>>(new Map());
  // 当前滚到哪一段——导航高亮跟着走。用 IntersectionObserver 盯，不挂滚动监听。
  const [active, setActive] = useState<SectionId>("curve");

  // 传给各组件的公共 prop 收成一份，五段透传同一组（跟 App 现在传给这五个视图的一致）。
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
        aria-label="情节脉络各段"
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
          段里直接渲染现成组件、只透传 shared——组件各自的懒生成入口原样保留，
          全景不替它预跑任何一段。段与段之间用一道细朱砂规 + 留白分隔。 */}
      <PanoramaSection id="curve" refs={sectionRefs} first>
        <NarrativeCurve {...shared} />
      </PanoramaSection>

      <PanoramaSection id="flow" refs={sectionRefs}>
        <CharacterFlow {...shared} />
      </PanoramaSection>

      <PanoramaSection id="timeline" refs={sectionRefs}>
        <Timeline {...shared} />
      </PanoramaSection>

      <PanoramaSection id="subplot" refs={sectionRefs}>
        <SubplotWeave {...shared} />
      </PanoramaSection>

      <PanoramaSection id="foreshadow" refs={sectionRefs}>
        <ForeshadowArcs {...shared} />
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
