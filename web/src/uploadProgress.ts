// ---------------------------------------------------------------------------
// 上传进度估算 · 客观曲线模拟
//
// 后端 POST /api/books/upload 一次性返完整结果不流式，前端用三段经验曲线
// 模拟进度，让用户知道现在大概到哪一步、还要等多久：
//
//   0~5  秒：0%  → 30%（解析文件）
//   5~15 秒：30% → 50%（切分章节）
//  15~85 秒：50% → 95%（AI 分析角色 · 最久）
//  真实响应回来：跳 100%
//
// 总估算 90 秒——大书会更慢，曲线停在 95% 等真实响应。
// ---------------------------------------------------------------------------
import { useEffect, useRef, useState } from "react";

export interface UploadProgressState {
  /** 0~100 的百分比 */
  percent: number;
  /** 当前步骤文案 */
  stepLabel: string;
  /** 估计剩余秒数（最少 0） */
  etaSeconds: number;
}

const TOTAL_ESTIMATE_SECONDS = 90;
const TICK_MS = 200;

function computeProgress(elapsedSeconds: number): UploadProgressState {
  let percent: number;
  let stepLabel: string;
  if (elapsedSeconds < 5) {
    percent = (elapsedSeconds / 5) * 30;
    stepLabel = "正在解析文件…";
  } else if (elapsedSeconds < 15) {
    percent = 30 + ((elapsedSeconds - 5) / 10) * 20;
    stepLabel = "切分章节…";
  } else if (elapsedSeconds < 85) {
    percent = 50 + ((elapsedSeconds - 15) / 70) * 45;
    stepLabel = "AI 正在分析角色（最久这一步，请等 30-90 秒）…";
  } else {
    percent = 95;
    stepLabel = "AI 还在分析（这本书有点大，再等等）…";
  }
  const etaSeconds = Math.max(0, Math.round(TOTAL_ESTIMATE_SECONDS - elapsedSeconds));
  return { percent: Math.min(95, percent), stepLabel, etaSeconds };
}

/**
 * 上传进度 hook。
 *
 * - active=true：每 200ms 推进；
 * - active=false 且之前活跃过：跳 100% 并显示"完成"；
 * - active=false 从未活跃：返 idle 初值（percent=0）；
 * - 失败兜底：调用方让 active 切回 false 同时不显示组件即可，hook 不管错误展示。
 */
export function useUploadProgress(active: boolean): UploadProgressState {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);
  const everActiveRef = useRef(false);

  useEffect(() => {
    if (active) {
      everActiveRef.current = true;
      startRef.current = Date.now();
      setElapsed(0);
      const id = window.setInterval(() => {
        if (startRef.current !== null) {
          setElapsed((Date.now() - startRef.current) / 1000);
        }
      }, TICK_MS);
      return () => {
        window.clearInterval(id);
      };
    }
    startRef.current = null;
    return undefined;
  }, [active]);

  if (!active && everActiveRef.current) {
    return { percent: 100, stepLabel: "完成", etaSeconds: 0 };
  }
  if (!active) {
    return { percent: 0, stepLabel: "", etaSeconds: TOTAL_ESTIMATE_SECONDS };
  }
  return computeProgress(elapsed);
}
