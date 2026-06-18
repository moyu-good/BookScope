// ---------------------------------------------------------------------------
// CharacterVoice — 声口一致（角色说话腔调一致性）
//
// 输一个角色 → 调 /api/agent/character-voice（整本进上下文归拢他的对白）→ 一张「声口卡」：
//   上半：语言特征（口头禅 / 句式 / 文白 / 用词 / 语气），每条挂代表对白，核验过盖朱砂钤印、
//         核不过的淡化（不剔——描述性特征留给读者自己核）。
//   下半：voice drift 提示（这句不像他说的），每条挂那句对白 + 章 + 一句为什么，点开看原文。
//         BE 已把挂不上原文的 drift 滤掉，列表里全核验过。每条标"这是提示不是定论，你自己判断"。
// 命根子：样本不足时明说、不硬下判定；合理的剧情驱动口吻变化 BE 不报。沿用 EntityRecall 样式。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { SealMark } from "./SealMark";

interface VoiceFeature {
  trait: string;
  evidence: string;
  verified?: boolean;
  match_score?: number;
  chapter?: number;
}

interface DriftItem {
  chapter: number;
  quote: string;
  reason: string;
  verified?: boolean;
  match_score?: number;
}

interface CharacterVoiceProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export function CharacterVoice({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: CharacterVoiceProps) {
  const [character, setCharacter] = useState("");
  const [queried, setQueried] = useState<string | null>(null);
  const [features, setFeatures] = useState<VoiceFeature[] | null>(null);
  const [driftItems, setDriftItems] = useState<DriftItem[]>([]);
  const [sampleTooSmall, setSampleTooSmall] = useState(false);
  const [scanned, setScanned] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);

  async function load() {
    const c = character.trim();
    if (!c) return;
    setLoading(true);
    setError(null);
    setOpenIdx(null);
    setFeatures(null);
    setDriftItems([]);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        character: c,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/character-voice", {
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
      const data = (await resp.json()) as {
        character: string;
        sample_too_small: boolean;
        features: VoiceFeature[];
        drift_items: DriftItem[];
        scanned: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      setScanned(data.scanned);
      setSampleTooSmall(data.sample_too_small);
      setFeatures(data.features);
      setDriftItems(data.drift_items ?? []);
      setQueried(data.character);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="pt-4">
      <p className="text-sm text-[var(--color-ink-muted)] mb-3 leading-relaxed">
        输一个角色，归拢他全书的对白，刻画说话的腔调，再标出哪几句「不像他说的」——每条挂原文，你自己判断。
      </p>

      <form
        onSubmit={(ev) => {
          ev.preventDefault();
          load();
        }}
        className="flex gap-2 mb-5"
      >
        <input
          value={character}
          onChange={(e) => setCharacter(e.target.value)}
          placeholder="比如：张飞 / 林黛玉 / 某个主角"
          className="flex-1 rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm focus:border-[var(--color-seal)] outline-none"
          style={{ fontFamily: "var(--font-display)" }}
        />
        <button
          type="submit"
          disabled={loading || !apiKey || !character.trim()}
          className="shrink-0 text-sm px-4 py-2 rounded bg-[var(--color-seal)] text-white hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {loading ? "归拢中（约 1 分钟）…" : "看声口"}
        </button>
      </form>

      {error && (
        <p className="text-sm" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label={`归拢「${character.trim()}」的对白`} />}

      {!scanned && features && (
        <p className="text-sm text-[var(--color-ink-muted)]">
          这本书太大，暂不支持声口分析。
        </p>
      )}

      {scanned &&
        features &&
        sampleTooSmall && (
          <p className="text-sm text-[var(--color-ink)]">
            「{queried}」全书对白太少，不够刻画稳定的声口——样本不足，不硬下判定。
          </p>
        )}

      {scanned &&
        features &&
        !sampleTooSmall &&
        features.length === 0 &&
        driftItems.length === 0 &&
        queried && (
          <p className="text-sm text-[var(--color-ink)]">
            没归拢到「{queried}」可锚到原文的对白——换个角色名 / 写法再试试。
          </p>
        )}

      {scanned && features && (features.length > 0 || driftItems.length > 0) && (
        <>
          {/* 上半：语言特征——声口卡 */}
          {features.length > 0 && (
            <section className="mb-7">
              <h3
                className="text-[15px] mb-3 text-[var(--color-ink)]"
                style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
              >
                「{queried}」的声口
              </h3>
              <ul className="space-y-3">
                {features.map((f, i) => (
                  <li
                    key={i}
                    className="rounded-md border px-4 py-3"
                    style={{
                      borderColor: "var(--color-folio-edge)",
                      background: "var(--color-paper-raised)",
                      opacity: f.verified ? 1 : 0.6,
                    }}
                  >
                    <div
                      className="text-[14px] leading-relaxed text-[var(--color-ink)] flex items-center gap-1.5"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      <span>{f.trait}</span>
                      {f.verified && <SealMark size={16} title="原文已核验" />}
                    </div>
                    {f.evidence && (
                      <div
                        className="mt-2 border-l-2 border-[var(--color-seal)]/40 pl-3 py-1 text-[13px] leading-relaxed text-[var(--color-ink-muted)]"
                        style={{ fontFamily: "var(--font-display)" }}
                      >
                        “{f.evidence}”
                        {f.verified && f.chapter ? (
                          <span className="ml-2 text-xs opacity-60">
                            第 {f.chapter} 章
                          </span>
                        ) : null}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* 下半：voice drift 提示 */}
          <section>
            <h3
              className="text-[15px] mb-1.5 text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
            >
              「这句不像他说的」
            </h3>
            <p className="text-xs text-[var(--color-ink-muted)] mb-3 leading-relaxed">
              这是提示，不是定论——合理的剧情驱动口吻变化不在这里。点开看原文，你自己判断。
            </p>
            {driftItems.length === 0 ? (
              <p className="text-sm text-[var(--color-ink)]">
                没挑出可疑的句子——「{queried}」的声口从头到尾挺稳。
              </p>
            ) : (
              <ol className="relative border-l border-[var(--color-rule)] ml-2">
                {driftItems.map((d, i) => (
                  <li key={i} className="mb-4 ml-4">
                    <span
                      className="absolute -left-[5px] w-2.5 h-2.5 rounded-full"
                      style={{ background: "var(--color-seal)" }}
                      aria-hidden="true"
                    />
                    <button
                      type="button"
                      onClick={() => setOpenIdx(openIdx === i ? null : i)}
                      className="text-left w-full"
                    >
                      <div
                        className="text-[14px] leading-relaxed text-[var(--color-ink)]"
                        style={{ fontFamily: "var(--font-display)" }}
                      >
                        {d.reason || "（疑似不符）"}
                      </div>
                      <div className="text-xs text-[var(--color-ink-muted)] mt-1 flex items-center gap-1.5">
                        <span>第 {d.chapter} 章</span>
                        {d.verified && <SealMark size={17} title="原文已核验" />}
                        <span className="ml-auto opacity-60">
                          {openIdx === i ? "收起原文" : "看原文"}
                        </span>
                      </div>
                    </button>
                    {openIdx === i && d.quote && (
                      <div
                        className="mt-1.5 border-l-2 border-[var(--color-seal)]/40 pl-3 py-1 text-[13px] leading-relaxed text-[var(--color-ink)]"
                        style={{ fontFamily: "var(--font-display)" }}
                      >
                        “{d.quote}”
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>

          {!loading && <RunStats trace={trace} />}
        </>
      )}
    </div>
  );
}
