// ---------------------------------------------------------------------------
// EvidenceMark — 证据指示件（可视化 Phase 0 地基之补，接遍公文 / 书侧镜头）
//
// 把「一条结论的原文靠不靠得住」收成一枚可交互的小印记：核过的摆「鉴」印（钤印 = 已核的
// 视觉语言，SealMark），没核的摆证据强度标（EvidenceBadge 的 部分 / 待核）。悬停或键盘
// 聚焦这枚印 / 标，浮出锚定的原文 + 章次 + 强度四态（走共享 EvidencePopover）。
//
// 干一件事：把「盖印 or 强度标 + 悬停浮原文」这套接线收成一处，各镜头一行接入，不再各写
// 各的。强度从 deriveEvidenceStrength 一处判——证据强度只有一个真相来源，跟依据链网、
// 书侧镜头同一套（evidence-first：有原文显原文 + 核验态，没有就老实显「待核」，绝不编）。
// ---------------------------------------------------------------------------

import { SealMark } from "../SealMark";
import { EvidenceBadge } from "./EvidenceBadge";
import { EvidencePopover, deriveEvidenceStrength } from "./EvidencePopover";

interface EvidenceMarkProps {
  /** 锚定的原文引文。空 = 暂无贴切原文，浮层显「待核」不编。 */
  evidence: string;
  /** 是否逐字核验通过。 */
  verified: boolean;
  /** 原文匹配度 0-1（区分强锚 / 弱锚）。 */
  matchScore?: number;
  /** 原文所在章 / 条（有就在浮层显「第 N 章」）。 */
  chapter?: number | null;
  /** 「鉴」印尺寸（默认 17）。 */
  sealSize?: number;
}

function hasText(v: string | undefined): boolean {
  return !!v && v.trim().length > 0;
}

export function EvidenceMark({
  evidence,
  verified,
  matchScore,
  chapter,
  sealSize = 17,
}: EvidenceMarkProps) {
  const isVerified = verified && hasText(evidence);
  const strength = deriveEvidenceStrength(evidence, verified, matchScore);
  return (
    <EvidencePopover
      quote={evidence}
      chapter={typeof chapter === "number" ? chapter : undefined}
      verified={verified}
      matchScore={matchScore}
    >
      {/* 触发区做成可聚焦（tabIndex）——键盘走到也能看证据，不只鼠标可达 */}
      <span
        tabIndex={0}
        className="inline-flex items-center cursor-help rounded-sm outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-seal)]"
      >
        {isVerified ? (
          <SealMark size={sealSize} title="原文已核验" />
        ) : (
          <EvidenceBadge strength={strength} />
        )}
      </span>
    </EvidencePopover>
  );
}
