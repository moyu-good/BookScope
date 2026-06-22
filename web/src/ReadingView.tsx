// ---------------------------------------------------------------------------
// ReadingView —— 精读的两种读法（WP-reading-experience，1.3）
//
// 「通读」= 新的真阅读器（Reader）：整本书按章读，字号 / 行距 / 页边 / 背景 / 字体
//          可调，读到哪记得住。先安安静静读。
// 「批注」= 注释层（AnnotatedReader）：按选中的层（伏笔 / 矛盾 / 母题 / 人物）通读全书，
//          带原文证据的朱砂批注浮在行间，点开看证据 + 跨章跳转。
//
// 两块各自独立、互不打断：用 hidden 收起非当前页（不卸载），切回去时阅读位置 /
// 已生成的批注都还在。注释层逐渐并进阅读器行间（marks 直接浮在可调排版的连续正文里）
// 是后续版本的事，这一版先把真阅读器交出来、批注能力一个不少。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { AnnotatedReader } from "./AnnotatedReader";
import { Reader } from "./Reader";

interface ReadingViewProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export function ReadingView({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: ReadingViewProps) {
  const [tab, setTab] = useState<"read" | "annotate">("read");

  return (
    <div className="pt-2">
      <div className="flex gap-1.5 mb-2">
        <TabButton active={tab === "read"} onClick={() => setTab("read")}>
          通读
        </TabButton>
        <TabButton active={tab === "annotate"} onClick={() => setTab("annotate")}>
          批注
        </TabButton>
      </div>

      {/* hidden 收起非当前页、不卸载——切回去阅读位置 / 已生成批注都还在 */}
      <div className={tab === "read" ? "" : "hidden"}>
        <Reader sessionId={sessionId} />
      </div>
      <div className={tab === "annotate" ? "" : "hidden"}>
        <AnnotatedReader
          sessionId={sessionId}
          provider={provider}
          apiKey={apiKey}
          model={model}
          baseUrl={baseUrl}
        />
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-sm px-4 py-1.5 rounded-full border transition-colors"
      style={
        active
          ? {
              background: "var(--color-seal-soft)",
              borderColor: "var(--color-seal)",
              color: "var(--color-seal)",
            }
          : {
              background: "var(--color-paper)",
              borderColor: "var(--color-rule)",
              color: "var(--color-ink-muted)",
            }
      }
    >
      {children}
    </button>
  );
}
