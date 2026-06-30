// ---------------------------------------------------------------------------
// RedheadRelevance — 跟我相关（1.6 红头文件垂直·发明区一炮）
//
// 一份红头文件几十条，普通人真正要操心的就那几条。这块让用户报上自己的身份（个体工商户 /
// 某市市场监管局 / 一家小餐饮企业…），从公文里只圈出跟他相关的条款，并说清对他是
// 义务 / 利好 / 条件，外加一句「对你」的人话。同一份公文，个体户看到的和市监局看到的
// 是两份不同的清单——独有维度 = 个性化。
//
// 艺术意象 = 朱笔圈点·眉批：像一位先生拿朱砂笔替你在这份公文上圈点、旁批——
//   · 圈点：每条相关条款的条次旁画一枚朱砂手画圈（不是规整的圆，是毛笔顺手一圈），
//     圈住「这条冲你来的」。相关度高的圈描得重、相关度中的圈描得淡。
//   · 眉批：右栏一道朱砂批语——bearing（义务/利好/条件）的朱笔签 + 「对你」那一句，
//     像古人在天头地脚写的批注，墨字主文、朱字旁批。
//   · 钤印：原文核过的盖「鉴」小印。
// 不套花鸟山水、不做成通用表格——就是「先生替你圈点批注一份公文」的案头气质。
//
// evidence-first（全站一个规矩）：相关条款的原文核过的盖「鉴」印；核不过的老实标
// 「未在原文比对命中·仅供参考」。后端只返判为相关的条款（不相关的根本不返），所以
// 这里不画「不相关」状态——没相关条款就优雅退场。
//
// 设计语言（数字善本案头）：朱墨双色（朱 = var(--color-seal) 圈点/眉批/钤印，墨 =
// var(--color-ink) 条款主文，淡墨 = var(--color-ink-muted) 原文/辅文）、宋体
// var(--font-display)、留白、古籍克制——不堆古风、无 emoji。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

// ---- 后端契约（对着 redhead_relevance.relevance_from_spine 写） ----

type Relevance = "高" | "中";
type Bearing = "义务" | "利好" | "条件";

interface RelevanceItem {
  chapter: number; // 原条款序号
  matter: string; // 原公文体事项（这条管的事）
  relevance: Relevance; // 相关度：高 / 中
  bearing: Bearing; // 对你意味着：义务 / 利好 / 条件
  note: string; // 「对你」那一句人话
  evidence: string; // 原条款逐字原文
  verified: boolean;
  match_score: number;
}

interface RelevanceResponse {
  role: string; // 回显用户身份
  items: RelevanceItem[]; // 只含判为相关的条款
  scanned: boolean;
  book_session_id: string;
  trace?: RunTrace;
}

interface RedheadRelevanceProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 常见身份预设——一点就填进输入框，省得用户自己想怎么描述。
const ROLE_PRESETS: readonly string[] = [
  "个体工商户",
  "一家小微企业",
  "某市市场监管局",
  "街道办 / 社区工作人员",
  "普通市民",
];

// bearing → 朱笔签的一句注脚（眉批里 bearing 标下面那行小字）。
const BEARING_HINT: Record<Bearing, string> = {
  义务: "你得照办",
  利好: "给你的好处",
  条件: "满足了才适用",
};

function hasText(v: string): boolean {
  return !!v && v.trim().length > 0;
}

// 朱砂手画圈——一枚毛笔顺手圈出的椭圆（两道略错位的描边，带点手写的不规整），不是规整正圆。
// 相关度高的圈描得重（strong），中的描得淡。圈里是条次数字。
function BrushCircle({ n, strong }: { n: number; strong: boolean }) {
  const opacity = strong ? 0.95 : 0.5;
  const stroke = strong ? 2.1 : 1.5;
  return (
    <span
      className="relative inline-flex items-center justify-center shrink-0"
      style={{ width: 38, height: 38 }}
      aria-hidden
    >
      <svg
        viewBox="0 0 40 40"
        width={38}
        height={38}
        className="absolute inset-0"
        style={{ transform: "rotate(-4deg)" }}
      >
        {/* 主圈：一笔顺下来的椭圆，起收笔不闭合（手写感） */}
        <path
          d="M27 9 C13 5, 5 14, 7 24 C9 33, 24 37, 32 30 C39 24, 36 11, 24 8"
          fill="none"
          stroke="var(--color-seal)"
          strokeWidth={stroke}
          strokeLinecap="round"
          opacity={opacity}
        />
        {/* 第二道略错位的描边——毛笔复圈的重影，强相关才描，立「重重一圈」的力道 */}
        {strong && (
          <path
            d="M28 11 C15 8, 8 16, 10 24 C12 31, 23 34, 30 29"
            fill="none"
            stroke="var(--color-seal)"
            strokeWidth={1.1}
            strokeLinecap="round"
            opacity={0.4}
          />
        )}
      </svg>
      <span
        className="relative tabular-nums"
        style={{
          color: "var(--color-seal)",
          fontFamily: "var(--font-display)",
          fontSize: "0.8rem",
          opacity: strong ? 1 : 0.85,
        }}
      >
        {n}
      </span>
    </span>
  );
}

