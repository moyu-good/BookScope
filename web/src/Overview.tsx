// ---------------------------------------------------------------------------
// Overview — 分析台首页/概览（进门流 · 作者选"先看一张概览"）
//
// 选一本书 → 先落这一页,按题材列出"这本书能做什么",点一件进那个功能。修掉旧动线"点书直接
// 甩进问书、一脸茫然"。列的套餐 = 左栏可见组(由 App 按 genreVisibleGroups 过滤后传进来),
// 跟左栏一致、不另搞一套。纯展示,点某件回调 onPick(modeId) 让 App 切过去。
// ---------------------------------------------------------------------------

interface OverviewMode {
  id: string;
  label: string;
}
interface OverviewGroup {
  key: string;
  title: string;
  modes: OverviewMode[];
}

interface OverviewProps {
  bookTitle: string;
  genre?: string | null;
  groups: OverviewGroup[];
  onPick: (id: string) => void;
}

// 每件事一句话说人话。没列到的(公文 / 会议等)回落只显名字,不硬编。
const BLURB: Record<string, string> = {
  ask: "有什么不懂直接问，答案带原文出处，不是空口摘要。",
  annotate: "逐段精读，AI 在章末给一段朱批。",
  recap: "读到第几章，回顾一下前情。",
  entity: "全书检索某个人 / 概念 / 物，看它每次出现在哪。",
  char_panorama: "谁跟谁、什么关系、多亲近，一路怎么变过来。",
  person_dossier: "主要人物站在书里争论的哪一边，一张图看清。",
  plot_panorama: "全书的事件密度、转折、伏笔、支线怎么铺排。",
  argument: "作者的论证骨架：中心论点是什么、下面靠哪些论点撑。",
  concept_graph: "核心概念怎么勾连：定义 / 包含 / 对立 / 因果。",
  scholar_stance: "书里引的思想家，各站在核心争论的哪一极。",
  quality_panorama: "行文质量、写作手法、前后一致、改稿建议。",
};

export function Overview({ bookTitle, genre, groups, onPick }: OverviewProps) {
  return (
    <div className="pt-4 max-w-3xl">
      <div className="text-xs text-[var(--color-ink-muted)] mb-1">分析台 · 这本书能做什么</div>
      <h2
        className="text-xl font-bold text-[var(--color-ink)] leading-snug mb-1"
        style={{ fontFamily: "var(--font-display)" }}
      >
        {bookTitle}
      </h2>
      <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed mb-6">
        {genre ? `认出这是「${genre}」，` : ""}下面是给这类书备的深读，点一件进去，每个结论都能翻回原文。
      </p>

      <div className="space-y-6">
        {groups.map((g) => (
          <section key={g.key}>
            <h3
              className="text-sm font-bold text-[var(--color-seal)] mb-2.5"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {g.title}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {g.modes.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => onPick(m.id)}
                  className="text-left p-3 rounded-lg border border-[var(--color-rule)] bg-[var(--color-paper-raised)] hover:border-[var(--color-seal)] transition-colors"
                >
                  <div
                    className="text-base font-bold text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {m.label}
                  </div>
                  {BLURB[m.id] && (
                    <div className="text-xs text-[var(--color-ink-muted)] mt-1 leading-relaxed">
                      {BLURB[m.id]}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