export function RedheadRelevance({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: RedheadRelevanceProps) {
  const [role, setRole] = useState("");
  const [result, setResult] = useState<RelevanceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  // 默认收起原文，点「对原文」展开看逐字原话——保眉批清爽
  const [openOrigin, setOpenOrigin] = useState<Record<number, boolean>>({});

  const roleTrimmed = role.trim();

  async function load() {
    if (!roleTrimmed) return;
    setLoading(true);
    setError(null);
    setOpenOrigin({});
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
        role: roleTrimmed,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/redhead/relevance", {
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
      const data = (await resp.json()) as RelevanceResponse;
      setTrace(data.trace ?? null);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const items = result?.items ?? [];
  const scanned = !!result && result.scanned;
  const gotSomething = scanned && items.length > 0;
  const verifiedCount = useMemo(
    () => items.filter((it) => it.verified && hasText(it.evidence)).length,
    [items],
  );
  const dutyCount = useMemo(
    () => items.filter((it) => it.bearing === "义务").length,
    [items],
  );
  const perkCount = useMemo(
    () => items.filter((it) => it.bearing === "利好").length,
    [items],
  );

  // ---- 身份输入区（永远在顶上，换身份重圈一遍） ----
  const identityBar = (
    <div className="mb-4">
      <label
        className="block text-sm font-bold text-[var(--color-ink)] mb-1.5"
        style={{ fontFamily: "var(--font-display)" }}
      >
        你是谁？
      </label>
      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        报上你的身份——同一份公文，个体户看到的和市监局看到的不是一份清单。
      </p>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        {ROLE_PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            onClick={() => setRole(preset)}
            disabled={loading}
            className={`text-xs px-2.5 py-1 rounded-full border transition-colors disabled:opacity-50 ${
              roleTrimmed === preset
                ? "border-[var(--color-seal)] text-[var(--color-seal)]"
                : "border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:border-[var(--color-seal)] hover:text-[var(--color-seal)]"
            }`}
          >
            {preset}
          </button>
        ))}
      </div>
      <div className="flex items-stretch gap-2">
        <input
          type="text"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && roleTrimmed && !loading && apiKey) load();
          }}
          placeholder="也可以自己写，比如「一家做餐饮的小公司」"
          disabled={loading}
          className="flex-1 text-sm px-3 py-2 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] placeholder:text-[var(--color-ink-muted)] focus:outline-none focus:border-[var(--color-seal)] disabled:opacity-50"
          style={{ fontFamily: "var(--font-display)" }}
        />
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey || !roleTrimmed}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors whitespace-nowrap"
        >
          {loading ? "逐条圈点中…" : "看跟我相关的"}
        </button>
      </div>
      {error && (
        <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}
      {!apiKey && (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
          填了 API key 才能生成。
        </p>
      )}
    </div>
  );

  // ---- 标题行 ----
  const header = (
    <h3
      className="text-base font-bold text-[var(--color-ink)] mb-1"
      style={{ fontFamily: "var(--font-display)" }}
    >
      跟我相关
    </h3>
  );

  // ---- 未生成：入口 + 身份输入 ----
  if (!result) {
    return (
      <div className="pt-4">
        {header}
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          报上你的身份，从这份红头文件里只圈出跟你相关的条款，并说清对你是义务（你得照办）、利好（给你的好处）还是条件（满足了才适用），外加一句「对你」的人话。不相关的一条不显。适合党政公文
          / 红头文件。
        </p>
        {identityBar}
        {loading && (
          <RunningProcess
            label="替你逐条圈点"
            hint="整份公文喂进模型先拆出条款，再带着你的身份逐条判相不相关，相关的才圈出来、回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  // ---- 已生成但没一条相关：优雅退场 ----
  if (!gotSomething) {
    return (
      <div className="pt-4">
        {header}
        {identityBar}
        {loading ? (
          <RunningProcess label="替你逐条圈点" />
        ) : (
          <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
            {scanned
              ? `这份公文里没找到明显冲「${result.role}」来的条款，可能这份不直接管到你这类身份，或者它偏叙述、没分条式正文。换个身份再圈一遍，或换一份公文。`
              : "没拆出可逐条判的正文条款，这份可能偏叙述、不是分条式公文。换一份规范公文，或稍后重试。"}
          </p>
        )}
      </div>
    );
  }

  // ---- 已圈出相关条款：朱笔圈点 + 眉批 ----
  return (
    <div className="pt-4">
      {header}
      {identityBar}

      {/* 题署一行：替「身份」圈出几条 · 几义务几利好 · 原文核验几条 */}
      <div className="mb-3 flex items-center gap-2 flex-wrap">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full"
          style={{
            color: "var(--color-seal)",
            border: "0.5px solid var(--color-seal)",
          }}
        >
          替「{result.role}」圈出 {items.length} 条
        </span>
        {dutyCount > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            义务 {dutyCount}
          </span>
        )}
        {perkCount > 0 && (
          <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
            利好 {perkCount}
          </span>
        )}
        <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">
          原文核验 {verifiedCount}/{items.length}
        </span>
      </div>

      {/* 圈点卷：一条 = 一开。左朱圈圈住条次（强/弱描边见相关度），中墨字主文，右朱砂眉批。 */}
      <div className="space-y-4">
        {items.map((it, i) => {
          const verified = it.verified && hasText(it.evidence);
          const isOpen = !!openOrigin[i];
          const canOpenOrigin = hasText(it.evidence);
          const strong = it.relevance === "高";
          return (
            <article
              key={i}
              className="relative rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] overflow-hidden"
            >
              <div className="flex gap-3 pl-3 pr-3 py-3">
                {/* 左：朱砂手画圈圈住条次——圈点这一动作的视觉主体 */}
                <div className="pt-0.5">
                  <BrushCircle n={it.chapter ?? i + 1} strong={strong} />
                </div>

                {/* 中：条款主文（墨字）。事项 + 核验印。 */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-start gap-2">
                    {verified && (
                      <span className="pt-0.5">
                        <SealMark size={18} title="原文已核验" />
                      </span>
                    )}
                    <p
                      className="text-[15px] leading-7 text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {hasText(it.matter) ? it.matter : "（这条没抽到事项）"}
                    </p>
                  </div>

                  {/* 核不过老实标一行 */}
                  {!verified && (
                    <p className="mt-1.5 text-xs text-[var(--color-ink-muted)] italic">
                      {hasText(it.evidence)
                        ? "未在原文比对命中·仅供参考"
                        : "暂无贴切原文（待核）"}
                    </p>
                  )}

                  {/* 原文：默认收起，点「对原文」展开，朱砂细规一隔 */}
                  {canOpenOrigin && (
                    <div className="mt-2">
                      <button
                        type="button"
                        onClick={() =>
                          setOpenOrigin((cur) => ({ ...cur, [i]: !cur[i] }))
                        }
                        className="text-[11px] text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
                      >
                        {isOpen ? "收起原文" : "对原文"}
                      </button>
                      {isOpen && (
                        <div className="mt-2">
                          <div
                            aria-hidden
                            className="h-px mb-2"
                            style={{
                              background: "var(--color-seal)",
                              opacity: 0.3,
                            }}
                          />
                          <p
                            className="text-[13px] leading-relaxed text-[var(--color-ink-muted)]"
                            style={{ fontFamily: "var(--font-display)" }}
                          >
                            <span
                              className="text-[11px] mr-1.5 align-top"
                              style={{ color: "var(--color-seal)" }}
                            >
                              原文
                            </span>
                            {it.evidence}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* 右：朱砂眉批——一道朱笔旁注。bearing 朱签 + 一句小注脚 + 「对你」那句人话。
                    像古人在天头写的批语，朱字旁批、墨字正文。窄屏下落到主文下方。 */}
                <aside
                  className="shrink-0 w-[34%] min-w-[120px] max-w-[210px] pl-3"
                  style={{ borderLeft: "1px solid var(--color-seal)" }}
                >
                  <div className="flex items-baseline gap-1.5 mb-1">
                    <span
                      className="text-[13px] font-bold"
                      style={{
                        color: "var(--color-seal)",
                        fontFamily: "var(--font-display)",
                      }}
                    >
                      {it.bearing}
                    </span>
                    <span
                      className="text-[10px]"
                      style={{ color: "var(--color-seal)", opacity: 0.7 }}
                    >
                      {BEARING_HINT[it.bearing]}
                    </span>
                  </div>
                  {hasText(it.note) ? (
                    <p
                      className="text-[13px] leading-relaxed text-[var(--color-ink)]"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {it.note}
                    </p>
                  ) : (
                    <p className="text-[12px] text-[var(--color-ink-muted)] italic">
                      （这条没批出一句话）
                    </p>
                  )}
                  {!strong && (
                    <p className="mt-1 text-[10px] text-[var(--color-ink-muted)]">
                      间接相关
                    </p>
                  )}
                </aside>
              </div>
            </article>
          );
        })}
      </div>

      {!loading && (
        <RunStats
          trace={trace}
          note={`替「${result.role}」圈出 ${items.length} 条 · 原文核验 ${verifiedCount}`}
        />
      )}
    </div>
  );
}
