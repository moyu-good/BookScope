import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { BookShelf, rememberImportSources } from "./BookShelf";
import { ReportPreview, type ReportPreviewState } from "./ReportPreview";
import { ReportHistoryModal, deleteReportHistoryEntry, loadReportHistory, saveReportHistory, type ReportHistoryEntry } from "./ReportHistory";
import { ReportCenter } from "./ReportCenter";
import type { SessionMetadata } from "./BookShelf";
import { AgentOrchestrate } from "./AgentOrchestrate";
import type { DrillInfo } from "./AgentOrchestrate";
import { Reader } from "./Reader";
import { bookScale } from "./bookScale";
import type { BookScale } from "./bookScale";
import { ScaleBanner } from "./ScaleBanner";
import { SpineWarmupBanner } from "./SpineWarmupBanner";
import type { SpineWarmupPhase } from "./SpineWarmupBanner";
import { ActionLedger } from "./ActionLedger";
import { CommitmentTracker } from "./CommitmentTracker";
import { StanceSubtext } from "./StanceSubtext";
import { AnnotatedReader } from "./AnnotatedReader";
import { ArgumentStructure } from "./ArgumentStructure";
import { CharacterArc } from "./CharacterArc";
import { CharacterFlow } from "./CharacterFlow";
import { CharacterGraph } from "./CharacterGraph";
import { VizFocusProvider } from "./viz/vizFocus";
import { CharacterVoice } from "./CharacterVoice";
import { ConsistencyScan } from "./ConsistencyScan";
import { RecallHub } from "./RecallHub";
import { ErrorBanner } from "./ErrorBanner";
import { ForeshadowArcs } from "./ForeshadowArcs";
import { NarrativeCurve } from "./NarrativeCurve";
import { Timeline } from "./Timeline";
import type { ApiError } from "./ErrorBanner";
import { HistoryPanel } from "./HistoryPanel";
import { appendEntry, newEntryId } from "./historyStorage";
import type { QAEntry } from "./historyStorage";
import { setAnnotationBackend } from "./annotationStore";
import { AccountStrip, AuthModal } from "./AuthGate";
import type { AuthUser, DeploymentMode } from "./authClient";
import {
  clearAuthToken,
  fetchMe,
  installAuthFetch,
  loadAuthToken,
  logout as logoutToken,
  probeDeployment,
} from "./authClient";
import { Onboarding } from "./Onboarding";
import { QuestionBreakdown } from "./QuestionBreakdown";
import { Recap } from "./Recap";
import { Dossier } from "./Dossier";
import { RedheadActionList } from "./RedheadActionList";
import { RedheadDependencyGraph } from "./RedheadDependencyGraph";
import { RedheadDocStructure } from "./RedheadDocStructure";
import { RedheadLevelConsistency } from "./RedheadLevelConsistency";
import { RedheadPolicyEvolution } from "./RedheadPolicyEvolution";
import { RedheadCloseReading } from "./RedheadCloseReading";
import { RedheadFormatCheck } from "./RedheadFormatCheck";
import { RedheadHardFacts } from "./RedheadHardFacts";
import { RedheadStakes } from "./RedheadStakes";
import { RedheadDocPanorama } from "./RedheadDocPanorama";
import { RedheadDossierPanorama } from "./RedheadDossierPanorama";
import { CharacterPanorama } from "./CharacterPanorama";
import { PersonDossierPanel } from "./PersonDossierPanel";
import { Overview } from "./Overview";
import { ScholarStancePanel } from "./ScholarStancePanel";
import { NarrativePanorama } from "./NarrativePanorama";
import { QualityPanorama } from "./QualityPanorama";
import { RelationshipTimeline } from "./RelationshipTimeline";
import { RevisionList } from "./RevisionList";
import type {
  Difficulty,
  QuestionProcessedState,
} from "./QuestionBreakdown";
import { RouteDecisionBanner } from "./RouteDecisionBanner";
import { SealMark } from "./SealMark";
import { Select } from "./ui/FormControls";
import { StudyCards } from "./StudyCards";
import { StyleIssues } from "./StyleIssues";
import { SubplotWeave } from "./SubplotWeave";
import { WritingTechnique } from "./WritingTechnique";
import type {
  RouteDecisionState,
  RouteType,
} from "./RouteDecisionBanner";
import { useUploadProgress } from "./uploadProgress";

// 演示模式（VITE_DEMO_MODE=1，发布到 GitHub Pages 的静态 demo）：
// 用打包好的真实样本、不连后端、不要 key，访客点开即看。
const DEMO = import.meta.env.VITE_DEMO_MODE === "1";

// ---------------------------------------------------------------------------
// 类型：与 bookscope.api.schemas 对齐
// ---------------------------------------------------------------------------

type Provider = "deepseek" | "anthropic";

interface UploadResponse {
  session_id: string;
  book_title: string;
  language: string;
  chunk_count: number;
  character_count: number;
  message: string;
}

/** 上传队列里的一条：一个文件 + 它自己的状态。多选 / 拖进来多本时逐条入库，
 *  各自显示等待 / 上传中 / 成功 / 失败，某条失败不连累其它。 */
type UploadItemStatus = "queued" | "uploading" | "done" | "error";
interface UploadItem {
  /** 队列内稳定 id（文件名可能重复，用它当 key 和定位） */
  id: string;
  file: File;
  /** 入库书名，从文件名去扩展名得来 */
  title: string;
  status: UploadItemStatus;
  /** 成功后的元数据 */
  result?: UploadResponse;
  /** 失败时的错误 */
  error?: ApiError;
}

let _uploadItemSeq = 0;
function makeUploadItem(file: File): UploadItem {
  _uploadItemSeq += 1;
  return {
    id: `${Date.now()}-${_uploadItemSeq}`,
    file,
    title: stripExt(file.name),
    status: "queued",
  };
}

/** 去掉文件扩展名当书名（六种支持的后缀都剥掉）。 */
function stripExt(name: string): string {
  return name.replace(/\.(epub|txt|pdf|docx|md|markdown)$/i, "");
}

interface Citation {
  chapter: number;
  snippet: string;
  verified?: boolean;
  /** 证据强度：逐字命中 / 诚实转述 / 未核验（BE verify_citations 给） */
  match_type?: "quote" | "paraphrase" | "none";
  /** 论断支撑度：撑得起 / 撑不起 / 未核（BE check-citations 给，答完自动补） */
  claim_support?: "supported" | "weak" | "unchecked";
}

interface AskResponse {
  answer: string;
  citations: Citation[];
  trace: Record<string, unknown>;
  book_session_id: string;
  /** 产生这条答案的问题——给导出用，存进 payload 保 robust（含历史回放） */
  question?: string;
}

// AgentLoop streaming events (与 bookscope/agent/events.py 对齐)
type LoopEventFE =
  | {
      type: "route_decision";
      iteration: 0;
      timestamp: number;
      route_type: RouteType;
      human_label: string;
      expected_duration_seconds_min: number;
      expected_duration_seconds_max: number;
    }
  | {
      type: "question_processed";
      iteration: 0;
      original: string;
      subquestions: string[];
      recommended_chapters: number[] | null;
      difficulty: Difficulty;
      duration_seconds: number;
    }
  | { type: "iteration_start"; iteration: number; elapsed_ms: number }
  | {
      type: "tool_use";
      tool_name: string;
      tool_input: Record<string, unknown>;
      tool_use_id: string | null;
      iteration: number;
      elapsed_ms: number;
    }
  | {
      type: "tool_result";
      tool_name: string;
      output_summary: string;
      status: "ok" | "error";
      attempt: number;
      elapsed_ms: number;
      error_message: string | null;
    }
  | { type: "format_retry"; retries_used: number; reason: string }
  | { type: "content_filter_retry"; retries_used: number }
  | {
      type: "final_answer";
      answer: string;
      citations: Citation[];
      iterations: number;
      duration_ms: number;
    }
  | {
      type: "error";
      error_type: string;
      message: string;
      duration_ms: number;
      partial_evidence?: {
        tool_name: string;
        input_summary: string;
        output_summary: string;
        status: "ok" | "error";
      }[];
    };

// ---------------------------------------------------------------------------
// API fetch helpers
// ---------------------------------------------------------------------------

async function parseError(resp: Response): Promise<ApiError> {
  try {
    const body = await resp.json();
    const detail = body?.detail;
    if (detail && typeof detail === "object" && "error_type" in detail) {
      return detail as ApiError;
    }
    return {
      error_type: `HTTP_${resp.status}`,
      message: typeof detail === "string" ? detail : JSON.stringify(body),
    };
  } catch {
    return { error_type: `HTTP_${resp.status}`, message: resp.statusText };
  }
}

/**
 * KG ingest 期间的增量事件（与 bookscope.agent.events.IngestEvent 对齐）。
 *
 * 6 个 event_type：
 * - ingest_started: 一上来 emit，带 total_batches；FE 用作进度分母
 * - kg_batch_started: 每个 batch 开始抽取
 * - kg_batch_completed: 每个 batch 抽完（无论命中缓存与否都会 emit）
 * - kg_cache_hit: batch 命中 batch 级缓存（batch_index !== null）
 *   或整本命中 book-level 缓存（batch_index === null）
 * - ingest_done: KG 抽取链路完成（流末尾会再追一帧 upload_complete）
 * - ingest_error: 抽取链路抛异常
 */
type IngestEventFE =
  | {
      event_type: "ingest_started";
      book_session_id: string;
      total_batches: number | null;
      batch_index: null;
      cached: false;
      error_message: null;
      timestamp: number;
    }
  | {
      event_type: "kg_batch_started" | "kg_batch_completed";
      book_session_id: string;
      total_batches: null;
      batch_index: number;
      cached: false;
      error_message: null;
      timestamp: number;
    }
  | {
      event_type: "kg_cache_hit";
      book_session_id: string;
      total_batches: null;
      batch_index: number | null;
      cached: true;
      error_message: null;
      timestamp: number;
    }
  | {
      event_type: "ingest_done";
      book_session_id: string;
      total_batches: null;
      batch_index: null;
      cached: false;
      error_message: null;
      timestamp: number;
    }
  | {
      event_type: "ingest_error";
      book_session_id: string;
      total_batches: null;
      batch_index: null;
      cached: false;
      error_message: string;
      timestamp: number;
    };

/** 流末尾追加的 ``upload_complete`` 帧 —— 与 ``UploadResponse`` 同形。 */
type UploadCompleteFrame = { event_type: "upload_complete" } & UploadResponse;

/** 流末尾追加的 ``upload_error`` 帧 —— ingest 阶段失败时携带 HTTP-翻译错误类型。 */
type UploadErrorFrame = {
  event_type: "upload_error";
  error_type: string;
  message: string;
  timestamp: number;
};

type UploadStreamEvent = IngestEventFE | UploadCompleteFrame | UploadErrorFrame;

/** UI 侧聚合的 ingest 进度状态 —— 直接由 SSE 事件折叠出来。 */
interface IngestProgressState {
  /** 总 batch 数；ingest_started 收到后填，book-level 命中时 0 */
  totalBatches: number;
  /** 已完成的 batch 数（包含 kg_batch_completed 和 book-level cache hit） */
  completedBatches: number;
  /** 命中缓存的 batch 数（含 book-level 整本命中算 1） */
  cacheHits: number;
  /** 是否已收到 ingest_done */
  done: boolean;
  /** 是否 book-level 整本命中（FE 显示"整本命中缓存，秒进"） */
  bookCacheHit: boolean;
}

/** ingest 进度的初始值 —— ingest_started 还没到时短暂用。 */
const INGEST_PROGRESS_INITIAL: IngestProgressState = {
  totalBatches: 0,
  completedBatches: 0,
  cacheHits: 0,
  done: false,
  bookCacheHit: false,
};

function reduceIngestProgress(
  prev: IngestProgressState,
  event: IngestEventFE,
): IngestProgressState {
  switch (event.event_type) {
    case "ingest_started":
      return {
        ...INGEST_PROGRESS_INITIAL,
        totalBatches: event.total_batches ?? 0,
      };
    case "kg_batch_completed":
      return { ...prev, completedBatches: prev.completedBatches + 1 };
    case "kg_cache_hit":
      if (event.batch_index === null) {
        // book-level 整本命中
        return {
          ...prev,
          bookCacheHit: true,
          cacheHits: prev.cacheHits + 1,
          completedBatches: prev.totalBatches,
        };
      }
      return { ...prev, cacheHits: prev.cacheHits + 1 };
    case "ingest_done":
      return { ...prev, done: true };
    case "ingest_error":
      // 错误状态由顶层 error banner 显示；这里仍标 done 让进度条停
      return { ...prev, done: true };
    default:
      return prev;
  }
}

/**
 * 上传书籍并以 SSE 流推送 KG ingest 进度事件。
 *
 * 末帧必为 ``upload_complete``（成功）或 ``upload_error``（ingest 失败）。
 * setup-time 错误（文件格式 / 空文件 / SDK 缺）仍走 HTTP 4xx，不进入流。
 */
async function* streamUploadBook(args: {
  file: File;
  bookTitle: string;
  language: string;
  provider: Provider;
  apiKey: string;
  model: string;
  baseUrl: string;
}): AsyncGenerator<UploadStreamEvent> {
  const fd = new FormData();
  fd.append("file", args.file);
  fd.append("book_title", args.bookTitle);
  fd.append("language", args.language);
  fd.append("provider", args.provider);
  fd.append("api_key", args.apiKey);
  if (args.model) fd.append("model", args.model);
  if (args.baseUrl) fd.append("base_url", args.baseUrl);

  const resp = await fetch("/api/books/upload/stream", {
    method: "POST",
    body: fd,
  });
  if (!resp.ok) throw await parseError(resp);
  if (!resp.body)
    throw { error_type: "NoStreamBody", message: "响应没有流式正文" };

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let eventType = "";
      const dataLines: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventType = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!eventType || dataLines.length === 0) continue;
      try {
        const data = JSON.parse(dataLines.join("\n"));
        if (eventType === "upload_complete" || eventType === "upload_error") {
          yield { ...data, event_type: eventType } as UploadStreamEvent;
        } else {
          yield { ...data, event_type: eventType } as IngestEventFE;
        }
      } catch {
        // 单帧解析失败不打断流
      }
    }
  }
}

async function* streamAskAgent(args: {
  question: string;
  sessionId: string;
  provider: Provider;
  apiKey: string;
  model: string;
  baseUrl: string;
}): AsyncGenerator<LoopEventFE> {
  const body: Record<string, unknown> = {
    question: args.question,
    book_session_id: args.sessionId,
    provider: args.provider,
    api_key: args.apiKey,
  };
  if (args.model) body.model = args.model;
  if (args.baseUrl) body.base_url = args.baseUrl;

  const resp = await fetch("/api/agent/ask/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  // setup-time 错误（404 / 400 / 422）走 HTTP status，没有流
  if (!resp.ok) throw await parseError(resp);
  if (!resp.body) throw { error_type: "NoStreamBody", message: "响应没有流式正文" };

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let eventType = "";
      const dataLines: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventType = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!eventType || dataLines.length === 0) continue;
      try {
        const data = JSON.parse(dataLines.join("\n"));
        yield { ...data, type: eventType } as LoopEventFE;
      } catch {
        // 单帧解析失败不打断流
      }
    }
  }
}

// ---------------------------------------------------------------------------
// 进度条目：三类
//   - iteration : 一轮的开头（组标题）
//   - tool      : 该轮里的某个 tool 调用（可能多个，并发）
//   - meta      : 重试 / 错误等顶层提示（独立成行）
// 同 iteration 的 tool 在视觉上共组缩进，体现并发
// ---------------------------------------------------------------------------

type ProgressItem =
  | { kind: "iteration"; iteration: number }
  | {
      kind: "tool";
      iteration: number | null;
      toolName: string;
      label: string;
      chapters: number[];
      query: string | null;
      status: "running" | "ok" | "error";
      errorMessage: string | null;
    }
  | { kind: "meta"; label: string; tone: "info" | "warn" };

interface ToolLabelInfo {
  label: string;
  chapters: number[];
  query: string | null;
}

/**
 * 把 ToolUseEvent.tool_input 翻译成展示用 label + 章节数组 + 查询关键词。
 *
 * 章节信息单独放进 chapters 字段，由 ProgressTimeline 用印章红徽章强调。
 * label 里只放上下文文案（动词 + tool 含义），不重复章节数字，避免噪声。
 */
function formatToolUseLabel(
  toolName: string,
  toolInput: Record<string, unknown>,
): ToolLabelInfo {
  if (toolName === "search_chunks") {
    const query =
      typeof toolInput.query === "string" && toolInput.query.length > 0
        ? toolInput.query
        : null;
    const scope = toolInput.chapter_scope;
    const chapters: number[] = [];
    if (
      Array.isArray(scope) &&
      scope.length === 2 &&
      typeof scope[0] === "number" &&
      typeof scope[1] === "number"
    ) {
      const [start, end] = scope as [number, number];
      if (start === end) chapters.push(start);
      else chapters.push(start, end);
    }
    const characterFilter = toolInput.character_filter;
    let label = query !== null ? `查 “${query}”` : "检索原文";
    if (
      Array.isArray(characterFilter) &&
      characterFilter.length > 0 &&
      typeof characterFilter[0] === "string"
    ) {
      label += ` · 限定 ${characterFilter.join(" / ")}`;
    }
    return { label, chapters, query };
  }

  if (toolName === "get_chapter_range") {
    const start =
      typeof toolInput.start_chapter === "number"
        ? toolInput.start_chapter
        : null;
    const end =
      typeof toolInput.end_chapter === "number" ? toolInput.end_chapter : null;
    const chapters: number[] = [];
    if (start !== null && end !== null) {
      if (start === end) chapters.push(start);
      else chapters.push(start, end);
    } else if (start !== null) chapters.push(start);
    return { label: "拉取章节原文", chapters, query: null };
  }

  if (toolName === "list_characters_in_chapter") {
    const ch =
      typeof toolInput.chapter === "number" ? toolInput.chapter : null;
    return {
      label: "列出登场角色",
      chapters: ch !== null ? [ch] : [],
      query: null,
    };
  }

  return { label: `调用 ${toolName}`, chapters: [], query: null };
}

/**
 * 把单条 LoopEvent 折叠进 progress 列表。
 *
 * - iteration_start: append 一条 iteration 标题
 * - tool_use: append 一条 tool（running）
 * - tool_result: 找最近一条同名 + running 的 tool，就地改 status；
 *   找不到就 append 一条孤立结果（事件丢帧时仍能展示）
 * - format_retry / content_filter_retry: append meta
 * - final_answer / error: 不入 timeline，调用方主区渲染
 */
function reduceProgress(
  prev: ProgressItem[],
  event: LoopEventFE,
): ProgressItem[] {
  switch (event.type) {
    case "iteration_start":
      return [...prev, { kind: "iteration", iteration: event.iteration }];

    case "tool_use": {
      const info = formatToolUseLabel(event.tool_name, event.tool_input ?? {});
      return [
        ...prev,
        {
          kind: "tool",
          iteration: event.iteration,
          toolName: event.tool_name,
          label: info.label,
          chapters: info.chapters,
          query: info.query,
          status: "running",
          errorMessage: null,
        },
      ];
    }

    case "tool_result": {
      const next = [...prev];
      for (let i = next.length - 1; i >= 0; i -= 1) {
        const item = next[i];
        if (
          item.kind === "tool" &&
          item.toolName === event.tool_name &&
          item.status === "running"
        ) {
          next[i] = {
            ...item,
            status: event.status,
            errorMessage:
              event.status === "error" ? event.error_message ?? null : null,
          };
          return next;
        }
      }
      return [
        ...prev,
        {
          kind: "tool",
          iteration: null,
          toolName: event.tool_name,
          label:
            event.status === "error"
              ? `${event.tool_name} 失败（第 ${event.attempt} 次）`
              : `${event.tool_name} 返回 · ${event.output_summary}`,
          chapters: [],
          query: null,
          status: event.status,
          errorMessage:
            event.status === "error" ? event.error_message ?? null : null,
        },
      ];
    }

    case "format_retry":
      return [
        ...prev,
        { kind: "meta", label: "输出格式不合规 · 重试一次", tone: "warn" },
      ];

    case "content_filter_retry":
      return [
        ...prev,
        {
          kind: "meta",
          label: `内容审核拦截 · 中性化重试（第 ${event.retries_used} 次）`,
          tone: "warn",
        },
      ];

    case "final_answer":
    case "error":
    case "route_decision":
    case "question_processed":
      // 这四类事件不入 timeline，由 runAsk 在外层另行处理
      return prev;
  }
}

// ---------------------------------------------------------------------------
// 组件
// ---------------------------------------------------------------------------

// localStorage 持久化 LLM 配置 —— 刷新页面不丢 key（仅本机存储不上送服务端）
const CONFIG_STORAGE_KEY = "bookscope_llm_config_v1";

interface PersistedConfig {
  provider: Provider;
  apiKey: string;
  model: string;
  baseUrl: string;
}

function loadPersistedConfig(): PersistedConfig | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(CONFIG_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedConfig>;
    if (
      typeof parsed.provider !== "string" ||
      typeof parsed.apiKey !== "string"
    ) {
      return null;
    }
    let model = parsed.model ?? "";
    let baseUrl = parsed.baseUrl ?? "";
    // 旧配置清洗:minimax 已彻底下线(2026-06-11),它的 base_url / 模型名(abab*)若残留在
    // localStorage 里,会让 DeepSeek 档带着失效端点跑——用户会看到"dk 在用 minimax 设置"。
    // 命中就清回官方默认(空 = 各后端默认)。
    if (/minimax/i.test(baseUrl) || /minimax|abab/i.test(model)) {
      model = "";
      baseUrl = "";
    }
    // provider 只认 deepseek / anthropic;存过别的(如旧 minimax)一律归 deepseek。
    const provider: Provider =
      parsed.provider === "anthropic" ? "anthropic" : "deepseek";
    return { provider, apiKey: parsed.apiKey, model, baseUrl };
  } catch {
    return null;
  }
}

function savePersistedConfig(config: PersistedConfig): void {
  if (typeof window === "undefined") return;
  try {
    // 别用空 key 覆盖已存的 key——防"加载失败/某次渲染 key 暂空 → 存空 → 把保存的 key 抹了"
    // 的竞态(用户反复反馈"默认保存的 api 又没了")。空 key 时若本地已有 key,直接不写。
    if (!config.apiKey) {
      const raw = window.localStorage.getItem(CONFIG_STORAGE_KEY);
      if (raw) {
        try {
          const ex = JSON.parse(raw) as Partial<PersistedConfig>;
          if (typeof ex.apiKey === "string" && ex.apiKey) return;
        } catch {
          /* 解析不了就当没有,照常写 */
        }
      }
    }
    window.localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(config));
  } catch {
    // 隐私模式 / 配额满 / SSR ——失败默默忽略不阻断主流程
  }
}

const APP_VERSION = "1.5.4";

// 主题(亮/暗,#20)持久化——默认亮(没存过/解析失败都按亮,不惊动老用户)。
// 应用在 <html data-theme>;index.css 的 [data-theme="dark"] 接管暗色 palette。
const THEME_STORAGE_KEY = "bookscope_theme_v1";
type ThemeMode = "light" | "dark";

function loadTheme(): ThemeMode {
  if (typeof window === "undefined") return "light";
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === "dark"
      ? "dark"
      : "light";
  } catch {
    return "light";
  }
}

function saveTheme(theme: ThemeMode): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* 隐私模式 / 配额满——忽略 */
  }
}

// 自动建议开关持久化——单独存一个布尔，默认开（没存过 / 解析失败都按开）。
const AUTO_SUGGEST_STORAGE_KEY = "bookscope_auto_suggest_v1";

function loadAutoSuggest(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(AUTO_SUGGEST_STORAGE_KEY) !== "0";
  } catch {
    return true;
  }
}

function saveAutoSuggest(enabled: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(AUTO_SUGGEST_STORAGE_KEY, enabled ? "1" : "0");
  } catch {
    // 隐私模式 / 配额满 / SSR ——失败默默忽略
  }
}

// 「笔记只留本地」开关持久化——托管版默认把笔记 / 标注存到账号（换设备能接着看）；
// 打开这个开关就只存在当前这台设备的浏览器里、不上账号。默认关（没存过 / 解析失败
// 都按关，即默认上账号同步）。本地版根本用不到账号，这个偏好对它没有意义。
const NOTES_LOCAL_ONLY_STORAGE_KEY = "bookscope_notes_local_only_v1";

function loadNotesLocalOnly(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(NOTES_LOCAL_ONLY_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function saveNotesLocalOnly(on: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(NOTES_LOCAL_ONLY_STORAGE_KEY, on ? "1" : "0");
  } catch {
    // 隐私模式 / 配额满 / SSR ——失败默默忽略
  }
}

// 卷宗（1.6 跨文件）持久化——选进卷宗的 session_id 一组，刷新不丢、跨视图共享。
// 跟 LLM 配置一个套路：纯本机存储，不上送服务端。
const DOSSIER_STORAGE_KEY = "bookscope_dossier_v1";

function loadDossier(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(DOSSIER_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is string => typeof x === "string");
  } catch {
    return [];
  }
}

function saveDossier(ids: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(DOSSIER_STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // 隐私模式 / 配额满 / SSR ——失败默默忽略
  }
}

export function App() {
  // 配置区 —— 从 localStorage 恢复，刷新页面不丢
  const persisted = loadPersistedConfig();
  const [provider, setProvider] = useState<Provider>(
    // 默认 deepseek——与 adapter 层默认（dependencies.py）和 NORTH_STAR
    // "国内 LLM 首选 DeepSeek" 对齐；已存配置的老用户不受影响
    persisted?.provider ?? "deepseek",
  );
  // 演示模式：强制给个占位 key（不看 persisted——本地存过空串也得放行），让所有
  // 「没填 key 不能用」的守卫通过、隐藏填 key 横幅。真实请求会带上它，但 demo
  // 拦截器只返打包样本、根本不看 key 值。
  const [apiKey, setApiKey] = useState(
    import.meta.env.VITE_DEMO_MODE === "1"
      ? "demo"
      : (persisted?.apiKey ?? ""),
  );
  const [model, setModel] = useState(persisted?.model ?? "");
  const [baseUrl, setBaseUrl] = useState(persisted?.baseUrl ?? "");
  // LLM 配置降级——收进设置抽屉，不占头版
  const [settingsOpen, setSettingsOpen] = useState(false);
  // 主题(亮/暗,#20):存 localStorage,应用在 <html data-theme>,暗色 palette 由 index.css 接管。
  const [theme, setTheme] = useState<ThemeMode>(loadTheme);
  useEffect(() => {
    saveTheme(theme);
    if (typeof document !== "undefined") {
      document.documentElement.setAttribute("data-theme", theme);
    }
  }, [theme]);
  // app-shell 当前主画布显示哪一件事（左栏导航切换）
  const [mode, setMode] = useState<
    | "library"
    | "overview"
    | "ask"
    | "annotate"
    | "graph"
    | "concept_graph"
    | "flow"
    | "reltime"
    | "chararc"
    | "charvoice"
    | "foreshadow"
    | "subplot"
    | "timeline"
    | "entity"
    | "pacing"
    | "narrative"
    | "consistency"
    | "argument"
    | "scholar_stance"
    | "style"
    | "recap"
    | "concept"
    | "motif"
    | "technique"
    | "cards"
    | "revision"
    | "dossier"
    | "redhead"
    | "redhead_actions"
    | "redhead_plain"
    | "redhead_stakes"
    | "redhead_hardfacts"
    | "redhead_formatcheck"
    | "redhead_panorama"
    | "redhead_dossier_panorama"
    | "char_panorama"
    | "person_dossier"
    | "plot_panorama"
    | "quality_panorama"
    | "redhead_depgraph"
    | "redhead_policy"
    | "redhead_level"
    | "meeting_ledger"
    | "meeting_stance"
    | "meeting_commitments"
  >("library");
  // 手机端左栏收成抽屉，这个控制开合
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // 读书优先 IA：进沉浸阅读器时为 true，整页渲染 Reader、不挂分析台外壳。
  const [readerOpen, setReaderOpen] = useState(false);

  // ── 托管版账号(1.6.2) ──────────────────────────────────────────────
  // local 模式这三个状态恒为初始值、不触发任何账号 UI;只有探测到 hosted 才激活。
  // deploymentMode: null=还没探测出来;探出来是 local / hosted。
  const [deploymentMode, setDeploymentMode] = useState<DeploymentMode | null>(null);
  // 当前登录用户;null=没登录。
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  // 启动那次"验明身份"是否跑完(避免没验完就闪一下登录弹窗)。
  const [authChecked, setAuthChecked] = useState(false);
  // 「笔记只留本地」偏好（默认关＝上账号同步）。持久化到 localStorage，刷新不丢。
  // 声明在这儿（挨着账号态）是因为下面切标注仓储的那段 effect 要用到它。
  const [notesLocalOnly, setNotesLocalOnly] = useState<boolean>(loadNotesLocalOnly);
  useEffect(() => {
    saveNotesLocalOnly(notesLocalOnly);
  }, [notesLocalOnly]);

  // 启动:先给 fetch 挂上令牌注入层(没令牌时是纯透传,local 零影响),再探测部署形态;
  // hosted 且本地有令牌就调 /auth/me 验,401 清掉过期令牌。local 直接当账号功能不存在。
  useEffect(() => {
    installAuthFetch();
    let cancelled = false;
    (async () => {
      const mode = await probeDeployment();
      if (cancelled) return;
      setDeploymentMode(mode);
      if (mode !== "hosted") {
        setAuthChecked(true);
        return;
      }
      // hosted:有令牌就验一次身份
      if (loadAuthToken()) {
        const me = await fetchMe();
        if (cancelled) return;
        if (me) setAuthUser(me);
        else clearAuthToken(); // 令牌过期 / 坏 → 清掉,回到未登录
      }
      if (!cancelled) setAuthChecked(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogout = useCallback(() => {
    logoutToken();
    setAuthUser(null);
  }, []);

  // 标注仓储据部署形态 + 登录态 + 用户偏好切底层（WP-reading-workspace Phase C-FE）：
  // hosted 且已登录、且没打开「只留本地」→ HostedAnnotationStore（走账号 DB、异步预热缓存）；
  // 其余（local 模式 / hosted 未登录 / 用户主动选了只留本地）→ LocalAnnotationStore（localStorage）。
  // 登出会把 authUser 置空 → 这里切回 local 并清掉 Hosted 缓存，不串账号。
  // 打开「只留本地」也切回 local：往后的笔记只进这台设备的浏览器，不上账号。
  // local 模式 deploymentMode 恒为 "local" → 永远只切成 local，Hosted 根本不实例化。
  useEffect(() => {
    setAnnotationBackend(
      deploymentMode === "hosted" && authUser !== null && !notesLocalOnly
        ? "hosted"
        : "local",
    );
  }, [deploymentMode, authUser, notesLocalOnly]);

  // 只有 hosted + 验过身份 + 没登录,才挂登录弹窗。
  const needsAuth =
    deploymentMode === "hosted" && authChecked && authUser === null;

  // 配置变化时同步写 localStorage
  useEffect(() => {
    savePersistedConfig({ provider, apiKey, model, baseUrl });
  }, [provider, apiKey, model, baseUrl]);

  // 上传区。queue 支持多选 / 拖拽进来多本，逐条入库；单本时也是一条的队列。
  const [queue, setQueue] = useState<UploadItem[]>([]);
  const [language, setLanguage] = useState("zh");
  const [uploading, setUploading] = useState(false);
  /** 正在上传的那条 item id（串行逐条传，进度条只跟当前这条） */
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  /** 最近一次 upload 的产出元数据；仅供贰区下方"已入库"提示行展示 */
  const [lastUpload, setLastUpload] = useState<UploadResponse | null>(null);
  /** 真实 KG ingest 进度（SSE 流接进来时实时更新）；null=未开始 / 走兜底曲线 */
  const [ingestProgress, setIngestProgress] = useState<IngestProgressState | null>(
    null,
  );

  // 当前选中的书 session（来自书柜点击或上传后自动选中）
  const [currentSession, setCurrentSession] = useState<SessionMetadata | null>(
    null,
  );

  // 手机物理返回键：无路由库，靠状态派生 + 单哨兵 pushState 让返回键
  // 先关最上层浮层（Reader→设置→侧栏→回书库），而不是直接退出站点。
  // 纯增量：不碰任何现有 setter 调用点，只在 back 时额外调一次 setter。
  const sentinelRef = useRef(false); // 当前是否持有一个哨兵历史条目
  const suppressRef = useRef(false); // 自触发 history.back() 引起的 popstate 要忽略
  const prevCountRef = useRef(0); // 上一轮活跃层数，用于检测开/关
  const hasSession = !!currentSession;
  useEffect(() => {
    // 当前活跃"层"数：每层都该被返回键关掉一层
    const activeCount =
      (readerOpen ? 1 : 0) +
      (settingsOpen ? 1 : 0) +
      (sidebarOpen ? 1 : 0) +
      (mode !== "library" && hasSession ? 1 : 0);

    if (activeCount > prevCountRef.current && !sentinelRef.current) {
      // 有层打开：压一个哨兵条目，返回键先消费它
      history.pushState({ bs: 1 }, "");
      sentinelRef.current = true;
    } else if (
      activeCount < prevCountRef.current &&
      activeCount === 0 &&
      sentinelRef.current
    ) {
      // UI 自己把所有层关了：主动 back 消费哨兵，保持历史栈平衡
      suppressRef.current = true;
      history.back();
    }
    prevCountRef.current = activeCount;
  }, [readerOpen, settingsOpen, sidebarOpen, mode, hasSession]);

  useEffect(() => {
    function onPop() {
      if (suppressRef.current) {
        // 自己调 history.back() 触发的 popstate，别再关东西
        suppressRef.current = false;
        sentinelRef.current = false;
        return;
      }
      if (!sentinelRef.current) return; // 没持哨兵，让浏览器默认行为走
      sentinelRef.current = false;
      // 按优先级关最上层
      if (readerOpen) setReaderOpen(false);
      else if (settingsOpen) setSettingsOpen(false);
      else if (sidebarOpen) setSidebarOpen(false);
      else if (mode !== "library") setMode("library");
      // 关一层后 state 变 → 上一个 effect 重跑 → 仍有层则重新 push 哨兵
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [readerOpen, settingsOpen, sidebarOpen, mode]);

  // 卷宗（1.6 跨文件）：选进一组 session_id，三个跨文件视图共享。落 localStorage 刷新不丢。
  const [dossierIds, setDossierIds] = useState<string[]>(loadDossier);
  useEffect(() => {
    saveDossier(dossierIds);
  }, [dossierIds]);
  const toggleDossier = useCallback((id: string) => {
    setDossierIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }, []);
  const clearDossier = useCallback(() => setDossierIds([]), []);

  // 当前书的体量估算（全书结构类分析大书会慢/贵/可能截断,提前提醒）。
  // 拿 TOC（每章 word_count，纯数据不调 LLM）算总字数;取不到就当不知道、不提醒。
  const [scale, setScale] = useState<BookScale | null>(null);
  useEffect(() => {
    if (!currentSession) {
      setScale(null);
      return;
    }
    let cancelled = false;
    setScale(null);
    (async () => {
      try {
        const resp = await fetch(`/api/sessions/${currentSession.session_id}/toc`);
        if (!resp.ok) return;
        const data = (await resp.json()) as { chapters: { word_count: number }[] };
        const chapters = data.chapters ?? [];
        if (cancelled || chapters.length === 0) return;
        const totalChars = chapters.reduce((s, c) => s + (c.word_count || 0), 0);
        setScale(bookScale(totalChars, chapters.length));
      } catch {
        /* 取不到 TOC 就不提醒，不打断分析 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentSession]);

  // ── 章脉后台预建（性能 Lever B 前端）─────────────────────────────────────
  // 超长文第一次打开要整本读一遍建章脉（可能十几分钟）。一进这本书的分析台（书已选
  // + 已填 key）就后台起预建，把等待挪到后台；建好后各整本书功能命中缓存秒出。
  //
  // phase：null=不显示（idle / error / 还没起）；building=在建；done=建好（短暂显示后收起）。
  const [warmupPhase, setWarmupPhase] = useState<SpineWarmupPhase | null>(null);
  // 去重：按 book_session_id 记"这本已经起过预建了"，换书才对新书再发一次。
  // 不放 state——它只是"发没发过"的账本，不该触发 render。
  const warmedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    // 换书 / 掉 key：先清掉上一本的横幅，别让旧状态串到新书上。
    setWarmupPhase(null);
    // demo 是静态样本、没真后端，别发预建；没选书 / 没 key 也不发。
    if (DEMO || !currentSession || !apiKey) return;
    const sessionId = currentSession.session_id;
    // 已对这本起过 → 不重发（防每次 render / 切 mode 重打）。换书 sessionId 变，新书没记过。
    if (warmedRef.current.has(sessionId)) return;
    warmedRef.current.add(sessionId);

    // model / base_url 口径要和别的整本书功能一致（detect-genre 同款内联）：
    // POST 和 GET 两边传同一个 model，空就都不传 → 后端按 provider 推同一个默认，
    // 否则缓存键 / 状态键对不上（后端硬约束）。
    const warmupModel = model.trim();
    const warmupBaseUrl =
      provider === "anthropic" ? "" : baseUrl.trim();

    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const stopPolling = () => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };

    const pollOnce = async () => {
      try {
        const params = new URLSearchParams({
          book_session_id: sessionId,
          provider,
        });
        if (warmupModel) params.set("model", warmupModel);
        const resp = await fetch(
          `/api/agent/prewarm-spine/status?${params.toString()}`,
        );
        if (!resp.ok || cancelled) return;
        const data = (await resp.json()) as {
          status: "idle" | "building" | "done" | "error";
          built_chapters?: number;
          total_chapters?: number;
        };
        if (cancelled) return;
        if (data.status === "building") {
          setWarmupPhase({
            status: "building",
            built: data.built_chapters ?? 0,
            total: data.total_chapters ?? 0,
          });
        } else if (data.status === "done") {
          setWarmupPhase({ status: "done" });
          stopPolling();
        } else {
          // idle / error：静默收起，不弹错（各 viz 还能按需现建，预建失败不该吓用户）。
          setWarmupPhase(null);
          stopPolling();
        }
      } catch {
        // 网络抖动：这轮跳过，下一轮再试；不改 phase、不弹错。
      }
    };

    (async () => {
      try {
        const resp = await fetch("/api/agent/prewarm-spine", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            book_session_id: sessionId,
            provider,
            api_key: apiKey,
            model: warmupModel || undefined,
            base_url: warmupBaseUrl || undefined,
          }),
        });
        if (!resp.ok || cancelled) return;
        const data = (await resp.json()) as {
          status: "cached" | "building" | "started";
        };
        if (cancelled) return;
        if (data.status === "cached") {
          // 已缓存：不用进度、直接当已就绪，横幅都不显（秒出，无需告知）。
          setWarmupPhase(null);
          return;
        }
        // building / started：进入轮询，每 ~4 秒查一次，直到 done / error / idle 停。
        setWarmupPhase({ status: "building", built: 0, total: 0 });
        timer = setInterval(() => void pollOnce(), 4000);
      } catch {
        // 起建失败：静默，不弹错（预建是后台事，各功能仍可按需现建）。
      }
    })();

    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [currentSession, apiKey, provider, model, baseUrl]);

  // 建好后横幅"全书已通读，分析秒出"短暂显示几秒就收起，不长期占地方。
  useEffect(() => {
    if (warmupPhase?.status !== "done") return;
    const t = setTimeout(() => setWarmupPhase(null), 4000);
    return () => clearTimeout(t);
  }, [warmupPhase]);

  // 选书时主动测一次题材（#14）：左栏 nav 按题材显隐（小说收起"思想·理论"组、
  // 理论书收起"人物"组）要 genre 先有值。以前 genre 只在用"论点结构"时才懒检测，
  // nav 显隐对刚选的书是哑的（全显）；这里换书就测一次填进 currentSession.genre。
  // 已分类的不重测（也不重复花钱，后端还有缓存兜一层）；没 apiKey 没法调 LLM，先不测。
  useEffect(() => {
    if (!currentSession || !apiKey) return;
    if (currentSession.genre) return; // 已有题材 → 不重测
    const sessionId = currentSession.session_id;
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/agent/detect-genre", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            book_session_id: sessionId,
            provider,
            api_key: apiKey,
            model: model.trim() || undefined,
            // effectiveBaseUrl 同款逻辑内联（anthropic 忽略 base_url）。
            base_url: provider === "anthropic" ? undefined : baseUrl.trim() || undefined,
          }),
        });
        if (!resp.ok || cancelled) return;
        const data = (await resp.json()) as { genre?: string };
        const g = (data.genre ?? "").trim();
        if (!g || cancelled) return;
        setCurrentSession((prev) =>
          prev && prev.session_id === sessionId ? { ...prev, genre: g } : prev,
        );
      } catch {
        /* 测不出题材就全显，不打断分析 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentSession, apiKey, provider, model, baseUrl]);

  // 选书后判一次"叙事型 / 论述型"(exp035),左栏据此只上对应一套镜头(叙事=人物+情节、论述=思想),
  // 根治俩关系图俩立场重叠。等 genre 先有值(公文 / 会议走自己的垂直组、不判 mode)。已判过不重判;
  // 判不出维持题材默认(genreVisibleGroups 里 mode 为空会退回按题材桶)。
  useEffect(() => {
    if (!currentSession || !apiKey) return;
    if (currentSession.mode) return; // 已判 → 不重判
    const genre = currentSession.genre ?? "";
    if (!genre) return; // 等题材先出;currentSession.genre 更新会让本 effect 重跑
    if (/公文|红头|会议|纪要/.test(genre)) return; // 垂直题材不需要 mode
    const sessionId = currentSession.session_id;
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/agent/detect-mode", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            book_session_id: sessionId,
            provider,
            api_key: apiKey,
            model: model.trim() || undefined,
            base_url: provider === "anthropic" ? undefined : baseUrl.trim() || undefined,
          }),
        });
        if (!resp.ok || cancelled) return;
        const data = (await resp.json()) as { mode?: string };
        const m = (data.mode ?? "").trim();
        if (!m || cancelled) return;
        setCurrentSession((prev) =>
          prev && prev.session_id === sessionId ? { ...prev, mode: m } : prev,
        );
      } catch {
        /* 判不出就维持题材默认,不打断 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentSession, apiKey, provider, model, baseUrl]);

  // 书柜刷新触发器：上传成功后 + 删除成功后递增
  const [shelfRefresh, setShelfRefresh] = useState(0);
  // 上传成功后让书柜自动选中新书
  const [pendingAutoSelectId, setPendingAutoSelectId] = useState<string | null>(
    null,
  );

  // 问书两条路：question=随便问（原 ask 路径，不动）；goal=给目标（agent 编排路径）
  const [askMode, setAskMode] = useState<"question" | "goal">("question");
  // 互相递：从功能视图「把它跟别的维度串起来看」过来时，给 AgentOrchestrate 预填的目标 + 令牌。
  const [goalPrefill, setGoalPrefill] = useState<{ goal: string; token: number } | null>(null);
  // 自动建议总开关（默认开、可关），持久化到 localStorage。
  const [autoSuggestEnabled, setAutoSuggestEnabled] = useState<boolean>(loadAutoSuggest);
  useEffect(() => {
    saveAutoSuggest(autoSuggestEnabled);
  }, [autoSuggestEnabled]);
  // 本书这次会话点过的不同功能（≥3 个就提示通盘检查）；换书清空。
  const [visitedFeatures, setVisitedFeatures] = useState<Set<Mode>>(new Set());
  // 两类自动建议各自的「这次会话先别再提」标记——关掉一次后这次会话不再弹同一类。
  const [dismissedSweepHint, setDismissedSweepHint] = useState(false);
  const [dismissedOpenHint, setDismissedOpenHint] = useState(false);

  // drill-into：四个要参数的功能（实体回溯 / 概念演进 / 母题追踪 / 声口一致）
  // 点「点开看完整 X 视图」时把参数预填进去并自动跑。token 每次递增触发那个视图的 effect。
  const [entityPrefill, setEntityPrefill] = useState<{ value: string; token: number } | null>(null);
  const [conceptPrefill, setConceptPrefill] = useState<{ value: string; token: number } | null>(null);
  const [motifPrefill, setMotifPrefill] = useState<{ value: string; token: number } | null>(null);
  const [voicePrefill, setVoicePrefill] = useState<{ value: string; token: number } | null>(null);

  // 问答区
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [progress, setProgress] = useState<ProgressItem[]>([]);
  // 路由决策快照 —— route_decision 事件到了就塞进去；final_answer 后停 tick
  const [routeDecision, setRouteDecision] =
    useState<RouteDecisionState | null>(null);
  const [finalDurationMs, setFinalDurationMs] = useState<number | null>(null);
  // 长题拆解快照 —— question_processed 事件到了就塞进去；下次问答 reset
  const [questionProcessed, setQuestionProcessed] =
    useState<QuestionProcessedState | null>(null);

  const [error, setError] = useState<ApiError | null>(null);

  // 历史面板刷新触发器：每写入新记录递增一次
  const [historyRefresh, setHistoryRefresh] = useState(0);

  // 每书自动出题：据这本书出的诊断题（按需 fetch，省成本）；换书清空
  const [bookQuestions, setBookQuestions] = useState<
    { type: string; question: string }[]
  >([]);
  const [bookQuestionsLoading, setBookQuestionsLoading] = useState(false);
  useEffect(() => {
    setBookQuestions([]);
    // 换书：通盘检查的足迹和两类建议的「这次别再提」标记都清空，重新开始。
    setVisitedFeatures(new Set());
    setDismissedSweepHint(false);
    setDismissedOpenHint(false);
  }, [currentSession?.session_id]);

  // 通盘检查足迹：每切到一个分析功能视图就记一笔（「问书」「书库」不算分析维度）。
  useEffect(() => {
    if (!currentSession) return;
    if (mode === "ask" || mode === "library") return;
    setVisitedFeatures((prev) => {
      if (prev.has(mode)) return prev;
      const next = new Set(prev);
      next.add(mode);
      return next;
    });
  }, [mode, currentSession]);

  // Onboarding 触发追踪：仅本次会话感知"是不是刚发生过"
  const [hasUploaded, setHasUploaded] = useState(false);
  const [hasSwitched, setHasSwitched] = useState(false);
  const uploadedSessionIdsRef = useRef<Set<string>>(new Set());

  // ErrorBanner 回调
  function handleRetry() {
    setError(null);
    if (currentSession && question.trim() && apiKey) {
      void runAsk();
    }
  }

  // 每书自动出题：点按钮才 fetch（省成本）；据整本书出书内专属诊断题
  async function generateBookQuestions() {
    if (!currentSession || !apiKey || bookQuestionsLoading) return;
    setBookQuestionsLoading(true);
    try {
      const body: Record<string, unknown> = {
        book_session_id: currentSession.session_id,
        provider,
        api_key: apiKey,
      };
      if (model.trim()) body.model = model.trim();
      if (effectiveBaseUrl()) body.base_url = effectiveBaseUrl();
      const resp = await fetch("/api/agent/suggest-questions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (resp.ok) {
        const data = (await resp.json()) as {
          questions: { type: string; question: string }[];
        };
        setBookQuestions(data.questions ?? []);
      }
    } catch {
      // 静默——通用诊断题兜底
    } finally {
      setBookQuestionsLoading(false);
    }
  }

  function handleRewrite() {
    setError(null);
    setQuestion("");
  }

  function handleNewSession() {
    // ErrorBanner 的"新建对话"语义：清掉当前问答区状态，但不清掉书柜选中
    setError(null);
    setQuestion("");
    setAnswer(null);
    setProgress([]);
    setRouteDecision(null);
    setFinalDurationMs(null);
    setQuestionProcessed(null);
  }

  function handleOpenSettings() {
    setError(null);
    setSettingsOpen(true);
  }

  function handleSelectHistory(entry: QAEntry) {
    if (!currentSession) return;
    setMode("ask");
    setError(null);
    setProgress([]);
    setRouteDecision(null);
    setFinalDurationMs(null);
    setQuestionProcessed(null);
    setQuestion(entry.question);
    setAnswer({
      answer: entry.answer,
      citations: entry.citations,
      trace: { from_history: true, created_at: entry.created_at },
      book_session_id: currentSession.session_id,
      question: entry.question,
    });
  }

  // 书柜回调：点 tab 切书 → 清空当前问答区
  const handleSelectShelfBook = useCallback((s: SessionMetadata) => {
    // 进门先落概览页(作者定"先看一张概览"),不再直接甩进问书。
    setMode("overview");
    setCurrentSession((prev) => {
      if (prev?.session_id === s.session_id) return prev;
      // 切到不同的书 → 清掉问答区
      setQuestion("");
      setAnswer(null);
      setProgress([]);
      setRouteDecision(null);
      setFinalDurationMs(null);
      setQuestionProcessed(null);
      setError(null);
      // 只在切到"不是本次会话刚上传的那本"时算 first_switch
      if (prev !== null && !uploadedSessionIdsRef.current.has(s.session_id)) {
        setHasSwitched(true);
      }
      return s;
    });
  }, []);

  // 书柜回调：删除某本书后通知，若删的是当前书则清空选中
  const handleDeletedShelfBook = useCallback(
    (deletedSessionId: string) => {
      setCurrentSession((prev) =>
        prev?.session_id === deletedSessionId ? null : prev,
      );
      if (lastUpload?.session_id === deletedSessionId) {
        setLastUpload(null);
      }
      // 触发书柜重新拉 list（数据库已删，再拉一次保险）
      setShelfRefresh((n) => n + 1);
    },
    [lastUpload],
  );

  const handleAutoSelected = useCallback(() => {
    setPendingAutoSelectId(null);
  }, []);

  // 注销账号（WP-reading-workspace Phase B）：DELETE /api/auth/me（CASCADE 连带删
  // 名下文档 + 标注，不可逆，二次确认在 MyDesk 里）。成功后清令牌 + 回未登录态 + 退回书库。
  // 失败抛出去给 MyDesk 显错。删完书柜数据也没了，顺手触发一次刷新。
  const handleDeleteAccount = useCallback(async () => {
    const resp = await fetch("/api/auth/me", { method: "DELETE" });
    // 204 删成功；404 = 账号早没了，也当成功（本地清干净对齐）。
    if (resp.status !== 204 && resp.status !== 404) {
      throw new Error(`注销失败（HTTP ${resp.status}）`);
    }
    clearAuthToken();
    setAuthUser(null);
    setCurrentSession(null);
    setMode("library");
    setShelfRefresh((n) => n + 1);
  }, []);

  // drill-into：agent 编排某个 step → 跳进该功能的完整视图。要参数的功能（实体 / 概念 /
  // 母题 / 声口）把参数预填进去并自动跑；不要参数的功能直接切过去（用户在那个视图点跑）。
  const drillInto = useCallback((drill: DrillInfo) => {
    const targetMode = FEATURE_TO_MODE[drill.feature];
    if (!targetMode) return;
    const prefillKey = FEATURE_PREFILL_KEY[drill.feature];
    if (prefillKey) {
      const value = (drill.params?.[prefillKey] ?? "").trim();
      const next = { value, token: Date.now() };
      if (drill.feature === "entity_recall") setEntityPrefill(next);
      else if (drill.feature === "concept_evolution") setConceptPrefill(next);
      else if (drill.feature === "motif") setMotifPrefill(next);
      else if (drill.feature === "character_voice") setVoicePrefill(next);
    }
    setMode(targetMode);
    setSidebarOpen(false);
  }, []);

  // 互相递 + 自动建议共用：带一个目标切到问书「给目标」模式并自动编排一次。
  const relayToGoal = useCallback((goal: string) => {
    const g = goal.trim();
    if (!g) return;
    setMode("ask");
    setAskMode("goal");
    setSidebarOpen(false);
    setGoalPrefill({ goal: g, token: Date.now() });
  }, []);

  // 读书优先 IA：从书架「读」门进沉浸阅读器（选中该书 + 整页渲染 Reader）。
  const openReader = useCallback((s: SessionMetadata) => {
    setCurrentSession(s);
    setReaderOpen(true);
    setSidebarOpen(false);
  }, []);

  /** 跨文本对照：先选一本，再点另一本触发对照报告下载。 */
  const [compareTarget, setCompareTarget] = useState<SessionMetadata | null>(null);
  /** 报告预览：出报告/对照报告后应用内 iframe 预览（可下载）。 */
  const [reportPreview, setReportPreview] = useState<ReportPreviewState | null>(null);
  /** 批量导入进度（书柜内进度条） */
  const [importProgress, setImportProgress] = useState<{ done: number; total: number; current: string | null } | null>(null);
  /** 报告历史（localStorage）+ 历史弹窗 */
  const [reportHistory, setReportHistory] = useState<ReportHistoryEntry[]>(() => loadReportHistory());
  const [historyOpen, setHistoryOpen] = useState(false);
  const [reportCenterOpen, setReportCenterOpen] = useState(false);
  const handleCompare = useCallback(
    async (s: SessionMetadata) => {
      if (!apiKey) {
        alert("先配置 LLM key（设置里）再出对照报告");
        return;
      }
      if (!compareTarget) {
        setCompareTarget(s);
        alert(`已选《${s.book_title}》为对照第一本，再点另一本书的「对照」`);
        return;
      }
      if (compareTarget.session_id === s.session_id) {
        alert("请选另一本不同的书");
        return;
      }
      const target = compareTarget;
      setCompareTarget(null);
      try {
        const resp = await fetch("/api/agent/cross-book/report", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            book_session_ids: [target.session_id, s.session_id],
            provider,
            api_key: apiKey,
            model: model.trim() || undefined,
            base_url: effectiveBaseUrl() || undefined,
          }),
        });
        if (!resp.ok) {
          let msg = `对照报告失败（${resp.status}）`;
          try {
            const d = (await resp.json()) as { detail?: { message?: string } };
            if (d?.detail?.message) msg = d.detail.message;
          } catch {
            /* 非 JSON 错误体，用默认文案 */
          }
          alert(msg);
          return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const entry: ReportHistoryEntry = {
          id: `cross-${Date.now()}`,
          title: `跨文本对照 · ${target.book_title || "A"} × ${s.book_title || "B"}`,
          type: "cross",
          sessionIds: [target.session_id, s.session_id],
          fileName: `${target.book_title || "A"}×${s.book_title || "B"}-对照报告.html`,
          createdAt: new Date().toISOString(),
        };
        saveReportHistory(entry);
        setReportHistory(loadReportHistory());
        setReportPreview({
          url,
          title: entry.title,
          fileName: entry.fileName,
          sessionIds: entry.sessionIds,
        });
      } catch {
        alert("对照报告失败：网络错误");
      }
    },
    [apiKey, provider, model, baseUrl, compareTarget],
  );

  /** 对照模式多选：一次生成多本书的跨文本对照报告（预览）。 */
  const handleCompareMany = useCallback(
    async (sessions: SessionMetadata[]) => {
      if (!apiKey) {
        alert("先配置 LLM key（设置里）再出对照报告");
        return;
      }
      if (sessions.length < 2) return;
      try {
        const resp = await fetch("/api/agent/cross-book/report", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            book_session_ids: sessions.map((x) => x.session_id),
            provider,
            api_key: apiKey,
            model: model.trim() || undefined,
            base_url: effectiveBaseUrl() || undefined,
          }),
        });
        if (!resp.ok) {
          let msg = `对照报告失败（${resp.status}）`;
          try {
            const d = (await resp.json()) as { detail?: { message?: string } };
            if (d?.detail?.message) msg = d.detail.message;
          } catch {
            /* 非 JSON 错误体，用默认文案 */
          }
          alert(msg);
          return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const titles = sessions.map((x) => x.book_title || "书").join(" × ");
        const entry: ReportHistoryEntry = {
          id: `cross-${Date.now()}`,
          title: `跨文本对照 · ${titles}`,
          type: "cross",
          sessionIds: sessions.map((x) => x.session_id),
          fileName: `跨文本对照-${titles.replace(/[\/:*?"<>|]/g, "_")}.html`,
          createdAt: new Date().toISOString(),
        };
        saveReportHistory(entry);
        setReportHistory(loadReportHistory());
        setReportPreview({
          url,
          title: entry.title,
          fileName: entry.fileName,
          sessionIds: entry.sessionIds,
        });
      } catch {
        alert("对照报告失败：网络错误");
      }
    },
    [apiKey, provider, model, baseUrl],
  );

  /** 簇总览报告：来源组所有书的聚合清单（纯聚合，秒出）。 */
  const handleClusterReport = useCallback(
    async (sessions: SessionMetadata[], clusterName: string) => {
      if (!apiKey) {
        alert("先配置 LLM key（设置里）再出簇总览");
        return;
      }
      if (sessions.length === 0) return;
      try {
        const resp = await fetch("/api/agent/cluster/report", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            book_session_ids: sessions.map((x) => x.session_id),
            cluster_name: clusterName,
            provider,
            api_key: apiKey,
            model: model.trim() || undefined,
            base_url: effectiveBaseUrl() || undefined,
          }),
        });
        if (!resp.ok) {
          let msg = `簇总览失败（${resp.status}）`;
          try {
            const d = (await resp.json()) as { detail?: { message?: string } };
            if (d?.detail?.message) msg = d.detail.message;
          } catch {
            /* 非 JSON 错误体 */
          }
          alert(msg);
          return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        setReportPreview({
          url,
          title: `簇总览 · ${clusterName}`,
          fileName: `簇总览-${clusterName.replace(/[\/:*?"<>|]/g, "_")}.html`,
          coverage: "full",
        });
      } catch {
        alert("簇总览失败：网络错误");
      }
    },
    [apiKey, provider, model, baseUrl],
  );

  /** 文档簇问答：对选中的多本书直接提问（跨书回答，锚到各书）。 */
  const handleAskBooks = useCallback(
    async (question: string, sessions: SessionMetadata[]): Promise<string> => {
      if (sessions.length < 2) throw new Error("至少选 2 本才能追问");
      if (!apiKey) throw new Error("先配置 LLM key（设置里）再追问");
      const resp = await fetch("/api/agent/cross-book/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          book_session_ids: sessions.map((x) => x.session_id),
          question,
          provider,
          api_key: apiKey,
          model: model.trim() || undefined,
          base_url: effectiveBaseUrl() || undefined,
        }),
      });
      if (!resp.ok) {
        let msg = `追问失败（${resp.status}）`;
        try {
          const d = (await resp.json()) as { detail?: { message?: string } };
          if (d?.detail?.message) msg = d.detail.message;
        } catch {
          /* 非 JSON 错误体 */
        }
        throw new Error(msg);
      }
      const data = (await resp.json()) as { answer?: string };
      return data.answer ?? "（无回答）";
    },
    [apiKey, provider, model, baseUrl],
  );

  /** 从报告历史重新打开：按类型调对应端点重新生成 → 预览。 */
  const handleReopenReport = useCallback(
    async (entry: ReportHistoryEntry) => {
      if (!apiKey) {
        alert("先配置 LLM key（设置里）再打开报告");
        return;
      }
      const common = {
        provider,
        api_key: apiKey,
        model: model.trim() || undefined,
        base_url: effectiveBaseUrl() || undefined,
      };
      try {
        let resp: Response;
        if (entry.type === "cross" && entry.sessionIds && entry.sessionIds.length >= 2) {
          resp = await fetch("/api/agent/cross-book/report", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...common, book_session_ids: entry.sessionIds }),
          });
        } else if (entry.sessionId) {
          resp = await fetch("/api/agent/book/report", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...common, book_session_id: entry.sessionId }),
          });
        } else {
          alert("这份历史记录缺少会话信息，无法重新打开");
          return;
        }
        if (!resp.ok) {
          let msg = `重新打开失败（${resp.status}）`;
          try {
            const d = (await resp.json()) as { detail?: { message?: string } };
            if (d?.detail?.message) msg = d.detail.message;
          } catch {
            /* 非 JSON 错误体 */
          }
          alert(msg);
          return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const coverage = resp.headers.get("X-Report-Coverage") ?? undefined;
        setHistoryOpen(false);
        setReportPreview({
          url,
          title: entry.title,
          fileName: entry.fileName,
          sessionId: entry.sessionId,
          sessionIds: entry.sessionIds,
          coverage,
        });
      } catch {
        alert("重新打开失败：网络错误");
      }
    },
    [apiKey, provider, model, baseUrl],
  );

  /** 重新生成更全版报告：结构版/部分版时再调端点，拉取最新覆盖。 */
  const handleRegenerateReport = useCallback(async (): Promise<void> => {
    const cur = reportPreview;
    if (!cur) return;
    if (!apiKey) {
      alert("先配置 LLM key（设置里）再重新生成");
      return;
    }
    const common = {
      provider,
      api_key: apiKey,
      model: model.trim() || undefined,
      base_url: effectiveBaseUrl() || undefined,
    };
    try {
      let resp: Response;
      if (cur.sessionIds && cur.sessionIds.length >= 2) {
        resp = await fetch("/api/agent/cross-book/report", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...common, book_session_ids: cur.sessionIds }),
        });
      } else if (cur.sessionId) {
        resp = await fetch("/api/agent/book/report", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...common, book_session_id: cur.sessionId }),
        });
      } else {
        return;
      }
      if (!resp.ok) {
        let msg = `重新生成失败（${resp.status}）`;
        try {
          const d = (await resp.json()) as { detail?: { message?: string } };
          if (d?.detail?.message) msg = d.detail.message;
        } catch {
          /* 非 JSON 错误体 */
        }
        alert(msg);
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const coverage = resp.headers.get("X-Report-Coverage") ?? undefined;
      URL.revokeObjectURL(cur.url); // 释放旧 blob
      setReportPreview({ ...cur, url, coverage });
    } catch {
      alert("重新生成失败：网络错误");
    }
  }, [reportPreview, apiKey, provider, model, baseUrl]);

  /** 报告内追问：调 /agent/ask（单书报告），答案展示在预览下方。 */
  const handleReportAsk = useCallback(
    async (question: string, preview: ReportPreviewState, chapter?: number) => {
      const common = {
        provider,
        api_key: apiKey,
        model: model.trim() || undefined,
        base_url: effectiveBaseUrl() || undefined,
      };
      let resp: Response;
      if (preview.sessionIds && preview.sessionIds.length >= 2) {
        resp = await fetch("/api/agent/cross-book/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...common, book_session_ids: preview.sessionIds, question }),
        });
      } else if (preview.sessionId) {
        resp = await fetch("/api/agent/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...common, book_session_id: preview.sessionId, question, chapter }),
        });
      } else {
        throw new Error("这份报告不支持追问");
      }
      if (!resp.ok) {
        let msg = `追问失败（${resp.status}）`;
        try {
          const d = (await resp.json()) as { detail?: { message?: string } };
          if (d?.detail?.message) msg = d.detail.message;
        } catch {
          /* 非 JSON 错误体，用默认文案 */
        }
        throw new Error(msg);
      }
      const data = (await resp.json()) as { answer?: string };
      return data.answer ?? "";
    },
    [apiKey, provider, model, baseUrl],
  );

  /** 批量导入本地书库（仅本地模式）：输入路径 → 后台逐本导入 → 轮询 → 刷新书柜。 */
  const handleImportFolder = useCallback(async () => {
    const folder = window.prompt("输入本地书库文件夹绝对路径（如 D:\\书）");
    if (!folder || !folder.trim()) return;
    const path = folder.trim();
    if (!apiKey) {
      alert("先配置 LLM key（设置里）再导入");
      return;
    }
    try {
      const resp = await fetch("/api/books/import-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          folder_path: path,
          provider,
          api_key: apiKey,
          model: model.trim() || undefined,
          base_url: effectiveBaseUrl() || undefined,
        }),
      });
      if (!resp.ok) {
        let msg = `导入失败（${resp.status}）`;
        try {
          const d = (await resp.json()) as { detail?: { message?: string } };
          if (d?.detail?.message) msg = d.detail.message;
        } catch {
          /* 非 JSON 错误体 */
        }
        alert(msg);
        return;
      }
      const data = (await resp.json()) as { job_id: string; total: number };
      setImportProgress({ done: 0, total: data.total, current: null });
      // 轮询直到完成
      const timer = setInterval(async () => {
        try {
          const st = (await (await fetch(`/api/books/import-folder/status?job_id=${data.job_id}`)).json()) as {
            status: string; done: number; total: number; current?: string | null;
            results?: { session_id?: string | null; file?: string; book_title?: string | null; error?: string | null }[];
            error?: string | null;
          };
          if (st.status === "running") {
            setImportProgress({ done: st.done, total: st.total, current: st.current ?? null });
            return;
          }
          clearInterval(timer);
          setImportProgress(null);
          if (st.status === "done") {
            // 记录导入来源（session_id -> 文件夹名），书柜分组用
            rememberImportSources(
              (st.results ?? [])
                .filter((r) => r.session_id && !r.error)
                .map((r) => ({ session_id: r.session_id!, source_folder: path })),
            );
            alert(`导入完成：${st.done}/${st.total} 本`);
            setShelfRefresh((n) => n + 1);
          } else {
            alert(`导入失败：${st.error || "未知"}`);
          }
        } catch {
          /* 网络抖动：下一轮再试 */
        }
      }, 1200);
    } catch {
      alert("导入失败：网络错误");
    }
  }, [apiKey, provider, model, baseUrl]);

  /** 出书鉴报告：/agent/book/report 拿 HTML → 下载。章脉没建过后端 404，弹提示。 */
  const openReport = useCallback(async (s: SessionMetadata) => {
    if (!apiKey) {
      alert("先配置 LLM key（设置里）再出报告");
      return;
    }
    try {
      const resp = await fetch("/api/agent/book/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          book_session_id: s.session_id,
          provider,
          api_key: apiKey,
          model: model.trim() || undefined,
          base_url: effectiveBaseUrl() || undefined,
        }),
      });
      if (!resp.ok) {
        let msg = `出报告失败（${resp.status}）`;
        try {
          const d = (await resp.json()) as { detail?: { message?: string } };
          if (d?.detail?.message) msg = d.detail.message;
        } catch {
          /* 非 JSON 错误体，用默认文案 */
        }
        alert(msg);
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const coverage = resp.headers.get("X-Report-Coverage") ?? undefined;
      const entry: ReportHistoryEntry = {
        id: `book-${s.session_id}-${Date.now()}`,
        title: `《${s.book_title || "本书"}》书鉴报告`,
        type: "book",
        sessionId: s.session_id,
        fileName: `${s.book_title || "book"}-书鉴报告.html`,
        createdAt: new Date().toISOString(),
      };
      saveReportHistory(entry);
      setReportHistory(loadReportHistory());
      setReportPreview({
        url,
        title: entry.title,
        fileName: entry.fileName,
        sessionId: s.session_id,
        coverage,
      });
      // 结构版：自动触发后台章脉预建（渐进交付，构建完可重新生成更全版）
      if (coverage === "structure") {
        void fetch("/api/agent/prewarm-spine", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            book_session_id: s.session_id,
            provider,
            api_key: apiKey,
            model: model.trim() || undefined,
            base_url: effectiveBaseUrl() || undefined,
          }),
        }).catch(() => { /* 预建失败不打扰 */ });
      }
    } catch {
      alert("出报告失败：网络错误");
    }
  }, [apiKey, provider, model, baseUrl]);

  function effectiveBaseUrl(): string {
    // 仅 deepseek 走 base_url（代理 / 其他 OpenAI 兼容 endpoint）；anthropic 后端会忽略
    if (provider === "anthropic") return "";
    return baseUrl.trim();
  }

  /** 传一条 item：跑 SSE 流，成功返 UploadResponse，失败抛 ApiError。
   *  进度回调让外层把当前这条的进度条折出来。 */
  async function uploadOne(item: UploadItem): Promise<UploadResponse> {
    setIngestProgress(INGEST_PROGRESS_INITIAL);
    let finalResult: UploadResponse | null = null;
    const stream = streamUploadBook({
      file: item.file,
      bookTitle: item.title,
      language,
      provider,
      apiKey,
      model: model.trim(),
      baseUrl: effectiveBaseUrl(),
    });
    for await (const event of stream) {
      if (event.event_type === "upload_complete") {
        // 末帧 upload_complete 含 session_id / chunk_count 等元数据
        // (剥掉 event_type 后即为 UploadResponse)
        const { event_type: _et, ...rest } = event as UploadCompleteFrame;
        finalResult = rest as UploadResponse;
      } else if (event.event_type === "upload_error") {
        // SSE 流内 ingest 失败 —— 翻译成 ApiError 抛出去
        throw {
          error_type: event.error_type,
          message: event.message,
        } as ApiError;
      } else {
        // ingest 增量事件 —— 折进进度状态
        setIngestProgress((prev) =>
          reduceIngestProgress(prev ?? INGEST_PROGRESS_INITIAL, event),
        );
      }
    }
    if (!finalResult) {
      throw {
        error_type: "UploadStreamIncomplete",
        message: "上传流提前结束，没有拿到 session_id",
      } as ApiError;
    }
    return finalResult;
  }

  /** 提交整个队列：逐条串行入库。某条失败不影响后面的——它自己标红，继续传下一条。
   *  串行而非并发：每条都是几十秒的 LLM 调用，并发会同时打爆用户的 key，
   *  且进度条是共享的一根，串行才说得清现在在传哪本。 */
  async function handleUpload(e: FormEvent) {
    e.preventDefault();
    if (uploading || !apiKey) return;
    // 只传还没成功的（queued / 之前失败过想重试的 error）
    const pending = queue.filter(
      (it) => it.status === "queued" || it.status === "error",
    );
    if (pending.length === 0) return;

    setError(null);
    setUploading(true);

    let lastOk: UploadResponse | null = null;
    let anyFailed = false;

    for (const item of pending) {
      setActiveItemId(item.id);
      setQueue((prev) =>
        prev.map((it) =>
          it.id === item.id ? { ...it, status: "uploading", error: undefined } : it,
        ),
      );
      try {
        const result = await uploadOne(item);
        lastOk = result;
        uploadedSessionIdsRef.current.add(result.session_id);
        setQueue((prev) =>
          prev.map((it) =>
            it.id === item.id ? { ...it, status: "done", result } : it,
          ),
        );
        // 每成功一本就刷一次书柜，让它即时出现在架上
        setShelfRefresh((n) => n + 1);
      } catch (err) {
        anyFailed = true;
        const apiErr =
          err && typeof err === "object" && "error_type" in err
            ? (err as ApiError)
            : { error_type: "UploadFailed", message: String(err) };
        setQueue((prev) =>
          prev.map((it) =>
            it.id === item.id ? { ...it, status: "error", error: apiErr } : it,
          ),
        );
      }
    }

    setActiveItemId(null);
    setIngestProgress(null);
    setUploading(false);

    // 至少成功一本：记最近一本、标已上传、自动选中最后成功的那本
    if (lastOk) {
      setLastUpload(lastOk);
      setHasUploaded(true);
      setPendingAutoSelectId(lastOk.session_id);
      setShelfRefresh((n) => n + 1);
    }
    // 全军覆没才弹顶层 banner；部分成功的失败项各自在队列里标红就够了
    if (anyFailed && !lastOk) {
      const firstErr = queue.find((it) => it.status === "error")?.error;
      if (firstErr) setError(firstErr);
    }
  }

  /** 把选中 / 拖进来的文件加进队列（去重靠文件名+大小，避免一次拖重）。 */
  function addFilesToQueue(files: File[]) {
    if (files.length === 0) return;
    setQueue((prev) => {
      const seen = new Set(prev.map((it) => `${it.file.name}::${it.file.size}`));
      const fresh = files
        .filter((f) => !seen.has(`${f.name}::${f.size}`))
        .map(makeUploadItem);
      return [...prev, ...fresh];
    });
  }

  function removeQueueItem(id: string) {
    setQueue((prev) => prev.filter((it) => it.id !== id));
  }

  async function handleAsk(e: FormEvent) {
    e.preventDefault();
    await runAsk();
  }

  async function runAsk() {
    if (!currentSession || !question.trim() || !apiKey) return;
    const sessionId = currentSession.session_id;
    setError(null);
    setAsking(true);
    setAnswer(null);
    setProgress([]);
    setRouteDecision(null);
    setFinalDurationMs(null);
    setQuestionProcessed(null);

    let finalAnswer: AskResponse | null = null;

    try {
      const stream = streamAskAgent({
        question: question.trim(),
        sessionId,
        provider,
        apiKey,
        model: model.trim(),
        baseUrl: effectiveBaseUrl(),
      });
      for await (const event of stream) {
        if (event.type === "route_decision") {
          // 路由命中——立刻把人话标签 + 预期时长塞进 banner，开计时
          setRouteDecision({
            routeType: event.route_type,
            humanLabel: event.human_label,
            expectedMinSec: event.expected_duration_seconds_min,
            expectedMaxSec: event.expected_duration_seconds_max,
            startedAtMs: Date.now(),
          });
        } else if (event.type === "question_processed") {
          // 长题拆解到了——把子问题列表 + 推荐章节 + 难度展示给用户
          setQuestionProcessed({
            original: event.original,
            subquestions: event.subquestions,
            recommendedChapters: event.recommended_chapters,
            difficulty: event.difficulty,
            durationSeconds: event.duration_seconds,
          });
        } else if (event.type === "final_answer") {
          const payload: AskResponse = {
            answer: event.answer,
            citations: event.citations,
            trace: {
              iterations: event.iterations,
              duration_ms: event.duration_ms,
            },
            book_session_id: sessionId,
            question: question.trim(),
          };
          finalAnswer = payload;
          setAnswer(payload);
          setFinalDurationMs(event.duration_ms);
          // 答案出来了——把进度里所有还在 running 的 tool 标 ok
          setProgress((prev) =>
            prev.map((p) =>
              p.kind === "tool" && p.status === "running"
                ? { ...p, status: "ok" as const }
                : p,
            ),
          );
        } else if (event.type === "error") {
          setError({
            error_type: event.error_type,
            message: event.message,
            partial_evidence: event.partial_evidence,
          });
        } else {
          setProgress((prev) => reduceProgress(prev, event));
        }
      }

      // 流正常结束后写一次历史
      if (finalAnswer) {
        const entry: QAEntry = {
          id: newEntryId(),
          question: question.trim(),
          answer: finalAnswer.answer,
          citations: finalAnswer.citations,
          created_at: new Date().toISOString(),
        };
        appendEntry(sessionId, entry);
        setHistoryRefresh((n) => n + 1);
      }

      // claim precision（exp-015 GO，"只核转述"形态）：答完自动核非逐字引用撑不撑得起
      // 论述。逐字引用天然可信不核。失败静默——答案照常显示，只是没支撑徽标。
      if (
        finalAnswer &&
        finalAnswer.citations.some((c) => c.match_type && c.match_type !== "quote")
      ) {
        const settled = finalAnswer;
        try {
          const ccBody: Record<string, unknown> = {
            answer: settled.answer,
            citations: settled.citations,
            provider,
            api_key: apiKey,
          };
          if (model.trim()) ccBody.model = model.trim();
          if (effectiveBaseUrl()) ccBody.base_url = effectiveBaseUrl();
          const ccResp = await fetch("/api/agent/check-citations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(ccBody),
          });
          if (ccResp.ok) {
            const ccData = (await ccResp.json()) as { citations: Citation[] };
            setAnswer((prev) =>
              prev && prev.answer === settled.answer
                ? { ...prev, citations: ccData.citations }
                : prev,
            );
          }
        } catch {
          // 核验失败静默
        }
      }
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setAsking(false);
    }
  }

  // 读书优先：进了沉浸阅读器就整页渲染 Reader，不挂分析台外壳。
  // 分析在阅读器内的「鉴」浮层就地跑（AnalysisOverlay），不跳回这里。
  if (readerOpen && currentSession) {
    return (
      <>
        {needsAuth && <AuthModal onAuthed={setAuthUser} />}
        <Reader
          sessionId={currentSession.session_id}
          bookTitle={currentSession.book_title}
          provider={provider}
          apiKey={apiKey}
          model={model}
          baseUrl={effectiveBaseUrl()}
          onExit={() => setReaderOpen(false)}
          onGoAnnotate={() => {
            setReaderOpen(false);
            setMode("annotate");
          }}
        />
      </>
    );
  }

  return (
    <div className="min-h-screen md:p-3">
      {needsAuth && <AuthModal onAuthed={setAuthUser} />}
      <MobileBar onOpenNav={() => setSidebarOpen(true)} />

      {sidebarOpen && (
        <button
          type="button"
          aria-label="关闭导航"
          onClick={() => setSidebarOpen(false)}
          className="md:hidden fixed inset-0 z-30"
          style={{
            background:
              "color-mix(in oklch, var(--color-ink) 22%, transparent)",
          }}
        />
      )}

      <div className="folio relative flex w-full min-h-screen overflow-hidden md:min-h-[calc(100vh-1.5rem)]">
        <Sidebar
        mode={mode}
        onMode={(m) => {
          setMode(m);
          setSidebarOpen(false);
        }}
        currentBook={currentSession}
        hasBook={!!currentSession}
        // genre hook：#14 选书时主动测一次题材填进 currentSession.genre，nav 据此显隐；
        // 没测出（空串/undefined）→ 全显（genreHighlightGroups 返 null）。
        genre={currentSession?.genre}
        bookMode={currentSession?.mode}
        open={sidebarOpen}
        onOpenSettings={() => {
          setSettingsOpen(true);
          setSidebarOpen(false);
        }}
        onRead={() => {
          // 常驻「读」：选中书直接进沉浸阅读器（退出回进来前的 mode，不强制经书库）。
          if (currentSession) openReader(currentSession);
        }}
        readerActive={readerOpen}
        authUser={authUser}
        onLogout={handleLogout}
        onDeleteAccount={handleDeleteAccount}
      />

      {/* 联动总线:分析台所有镜头包进 VizFocusProvider——一个镜头选中一个对象就广播,
          别的镜头订阅到、认得就聚焦/高亮(镜头互相说话)。onSwitchMode=setMode 让 setFocus 的
          switchTo 能把目标镜头顶到前面(如关系图点人→自动切到关系演变)。switchTo 是通用 string,
          setMode 要的是 mode 联合类型,cast 一层。Sidebar 在外层、用不着总线。 */}
      <VizFocusProvider onSwitchMode={(m) => setMode(m as typeof mode)}>
      <main className="flex-1 min-w-0 px-5 sm:px-8 lg:px-14 pt-[4.5rem] md:pt-12 pb-16">
        <div className="stagger max-w-4xl mx-auto">
          {settingsOpen && (
            <SettingsDrawer
              provider={provider}
              setProvider={setProvider}
              apiKey={apiKey}
              setApiKey={setApiKey}
              model={model}
              setModel={setModel}
              baseUrl={baseUrl}
              setBaseUrl={setBaseUrl}
              autoSuggestEnabled={autoSuggestEnabled}
              setAutoSuggestEnabled={setAutoSuggestEnabled}
              theme={theme}
              setTheme={setTheme}
              notesLocalOnly={notesLocalOnly}
              setNotesLocalOnly={setNotesLocalOnly}
              accountSyncAvailable={deploymentMode === "hosted"}
              onClose={() => setSettingsOpen(false)}
            />
          )}

          {error && (
            <ErrorBanner
              error={error}
              onClose={() => setError(null)}
              onRetry={handleRetry}
              onRewrite={handleRewrite}
              onNewSession={handleNewSession}
              onOpenSettings={handleOpenSettings}
            />
          )}

          {!apiKey && (
            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              className="mb-6 w-full text-left rounded-lg border border-[var(--color-seal)]/40 px-4 py-3 text-sm text-[var(--color-ink)] hover:border-[var(--color-seal)] transition-colors"
              style={{ background: "var(--color-seal-soft)" }}
            >
              先填一个 LLM 的 API key 才能用，点这里去
              <span style={{ color: "var(--color-seal)" }}>设置</span>
              （左栏底部，自带的 key、不上传服务器）。
            </button>
          )}

          {/* 主画布：一次只显示一件事 */}
          {(mode === "library" || !currentSession) && (
            <section>
              <CanvasHeader
                title="选一本书"
                subtitle="从书库挑一本，或上传新的。选定后左栏会列出能对它做的事。"
              />
              <Onboarding type="first_visit" triggered />
              <BookShelf
                activeSessionId={currentSession?.session_id ?? null}
                onSelect={handleSelectShelfBook}
                onRead={openReader}
                onReport={openReport}
                onCompare={handleCompare}
                onCompareMany={handleCompareMany}
                onAskBooks={handleAskBooks}
                onClusterReport={handleClusterReport}
                onReopenReport={(e) => void handleReopenReport(e)}
                onImportFolder={handleImportFolder}
                importProgress={importProgress}
                onOpenHistory={() => setHistoryOpen(true)}
                onOpenReportCenter={() => setReportCenterOpen(true)}
                onDeleted={handleDeletedShelfBook}
                refreshTrigger={shelfRefresh}
                pendingAutoSelectId={pendingAutoSelectId}
                onAutoSelected={handleAutoSelected}
              />
              {!currentSession && <CapabilityShowcase />}
              <Onboarding
                type="first_switch"
                triggered={hasSwitched}
                bookTitle={currentSession?.book_title ?? ""}
              />
              {DEMO ? (
                <div className="mt-6 pt-5 border-t border-[var(--color-rule)]">
                  <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
                    这是只读演示，预置了一本《三国演义》的真实分析结果。想分析
                    <strong>你自己的书</strong>（epub / txt / pdf / docx / md）？{" "}
                    <a
                      href="https://github.com/moyu-good/BookScope"
                      target="_blank"
                      rel="noreferrer"
                      className="text-[var(--color-seal)] underline"
                    >
                      克隆仓库本地运行
                    </a>
                    ，填上你自己的 LLM key 即可。
                  </p>
                </div>
              ) : (
                <div className="mt-6 pt-5 border-t border-[var(--color-rule)]">
                  <p className="text-sm text-[var(--color-ink-muted)] mb-3">
                    书架里没有？上传新的（epub / txt / pdf / docx / md），一次可选多本或直接拖进来：
                  </p>
                  <UploadForm
                    queue={queue}
                    onAddFiles={addFilesToQueue}
                    onRemoveItem={removeQueueItem}
                    language={language}
                    setLanguage={setLanguage}
                    uploading={uploading}
                    activeItemId={activeItemId}
                    session={lastUpload}
                    onSubmit={handleUpload}
                    canSubmit={
                      !!apiKey &&
                      queue.some(
                        (it) => it.status === "queued" || it.status === "error",
                      )
                    }
                    ingestProgress={ingestProgress}
                  />
                </div>
              )}
            </section>
          )}

          {currentSession && (
            <>
              {warmupPhase && WHOLE_BOOK_MODES.has(mode) && (
                <SpineWarmupBanner phase={warmupPhase} />
              )}
              {scale && WHOLE_BOOK_MODES.has(mode) && <ScaleBanner scale={scale} />}
              <div className={mode === "ask" ? "" : "hidden"}>
                <CanvasHeader
                  title="问书"
                  subtitle={`在读《${currentSession.book_title}》，问什么都拿原文回答，没出处的结论一概不给。`}
                />
                <Onboarding type="first_upload" triggered={hasUploaded} />
                {/* 随便问 ↔ 给目标：前者走原问答（不动）；后者让 agent 自己编排该跑哪几个分析 */}
                {!DEMO && (
                  <AskModeToggle mode={askMode} onChange={setAskMode} />
                )}
                {askMode === "question" || DEMO ? (
                  <>
                    {/* 自动建议·通盘检查：连点 ≥3 个不同功能、像在通盘审 → 温和提示编排总览 */}
                    {!DEMO &&
                      autoSuggestEnabled &&
                      !dismissedSweepHint &&
                      visitedFeatures.size >= 3 &&
                      !asking && (
                        <AgentSuggestHint
                          text="看着像在做通盘检查，要不要我编排一遍、给你一份带原文证据的总览？"
                          actionLabel="让 agent 编排总览"
                          onAccept={() =>
                            relayToGoal(
                              "把这本书通盘审一遍：人物、关系、节奏、伏笔、设定一致性这些维度串起来，给我一份带原文证据的总览。",
                            )
                          }
                          onDismiss={() => setDismissedSweepHint(true)}
                        />
                      )}
                    <SuggestedQuestions
                      bookTitle={currentSession.book_title}
                      disabled={asking}
                      onPick={(q) => setQuestion(q)}
                      bookQuestions={bookQuestions}
                      bookQuestionsLoading={bookQuestionsLoading}
                      onGenerateBookQuestions={generateBookQuestions}
                    />
                    <AskForm
                      question={question}
                      setQuestion={setQuestion}
                      asking={asking}
                      onSubmit={handleAsk}
                      canSubmit={!!question.trim() && !!apiKey}
                    />
                    {/* 自动建议·开放问法：当前问题像开放 / 跨维度 → 提示切「给目标」编排着跑 */}
                    {!DEMO &&
                      autoSuggestEnabled &&
                      !dismissedOpenHint &&
                      !asking &&
                      !answer &&
                      looksCrossDimensional(question) && (
                        <AgentSuggestHint
                          text="这问题挺开放的，要不要我规划着把相关的几个分析串起来跑、综合给你？"
                          actionLabel="切到「给目标」编排"
                          onAccept={() => relayToGoal(question)}
                          onDismiss={() => setDismissedOpenHint(true)}
                        />
                      )}
                    {(asking ||
                      progress.length > 0 ||
                      routeDecision ||
                      questionProcessed) && (
                      <ProgressTimeline
                        progress={progress}
                        done={!asking}
                        routeDecision={routeDecision}
                        questionProcessed={questionProcessed}
                        finalDurationMs={finalDurationMs}
                      />
                    )}
                    {answer && <AnswerBlock answer={answer} />}
                    <HistoryPanel
                      bookSessionId={currentSession.session_id}
                      onSelect={handleSelectHistory}
                      refreshTrigger={historyRefresh}
                    />
                  </>
                ) : (
                  <AgentOrchestrate
                    sessionId={currentSession.session_id}
                    provider={provider}
                    apiKey={apiKey}
                    model={model.trim()}
                    baseUrl={effectiveBaseUrl()}
                    onDrill={drillInto}
                    prefill={goalPrefill}
                  />
                )}
              </div>

              {/* 互相递：在某个功能视图角落给一个轻入口，把它跟别的维度串起来看（升 agent）。
                  单独渲染一次、据当前 mode 决定显不显，避免 22 个视图各塞一份。 */}
              {!DEMO && CROSS_DIM_GOAL[mode] && (
                <CrossDimRelay
                  onRelay={() => relayToGoal(CROSS_DIM_GOAL[mode]!)}
                />
              )}

              <div className={mode === "annotate" ? "" : "hidden"}>
                <CanvasHeader
                  title="批注"
                  subtitle="按选中的层通读全书，行间浮出带原文证据的朱砂批注（伏笔、矛盾、母题、人物），点开看支撑它的原文，跨章批注一键跳到牵连的另一处。想纯读、调排版，去顶部「读」。"
                />
                <AnnotatedReader
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              {/* 集合整合:人物那组(关系图/关系演变/人物弧线/声口)合成一个镜头;
                  下面 graph/reltime/chararc/charvoice 的 mode-div 暂留、可逆,导航已收成一个「人物」入口。 */}
              <div className={mode === "overview" ? "" : "hidden"}>
                {currentSession &&
                  (() => {
                    // 概览列的套餐 = 左栏可见组(按题材过滤,跟左栏一致),去掉"概览"自身。
                    const vis = genreVisibleGroups(currentSession.genre, currentSession.mode);
                    const gs = NAV_GROUPS.filter((g) => !vis || vis.has(g.key))
                      .map((g) => ({
                        key: g.key,
                        title: g.title,
                        modes: g.modes.filter((m) => m.id !== "overview"),
                      }))
                      .filter((g) => g.modes.length > 0);
                    return (
                      <Overview
                        bookTitle={currentSession.book_title}
                        genre={currentSession.genre}
                        groups={gs}
                        onPick={(id) => setMode(id as typeof mode)}
                      />
                    );
                  })()}
              </div>

              <div className={mode === "char_panorama" ? "" : "hidden"}>
                <CanvasHeader
                  title="人物"
                  subtitle="想读透一个人：在全局关系图上点他，下面的关系演变跟着聚焦到他，再往下看他的人物弧线、声口。顺着往下看，每一段单独点开生成。"
                />
                <CharacterPanorama
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              {/* 人物志:全员名册(章脉派生)+ 点人现跑精确分析(立场 Toulmin / 处境),都锚原文。
                  通用镜头(任何有人物的书都能开);史书将来额外加籍贯/官职/纪年字段。 */}
              <div className={mode === "person_dossier" ? "" : "hidden"}>
                <CanvasHeader
                  title="立场格局"
                  subtitle="把书里的主要人物一口气打在一张立场图上：横看戏份，纵看立场倾向，谁站哪边、谁有争议一眼看清。点开谁，才正反两面取原文、看他真正的争议度；戏份轻的在下面名册里搜。"
                />
                <PersonDossierPanel
                  key={currentSession.session_id}
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              {/* 集合整合:情节脉络那组(叙事曲线/叙事流/时间线/支线/伏笔)合成一个镜头(下面各 mode-div 暂留、可逆)。 */}
              <div className={mode === "plot_panorama" ? "" : "hidden"}>
                <CanvasHeader
                  title="情节脉络"
                  subtitle="一本书的来龙去脉：叙事曲线看节奏起伏，叙事流看人物线怎么穿过全书，时间线排出关键事件，再往下看支线和伏笔。顺着往下看，每一段单独点开生成。"
                />
                <NarrativePanorama
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              {/* 集合整合:质量·写作那组(一致性 / 写作手法 / 文体体检 / 改稿清单 / 知识卡片)合成一个镜头(下面各 mode-div 暂留、可逆)。 */}
              <div className={mode === "quality_panorama" ? "" : "hidden"}>
                <CanvasHeader
                  title="质量 · 写作"
                  subtitle="通读一遍写作质量：设定一致性、写作手法、文体体检各扫各的问题，改稿清单把要改的收在一起带走，知识卡片留住要点。顺着往下看，每一段单独点开生成。"
                />
                <QualityPanorama
                  sessionId={currentSession.session_id}
                  bookTitle={currentSession.book_title}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "graph" ? "" : "hidden"}>
                <CanvasHeader
                  title="关系图"
                  subtitle="谁和谁、什么关系，切人物 / 概念两种单位看，每条边都点得到原文。"
                />
                <CharacterGraph
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "concept_graph" ? "" : "hidden"}>
                <CanvasHeader
                  title="概念关系图"
                  subtitle="书里的核心概念怎么勾连：定义 / 包含 / 对立 / 因果，每条连线都点得到原文。"
                />
                <CharacterGraph
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                  defaultUnit="concept"
                />
              </div>

              <div className={mode === "reltime" ? "" : "hidden"}>
                <CanvasHeader
                  title="关系演变"
                  subtitle="给关系网加一根时间轴：拖到第几章看那一刻谁和谁多亲近，或选一对人看关系怎么一章章走到这一步，每个转折钉在原文。"
                />
                <RelationshipTimeline
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "flow" ? "" : "hidden"}>
                <CanvasHeader
                  title="叙事流"
                  subtitle="每人一条横线穿过全书：同章同场聚成束、退场线止。一眼看见谁何时入场、哪几章是群戏，点束看原文。"
                />
                <CharacterFlow
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "chararc" ? "" : "hidden"}>
                <CanvasHeader
                  title="人物弧线"
                  subtitle="给主要角色画两条曲线：戏份密度看谁何时主导这本书，处境升降看谁过得顺不顺。渐变写成平滑爬升、硬扳写成直角拐弯，点起伏点看原文。"
                />
                <CharacterArc
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "charvoice" ? "" : "hidden"}>
                <CanvasHeader
                  title="声口一致"
                  subtitle="给一个角色归拢他全书的对白，刻画说话的腔调，再标出哪几句「不像他说的」。合理的剧情驱动口吻变化不报，每条挂原文，你自己判断。"
                />
                <CharacterVoice
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                  prefill={voicePrefill}
                />
              </div>

              <div className={mode === "foreshadow" ? "" : "hidden"}>
                <CanvasHeader
                  title="伏笔回收"
                  feature="foreshadow"
                  subtitle="每条伏笔从埋点章拱到回收点章画一道弧，埋了没回收的画成灰虚线悬空，一眼挑出没填的坑，点弧看两端原文。"
                />
                <ForeshadowArcs
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "subplot" ? "" : "hidden"}>
                <CanvasHeader
                  title="支线编织"
                  feature="subplot"
                  subtitle="每条情节支线一条横向泳道：活跃段亮、休眠段灰断，两条线同章交汇画连接节点。一眼看见哪条支线断更太久、哪几章是多线交汇的高潮，点活跃段 / 交汇看原文。"
                />
                <SubplotWeave
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "timeline" ? "" : "hidden"}>
                <CanvasHeader
                  title="时间线"
                  feature="timeline"
                  subtitle="多线并进、倒叙插叙，都理清真正的先后顺序，每件事都能翻到原文。"
                />
                <Timeline
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "entity" ? "" : "hidden"}>
                <CanvasHeader
                  title="全书回溯"
                  feature="entity"
                  subtitle="追一个词在全书的踪迹——人 / 物 / 地点、概念、还是母题，选一个追什么，回溯它每次出现：在哪章、怎么体现、被怎么用，每处带原文。"
                />
                <RecallHub
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                  entityPrefill={entityPrefill}
                  conceptPrefill={conceptPrefill}
                  motifPrefill={motifPrefill}
                />
              </div>

              <div className={mode === "recap" ? "" : "hidden"}>
                <CanvasHeader
                  title="前情回顾"
                  feature="recap"
                  subtitle="读到第几章告诉我，回顾到此为止的前情，后文绝不剧透（模型根本看不到后文）。"
                />
                <Recap
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "narrative" ? "" : "hidden"}>
                <CanvasHeader
                  title="叙事曲线"
                  feature="narrative"
                  subtitle="逐章数事件数+转折数,看整本书哪几章戏多哪几章是转折,点章看这章发生了什么。"
                />
                <NarrativeCurve
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "consistency" ? "" : "hidden"}>
                <CanvasHeader
                  title="设定一致性"
                  feature="consistency"
                  subtitle="扫全书前后矛盾，每条两处对照原文，编出来的会被滤掉。"
                />
                <ConsistencyScan
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "argument" ? "" : "hidden"}>
                <CanvasHeader
                  title="论点结构"
                  feature="argument"
                  subtitle="拆这本书的论证骨架：作者主张了什么、靠什么撑，每条钉在原文。"
                />
                <ArgumentStructure
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              {/* 学者立场谱:理论书专属镜头。把书里对话的学者按本书核心争论摆上发散轴,点人看原文取证。
                  非理论书靠后端 scanned=false / 空学者集优雅退场。换书由 key 重挂。 */}
              <div className={mode === "scholar_stance" ? "" : "hidden"}>
                <CanvasHeader
                  title="学者立场谱"
                  subtitle="看这本书在跟哪些思想家对话：先理出它自己的核心争论，再把书里引到的学者按原文摆到争论的某一极，谁偏哪头一眼看清。点开谁，看书里怎么刻画他，每句都能核回原文。"
                />
                <ScholarStancePanel
                  key={currentSession.session_id}
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "technique" ? "" : "hidden"}>
                <CanvasHeader
                  title="写作手法"
                  feature="technique"
                  subtitle="看作者怎么写：论证、结构、铺陈、用语的手法，每条配原文例子，学手艺。"
                />
                <WritingTechnique
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "cards" ? "" : "hidden"}>
                <CanvasHeader
                  title="知识卡片"
                  feature="cards"
                  subtitle="据书出知识点卡，每张一道启发自测题，先自己想，再翻看解释和原文。"
                />
                <StudyCards
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "style" ? "" : "hidden"}>
                <CanvasHeader
                  title="文体体检"
                  feature="style"
                  subtitle="扫用词重复、视角越界、支线失踪，保守只报清楚的，每条钉原文，编的滤掉。"
                />
                <StyleIssues
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "revision" ? "" : "hidden"}>
                <CanvasHeader
                  title="改稿清单"
                  subtitle="把扫出的矛盾、断伏笔、塌节奏、文体毛病攒成一份带原文的修改清单，逐条勾「待改 / 已改 / 不改」，改完导出带走。核不过原文的发现不进清单。"
                />
                <RevisionList
                  sessionId={currentSession.session_id}
                  bookTitle={currentSession.book_title}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              {/* 单份公文全景:把读懂一份公文的几件事合成一个镜头(集合整合,1.6.x)。
                  下面那 6 个 redhead 单份 mode-div 暂留(可逆),导航已收成这一个「公文全景」入口。 */}
              <div className={mode === "redhead_panorama" ? "" : "hidden"}>
                <CanvasHeader
                  title="公文全景"
                  subtitle="读懂一份红头文件不用在几件功能间来回跳:结构、逐条精读、利害与风向、要点、办事清单、规范性自检顺着往下读,顶部点一下跳到那段。每段各自点「生成」,不一次全跑。"
                />
                <RedheadDocPanorama
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "redhead" ? "" : "hidden"}>
                <CanvasHeader
                  title="公文结构"
                  subtitle="整份公文的骨架鸟瞰：发文字号、发文机关、成文日期等头要素齐不齐（对照公文格式标准看缺项），再加这份公文多大分量、能管到谁、会不会被上位文件盖过的效力研判。想逐条吃透每一条，去「逐条精读」。适合党政公文 / 红头文件。"
                />
                <RedheadDocStructure
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                  onJumpToCloseReading={() => setMode("redhead_plain")}
                />
              </div>

              <div className={mode === "redhead_actions" ? "" : "hidden"}>
                <CanvasHeader
                  title="办事清单"
                  subtitle="把一份红头文件拆成一张能勾的待办清单：每条说清做什么、谁去做、到几号、凭哪份上位文件，硬要求排最前，每条钉在原文。读完一份公文照着挨条办就行。适合党政公文 / 红头文件。"
                />
                <RedheadActionList
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                  onJumpToFacts={() => setMode("redhead_hardfacts")}
                />
              </div>

              <div className={mode === "redhead_plain" ? "" : "hidden"}>
                <CanvasHeader
                  title="逐条精读"
                  subtitle="一条一条把红头文件吃透，三件事一次看全。一是大白话：「应当于三十日内予以办结」就是「三十天内得办完」，碰到「原则上同意」留了口子、「研究研究」约等于不办、「由相关部门认定」真规则在别人手里，这类看着懂其实没懂的话还点破弦外之意。二是结构标签：这条是硬要求还是软倡导、谁负责、到几号、依据哪份上位文件。三是生词随手点开当场解释。背后原文核得到才盖「鉴」印，只忠实转述、不替你脑补。适合党政公文 / 红头文件。"
                />
                <RedheadCloseReading
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                  onJumpToStructure={() => setMode("redhead")}
                />
              </div>

              <div className={mode === "redhead_stakes" ? "" : "hidden"}>
                <CanvasHeader
                  title="利害与风向"
                  subtitle="说一句你是谁，先把这份公文里跟你直接相关的条款圈出来，再把它藏着的机会（可争取的红利）和风险（暴露面 / 代价）挑出来，每条标含金量（真金白银 / 有条件 / 空头倡导）、钉原文；再研判它透出的政策风向（弦外之音），标研判、不当成核实的事实。不填身份也能看一份通用利害。适合党政公文 / 红头文件。"
                />
                <RedheadStakes
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "redhead_hardfacts" ? "" : "hidden"}>
                <CanvasHeader
                  title="要点提取"
                  subtitle="把一份红头文件里所有钉死的硬信息抠出来：金额、比例、期限、门槛、数量、适用范围、生效废止，逐条列清并标出处，省得自己在长文里翻。时间类的还能切到「时序视图」按先后排成一条线。适合党政公文 / 红头文件。"
                />
                <RedheadHardFacts
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "redhead_formatcheck" ? "" : "hidden"}>
                <CanvasHeader
                  title="规范性自检"
                  subtitle="拿一份红头文件对照公文格式标准逐项核：发文字号、发文机关署名、成文日期、印章这些要素齐不齐、规不规范，缺的、不合规的列出来，每条说清依的哪条标准。适合党政公文 / 红头文件。"
                />
                <RedheadFormatCheck
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              {/* 1.7 会议·行动项台账（单份文档，跟单份公文功能同一层 currentSession 守卫内）。
                  genre=会议 时这组自动显示 + 突出；其余题材下仍留作手动入口，任何文档都能点进来试。 */}
              <div className={mode === "meeting_ledger" ? "" : "hidden"}>
                <CanvasHeader
                  title="行动项台账"
                  subtitle="一份会议记录精读一次，把这场会派下去的活列成一张能勾的台账：每条说清做什么、谁负责、几号前办完、落实哪条决议，标含金量（真金白银 / 有条件兑现 / 空头表态）、钉原文。没人接、没定时限的活排最前。填上名字就只看派到你头上的那几条。逐字稿、纪要都能读。"
                />
                <ActionLedger
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              {/* 1.7 会议·立场与弦外（单份文档，跟行动项台账同一层 currentSession 守卫内）。
                  整块是评估层（标研判、不盖鉴印），跟证据层功能视觉刻意两样。 */}
              <div className={mode === "meeting_stance" ? "" : "hidden"}>
                <CanvasHeader
                  title="立场与弦外"
                  subtitle="会议里大家心里怎么想，常不写在脸上：「再研究研究」往往是不想办，「我理解但是」往往是软反对。这块替你挖字面底下的真实态度——谁真同意、谁附条件、谁嘴上应付实则拖延、谁在打太极，每条钉发言原话、标把握。读出来的是研判不是核实结论，对不对你看着原话自己判。大家是真一致、没有暗流也会明说是好事。只读逐字稿；纪要会建议你传逐字稿。"
                />
                <StanceSubtext
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>
            </>
          )}

          {/* ── 卷宗 + 跨文件视图（1.6 红头文件·跨文件层）──
              不挂在「案上当前书」下：跨文件功能认的是一组 session（卷宗），
              跟单份功能正交。三视图都至少要 2 份才跑（组件内守卫 + 入口提示）。 */}
          <div className={mode === "dossier" ? "" : "hidden"}>
            <CanvasHeader
              title="卷宗"
              subtitle="从书库已上传的文档里多选一组、归成一份卷宗：三个跨文件视图（依据链网 / 政策演变 / 上下级一致性）都跑这一组。挑相关的几份（如一份上位规定 + 几份配套实施件），至少 2 份。选中状态本机保存，刷新不丢。"
            />
            <Dossier
              selectedIds={dossierIds}
              onToggle={toggleDossier}
              onClear={clearDossier}
              refreshTrigger={shelfRefresh}
              onOpenView={(v) => setMode(v)}
              onGoUpload={() => setMode("library")}
            />
          </div>

          {/* 集合整合:跨文件三视图(依据链网/政策演变/上下级)合成一个「卷宗全景」镜头
              (下面各 mode-div 暂留、可逆)。先在「卷宗」选一组≥2份再进。 */}
          <div className={mode === "redhead_dossier_panorama" ? "" : "hidden"}>
            <CanvasHeader
              title="卷宗全景"
              subtitle="一份卷宗里多份公文之间的关系：依据链网看谁依据谁，政策演变按时间看怎么改，上下级一致性勘对上位和下位。顺着往下看，每一段单独点开生成。先在「卷宗」里选一组（至少 2 份）。"
            />
            <RedheadDossierPanorama
              bookSessionIds={dossierIds}
              provider={provider}
              apiKey={apiKey}
              model={model}
              baseUrl={effectiveBaseUrl()}
            />
          </div>

          <div className={mode === "redhead_depgraph" ? "" : "hidden"}>
            <CanvasHeader
              title="依据链网"
              subtitle="把一卷宗里好几份公文的关系画成一张有向网：谁依据谁、谁落实谁、新文件废了哪份旧的、机关之间谁管谁。文件按层级依据分层排，关系全从原文锚出来。先去「卷宗」选一组（≥2 份）。适合一组相关的党政公文 / 红头文件。"
            />
            <RedheadDependencyGraph
              bookSessionIds={dossierIds}
              provider={provider}
              apiKey={apiKey}
              model={model}
              baseUrl={effectiveBaseUrl()}
            />
          </div>

          <div className={mode === "redhead_policy" ? "" : "hidden"}>
            <CanvasHeader
              title="政策演变"
              subtitle="把一卷宗里好几份公文按成文日期排成一条线：哪份先出、改了什么、再哪份接着改，看一项政策怎么一步步演变到现在，每阶段钉一句原话。可只盯一个主题排。先去「卷宗」选一组（≥2 份）。适合一组同主题、有先后的党政公文。"
            />
            <RedheadPolicyEvolution
              bookSessionIds={dossierIds}
              provider={provider}
              apiKey={apiKey}
              model={model}
              baseUrl={effectiveBaseUrl()}
            />
          </div>

          <div className={mode === "redhead_level" ? "" : "hidden"}>
            <CanvasHeader
              title="上下级一致性"
              subtitle="把卷宗里上位文件和下位文件并排勘对，挑出对不上的地方：走样、加码、漏落实，每处上下两栏对照、各钉原话。需要卷宗里有明确上下级关系的公文（上位规定 + 下位实施件）。先去「卷宗」选一组（≥2 份）。"
            />
            <RedheadLevelConsistency
              bookSessionIds={dossierIds}
              provider={provider}
              apiKey={apiKey}
              model={model}
              baseUrl={effectiveBaseUrl()}
            />
          </div>

          {/* 1.7 会议·跨会承诺追踪（杀手价值）。跟跨文件视图同一层：吃的是一组会议（卷宗），
              不挂在「案上当前书」下。至少 2 场会才跑（组件内守卫 + 入口提示）。 */}
          <div className={mode === "meeting_commitments" ? "" : "hidden"}>
            <CanvasHeader
              title="跨会承诺追踪"
              subtitle="把同一条线上的好几场会摆一起，沿时间线追每条承诺兑现没：谁在哪场会答应了什么，到后来的会做了没。逾期、没兑现的捞最前，点开看是哪场会承诺的、哪场坐实的，都钉原文。判不出兑现没就标进行中 / 未知，绝不替它猜成做完了。先去「卷宗」选一组会（≥2 场），如同一项目的几次周会。"
            />
            <CommitmentTracker
              bookSessionIds={dossierIds}
              provider={provider}
              apiKey={apiKey}
              model={model}
              baseUrl={effectiveBaseUrl()}
            />
          </div>

          <Footer />
        </div>
      </main>
      {reportCenterOpen && (
        <ReportCenter
          onOpenReport={(s) => void openReport(s)}
          onReopen={(e) => void handleReopenReport(e)}
          onClose={() => setReportCenterOpen(false)}
        />
      )}
      {historyOpen && (
        <ReportHistoryModal
          history={reportHistory}
          onReopen={(e) => void handleReopenReport(e)}
          onDelete={(id) => {
            deleteReportHistoryEntry(id);
            setReportHistory(loadReportHistory());
          }}
          onClose={() => setHistoryOpen(false)}
        />
      )}
      {reportPreview && (
        <ReportPreview
          preview={reportPreview}
          onAsk={
            reportPreview.sessionId || (reportPreview.sessionIds && reportPreview.sessionIds.length >= 2)
              ? (q, ch) => handleReportAsk(q, reportPreview, ch)
              : undefined
          }
          onRegenerate={handleRegenerateReport}
          onClose={() => {
            URL.revokeObjectURL(reportPreview.url);
            setReportPreview(null);
          }}
        />
      )}
      </VizFocusProvider>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 子组件
// ---------------------------------------------------------------------------

type Mode =
  | "library"
  | "overview"
  | "ask"
  | "annotate"
  | "graph"
  | "concept_graph"
  | "flow"
  | "reltime"
  | "chararc"
  | "charvoice"
  | "foreshadow"
  | "subplot"
  | "timeline"
  | "entity"
  | "pacing"
  | "narrative"
  | "consistency"
  | "argument"
  | "scholar_stance"
  | "style"
  | "recap"
  | "concept"
  | "motif"
  | "technique"
  | "cards"
  | "revision"
  | "dossier"
  | "redhead"
  | "redhead_actions"
  | "redhead_plain"
  | "redhead_stakes"
  | "redhead_hardfacts"
  | "redhead_formatcheck"
  | "redhead_panorama"
  | "redhead_dossier_panorama"
  | "char_panorama"
  | "person_dossier"
  | "plot_panorama"
  | "quality_panorama"
  | "redhead_depgraph"
  | "redhead_policy"
  | "redhead_level"
  | "meeting_ledger"
  | "meeting_stance"
  | "meeting_commitments";

// 读完整本出结构的功能——大书上分很多段、慢且贵、可能截断,要提前提醒。
// 问书 / 精读 / 实体 / 前情 / 概念 / 母题是 query-scoped 或按章,不在此列。
const WHOLE_BOOK_MODES = new Set<Mode>([
  "graph", "concept_graph", "person_dossier", "reltime", "flow", "chararc", "charvoice", "foreshadow", "subplot",
  "timeline", "narrative", "consistency", "argument", "scholar_stance", "style", "technique",
  "cards", "revision", "redhead", "redhead_actions", "redhead_plain",
  "redhead_stakes", "redhead_hardfacts",
  "redhead_formatcheck", "meeting_ledger", "meeting_stance",
]);

// 左栏功能按"用户想干啥"分五组，每组可折叠（WP-1.5.4）。
// 之前 20 个功能平铺一长条，扫不出哪个干啥；现在按意图归堆。
// 组里只放当前亮出来的功能；红头公文八件单独一组、整组暂藏（见末尾注释）。
//
// 注：WP-1.5.4 把"思想/理论"组列了"论点结构 / 概念演进 / 概念图"三项，
// 但代码里只有 argument（论点结构）和 concept（概念演进）两个 mode，
// 没有单独的"概念图" mode——所以这组只放这两项，没漏。
interface NavGroup {
  /** genre hook 用的稳定键；也作折叠状态的 key */
  key: string;
  title: string;
  modes: { id: Mode; label: string }[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    key: "read",
    title: "问 & 读",
    modes: [
      { id: "overview", label: "概览" },
      { id: "ask", label: "问书" },
      { id: "annotate", label: "精读" },
      { id: "recap", label: "前情回顾" },
      { id: "entity", label: "全书回溯" },
    ],
  },
  {
    key: "character",
    title: "人物",
    modes: [
      // 集合整合:关系图 / 关系演变 / 人物弧线 / 声口 收成一个「人物」镜头(点一人总线联动出各面)。
      { id: "char_panorama", label: "人物" },
      // 立场格局:全员一次批量粗定位到立场轴上(象限主视图),点人现跑单人 Toulmin 详证 + 处境;名册次要。
      { id: "person_dossier", label: "立场格局" },
    ],
  },
  {
    key: "plot",
    title: "情节脉络",
    modes: [
      // 集合整合:叙事曲线 / 叙事流 / 时间线 / 支线 / 伏笔 收成一个「情节脉络」镜头。
      { id: "plot_panorama", label: "情节脉络" },
    ],
  },
  {
    key: "thought",
    title: "思想 · 理论",
    modes: [
      { id: "argument", label: "论点结构" },
      // 概念关系图:理论书专属入口,复用关系图组件锁 concept;叙事书的人物关系图仍在「人物」组的全景里。
      { id: "concept_graph", label: "概念关系图" },
      // 学者立场谱:理论书专属镜头,把书里对话的思想家按本书核心争论摆到发散轴上(替掉不适配的立场格局)。
      { id: "scholar_stance", label: "学者立场谱" },
    ],
  },
  {
    key: "quality",
    title: "质量 · 写作",
    modes: [
      // 集合整合:一致性 / 写作手法 / 文体体检 / 改稿清单 / 知识卡片 收成一个「质量·写作」镜头。
      { id: "quality_panorama", label: "质量 · 写作" },
    ],
  },
  // 1.6 公文组已解封（代码层不再藏）。注意:推到公开仓 = 正式对外亮出"公文"垂直,
  // 那是 NORTH_STAR 级、要作者拍板的事(task #16)——本地 commit 随便,push 等作者点头。
  // 公文 12 功能按和"书"一样的意图标准分三组:读懂这份 / 抓重点办事 / 多份比对(卷宗+跨文件)。
  {
    key: "redhead_read",
    title: "公文 · 读这份",
    modes: [
      // 集合整合:原来「读懂这份 + 抓重点办事」六个平铺功能(结构 / 逐条精读 / 规范性自检 /
      // 利害 / 办事 / 要点)收成一个「公文全景」镜头,进去分段各自读、各自生成。跨文件的另算(下面一组)。
      { id: "redhead_panorama", label: "公文全景" },
    ],
  },
  {
    key: "redhead_cross",
    title: "公文 · 多份比对",
    modes: [
      { id: "dossier", label: "卷宗" },
      // 集合整合:依据链网 / 政策演变 / 上下级 收成一个「卷宗全景」镜头(先选卷宗≥2份再进)。
      { id: "redhead_dossier_panorama", label: "卷宗全景" },
    ],
  },
  // 1.7 会议垂直·首炮。会议题材已进后端 genre_detect：genre=会议 时这组自动显示 +
  // 突出（见 genreVisibleGroups / genreHighlightGroups 的会议分支）。其余题材（书 / 公文）
  // 仍把 "meeting" 放行，留一个手动入口，任何已上传的文档都能点进来试。
  {
    key: "meeting",
    title: "会议 · 行动项",
    modes: [
      { id: "meeting_ledger", label: "行动项台账" },
      { id: "meeting_stance", label: "立场与弦外" },
      { id: "meeting_commitments", label: "跨会承诺追踪" },
    ],
  },
];

// 题材 → 高亮哪几组（genre hook，#10 给 session.genre 后接）。
// 思路:不同题材关心的维度不一样——小说重人物/情节,理论书重思想/质量。
// 命中的组高亮 + 默认展开;没命中的组不藏、只是默认折叠(用户仍可手动展开)。
// **没有 genre 就返回 null = 全部组一视同仁、全显全展开**(向后兼容,现在没 genre 不能崩)。
// 真正的题材分类数据由 #10 提供,这里只留"读 genre → 决定每组是否突出"的接线点。
// 书类题材(小说 / 历史 / 理论 / 论文 / 诗 / 工具书…);公文 / 会议是垂直、不走这套。
const _BOOK_GENRE_RE =
  /(小说|novel|fiction|网文|架空|玄幻|历史|传记|history|biograph|理论|论文|paper|哲学|philosophy|社科|工具书|nonfiction|学术|诗|poem|poetry|散文)/;

// 叙事/论述 mode(exp035,按内容判)→ 书的镜头套餐。mode 优先:叙事只上人物 + 情节、论述只上思想,
// 于是俩关系图(人物 / 概念)俩立场(立场格局 / 学者立场谱)不再在同一本书上撞。mode 没判出返 null,
// 调用方退回按题材的默认桶(检测中 / 失败兜底,不至于门空)。
function bookGroupsByMode(mode: string | undefined | null): Set<string> | null {
  if (mode === "discursive") return new Set(["read", "thought", "quality"]);
  if (mode === "narrative") return new Set(["read", "character", "plot", "quality"]);
  return null;
}

// mode 没判出时的按题材默认(跟旧三桶一致):虚构叙事 / 纪实叙事 / 论述。检测中或失败的兜底。
function _bookGroupsFallbackByGenre(g: string): Set<string> {
  if (/(小说|novel|fiction|网文|架空|玄幻)/.test(g)) {
    return new Set(["read", "character", "plot", "quality"]);
  }
  if (/(历史|传记|history|biograph)/.test(g)) {
    return new Set(["read", "character", "plot", "thought", "quality"]);
  }
  return new Set(["read", "thought", "quality"]);
}

// 题材(+ 叙事/论述 mode)→ 高亮(默认展开 + 描朱)哪几组。书类:高亮 = 可见,显了就亮(修
// "历史书思想组显了却灰着"的自相矛盾)。没 genre / 认不出 → null(全显全展开,向后兼容)。
function genreHighlightGroups(
  genre: string | undefined | null,
  mode?: string | null,
): Set<string> | null {
  if (!genre) return null;
  const g = genre.toLowerCase();
  if (/(公文|红头)/.test(g)) return new Set(["read", "redhead_read", "redhead_cross"]);
  if (/(会议|纪要|meeting)/.test(g)) return new Set(["read", "meeting"]);
  if (_BOOK_GENRE_RE.test(g)) {
    return bookGroupsByMode(mode) ?? _bookGroupsFallbackByGenre(g);
  }
  return null;
}

// 题材(+ 叙事/论述 mode)→ 哪几组可见(跨垂直硬隐藏,#18)。公文 / 会议按题材走垂直组;书类按 mode
// 只上对应一套(叙事=人物+情节+质量、论述=思想+质量),mode 没判出退回按题材默认。没 genre → 全显。
function genreVisibleGroups(
  genre: string | undefined | null,
  mode?: string | null,
): Set<string> | null {
  if (!genre) return null;
  const g = genre.toLowerCase();
  if (/(会议|纪要|meeting)/.test(g)) return new Set(["read", "meeting"]);
  if (/(公文|红头)/.test(g)) return new Set(["read", "redhead_read", "redhead_cross"]);
  if (_BOOK_GENRE_RE.test(g)) {
    return bookGroupsByMode(mode) ?? _bookGroupsFallbackByGenre(g);
  }
  return null;
}

// agent 编排菜单的功能名（后端 orchestrate FEATURE_MENU 的键）→ App 的 mode。
// drill-into 用：点「点开看完整 X 视图」时据功能名跳进左栏那个功能的完整视图。
const FEATURE_TO_MODE: Record<string, Mode> = {
  character_graph: "graph",
  character_flow: "flow",
  timeline: "timeline",
  consistency: "consistency",
  entity_recall: "entity",
  concept_evolution: "entity",
  motif: "entity",
  argument_structure: "argument",
  writing_technique: "technique",
  study_cards: "cards",
  style_issues: "style",
  narrative_curve: "narrative",
  relationship_timeline: "reltime",
  character_arc: "chararc",
  character_voice: "charvoice",
  subplot_weave: "subplot",
  foreshadow: "foreshadow",
};

// 哪些功能 drill 时要把参数预填进它的输入框（功能名 → params 里取哪个键）。
const FEATURE_PREFILL_KEY: Record<string, "entity" | "concept" | "motif" | "character"> = {
  entity_recall: "entity",
  concept_evolution: "concept",
  motif: "motif",
  character_voice: "character",
};

// 互相递（按钮视图 → agent）：每个功能视图角落「把它跟别的维度串起来看」预填的目标。
// 按当前功能给一句合理的跨维度目标——让 agent 把这件事跟相关的几个维度串起来综合。
// 没列进来的功能（如「问书」本身、「改稿清单」这种已经是综合视图的）不给互相递入口。
const CROSS_DIM_GOAL: Partial<Record<Mode, string>> = {
  graph: "把人物关系跟它随时间的演变、各人的戏份起落串起来，看这本书的人物网是怎么长成现在这样的。",
  reltime: "把人物关系随时间的演变跟整体关系网、节奏起伏串起来，看哪几章是关系的转折点。",
  flow: "把各人的出场退场跟戏份弧线、关系网串起来，看这本书的群戏结构和主次安排。",
  chararc: "把主要角色的戏份和处境弧线跟关系演变、节奏起伏串起来，看人物成长跟全书节奏怎么咬合。",
  charvoice: "把这个角色的说话腔调跟他的人物弧线、关系演变串起来，看口吻变化是不是剧情推着走的。",
  foreshadow: "把伏笔的埋设和回收跟时间线、节奏起伏串起来，看哪些坑埋了没填、铺垫节奏稳不稳。",
  subplot: "把各条支线的活跃休眠跟节奏、伏笔、时间线串起来，看哪条支线断更太久、几条线怎么交汇成高潮。",
  timeline: "把事件的真实时间先后跟节奏起伏、伏笔铺设串起来，看这本书的叙事顺序是怎么安排的。",
  entity: "把这个对象的全书轨迹跟时间线、人物关系串起来，看它在故事里起了什么作用。",
  narrative: "把逐章的事件密度跟人物弧线、伏笔回收、支线编织串起来，看这本书的戏分布和转折是怎么铺排的。",
  consistency: "把设定前后矛盾跟人物关系、时间线串起来，看这些矛盾是孤立笔误还是牵动了情节。",
  argument: "把这本书的论证骨架跟关键概念的演进、全书有没有自相矛盾串起来，看它论证扎不扎实。",
  concept: "把这个概念的演进跟全书论证结构、相关母题串起来，看它在书里的分量和脉络。",
  motif: "把这个母题的全书复现跟叙事曲线、人物弧线串起来，看它怎么贯穿和呼应主题。",
  technique: "把作者的写作手法跟节奏安排、伏笔铺设、叙事曲线串起来，看这本书的手艺好在哪。",
  cards: "把这本书的知识要点跟论证结构、概念演进串起来，给一份带脉络的通盘梳理。",
  style: "把文体毛病跟人物声口、支线安排串起来，看这些问题成不成系统、要不要统一改。",
};

// 自动建议（保守）：判一句普通提问是不是开放 / 跨维度的——是就温和提示「要不要编排着跑」。
// 命中任一开放词，或一句话里没点名某个具体功能且偏长偏综合，就算开放。宁可漏报不误扰。
const OPEN_QUESTION_HINTS = [
  "整本",
  "总览",
  "通盘",
  "审一遍",
  "审一下",
  "全书",
  "有什么问题",
  "怎么样",
  "哪些",
  "综合",
  "全面",
  "整体",
  "通读",
  "梳理一遍",
];

function looksCrossDimensional(question: string): boolean {
  const q = question.trim();
  if (q.length < 6) return false; // 太短的（如「主角是谁」）多半是具体问题，不打扰
  return OPEN_QUESTION_HINTS.some((kw) => q.includes(kw));
}

// 细线 SVG 导航图标——不用 emoji、不引图标库
function NavIcon({
  id,
  size = 17,
}: {
  id: Mode | "settings" | "read";
  size?: number;
}) {
  const paths: Record<string, React.ReactNode> = {
    // 读——摊开的书（常驻「读」门）
    read: (
      <>
        <path d="M12 6c-1.8-1.3-4.2-2-7-2v13c2.8 0 5.2.7 7 2" />
        <path d="M12 6c1.8-1.3 4.2-2 7-2v13c-2.8 0-5.2.7-7 2z" />
        <path d="M12 6v13" />
      </>
    ),
    ask: (
      <>
        <path d="M5 5h14v10H10l-4 4v-4H5z" />
        <path d="M9 9h6M9 12h4" />
      </>
    ),
    annotate: (
      <>
        <path d="M4 4h9l3 3v13H4z" />
        <path d="M7 9h5M7 12h6M7 15h4" />
        <circle cx="17.5" cy="6.5" r="2.5" />
      </>
    ),
    graph: (
      <>
        <circle cx="6" cy="7" r="2" />
        <circle cx="18" cy="8" r="2" />
        <circle cx="10" cy="18" r="2" />
        <path d="M7.7 8.1 16.1 8.4M8.7 16.4 9.6 9.9" />
      </>
    ),
    flow: (
      <>
        <path d="M3 6h6c2 0 2 6 4 6s2-6 4-6h4" />
        <path d="M3 18h6c2 0 2-6 4-6" />
      </>
    ),
    reltime: (
      <>
        <circle cx="6" cy="7" r="2" />
        <circle cx="17" cy="7" r="2" />
        <path d="M8 7h7" />
        <path d="M4 20h16" />
        <path d="M9 20v-2.5M15 20v-2.5" />
      </>
    ),
    chararc: (
      <>
        <path d="M3 14c3 0 3-7 6-7s3 5 6 5 3-6 6-6" />
        <circle cx="9" cy="7" r="1.2" />
        <circle cx="15" cy="12" r="1.2" />
        <path d="M3 20h18" />
      </>
    ),
    charvoice: (
      <>
        <path d="M4 5h16v9H9l-4 4v-4H4z" />
        <path d="M8 9h5" />
        <path d="M8 11.5h3" strokeDasharray="1.4 1.4" />
      </>
    ),
    foreshadow: (
      <>
        <path d="M4 18c0-6 12-6 12 0" />
        <path d="M16 18c0-3 4-4 4-7" strokeDasharray="2 2" />
        <circle cx="4" cy="18" r="1.4" />
        <circle cx="16" cy="18" r="1.4" />
      </>
    ),
    subplot: (
      <>
        <path d="M3 8c5 0 5 8 10 8s5-8 8-8" />
        <path d="M3 16c5 0 5-8 10-8s5 8 8 8" />
        <circle cx="13" cy="12" r="1.5" />
      </>
    ),
    timeline: (
      <>
        <path d="M5 4v16" />
        <circle cx="5" cy="8" r="1.5" />
        <circle cx="5" cy="15" r="1.5" />
        <path d="M9 8h10M9 15h6" />
      </>
    ),
    entity: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="m21 21-4.3-4.3" />
      </>
    ),
    narrative: (
      <>
        <path d="M4 20v-5M8 20v-9M12 20v-3M16 20V7M20 20v-7" />
        <path d="M3 20h18" />
        <circle cx="16" cy="4.5" r="1.6" />
      </>
    ),
    consistency: (
      <>
        <path d="M12 4 21 19H3z" />
        <path d="M12 10v4M12 16.5h.01" />
      </>
    ),
    argument: (
      <>
        <path d="M9 6h11M9 12h11M9 18h7" />
        <path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01" />
      </>
    ),
    style: (
      <>
        <path d="M12 20h9" />
        <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
      </>
    ),
    recap: <path d="M6 3h12v18l-6-4-6 4z" />,
    concept: (
      <>
        <path d="M4 17l5-5 4 4 7-7" />
        <path d="M16 8h4v4" />
      </>
    ),
    motif: (
      <>
        <circle cx="12" cy="12" r="3" />
        <circle cx="12" cy="12" r="8" />
      </>
    ),
    technique: (
      <>
        <path d="M5 3v4M3 5h4M6 17v4M4 19h4" />
        <path d="M13 7l4 4L7 21l-4-4z" />
      </>
    ),
    cards: (
      <>
        <rect x="3" y="5" width="13" height="13" rx="2" />
        <path d="M8 5V3h13v13h-2" />
      </>
    ),
    revision: (
      <>
        <path d="M8 4h8v3H8z" />
        <path d="M6 5h2v0M16 5h2v15H6V5h0" />
        <path d="M9 12l1.6 1.6L13.5 11M9 16.5h4" />
      </>
    ),
    redhead: (
      <>
        <path d="M5 3h11l3 3v15H5z" />
        <path d="M8 8h6" />
        <path d="M8 11.5h8" />
        <circle cx="16.5" cy="16" r="2.5" />
      </>
    ),
    redhead_actions: (
      <>
        <rect x="6" y="4" width="12" height="17" rx="1.5" />
        <path d="M9 3.5h6v2H9z" />
        <path d="M9 10l1.4 1.4L13 9" />
        <path d="M9 15l1.4 1.4L13 14" />
      </>
    ),
    redhead_plain: (
      <>
        <path d="M5 3h11l3 3v15H5z" />
        <path d="M8 8.5h8" />
        <path d="M8 11h5" />
        <path d="M8 15.5h8" />
        <path d="M8 18h5" />
      </>
    ),
    // 利害与风向——天平(权衡机会/风险)
    redhead_stakes: (
      <>
        <path d="M12 3v18" />
        <path d="M5 7h14" />
        <path d="M5 7l-2.5 5.5a3 3 0 0 0 5 0z" />
        <path d="M19 7l-2.5 5.5a3 3 0 0 0 5 0z" />
        <path d="M8 21h8" />
      </>
    ),
    // 要点提取——文件 + 放大镜，把硬数据抠出来
    redhead_hardfacts: (
      <>
        <path d="M5 3h9l3 3v5" />
        <path d="M5 3v18h6" />
        <circle cx="16.5" cy="15.5" r="3" />
        <path d="M18.7 17.7 21 20" />
      </>
    ),
    // 规范性自检——文件 + 对勾盾
    redhead_formatcheck: (
      <>
        <path d="M5 3h9l3 3v4" />
        <path d="M5 3v18h6" />
        <path d="M16.5 12 21 14v3c0 2.5-2 4-4.5 5C14 21 12 19.5 12 17v-3z" />
        <path d="M14.7 16.8 16 18l2.5-2.6" />
      </>
    ),
    // 卷宗——函套 / 文件夹收一摞文书
    dossier: (
      <>
        <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        <path d="M3 11h18" />
      </>
    ),
    // 依据链网——分层节点 + 有向连线（层级依据图）
    redhead_depgraph: (
      <>
        <rect x="9" y="3" width="6" height="3.5" rx="0.6" />
        <rect x="3.5" y="14" width="6" height="3.5" rx="0.6" />
        <rect x="14.5" y="14" width="6" height="3.5" rx="0.6" />
        <path d="M11 6.5 6.8 14M13 6.5 17 14" />
      </>
    ),
    // 政策演变——纪年轴 + 阶段点（编年时序）
    redhead_policy: (
      <>
        <path d="M6 3v18" />
        <circle cx="6" cy="7" r="1.6" />
        <circle cx="6" cy="12.5" r="1.6" />
        <circle cx="6" cy="18" r="1.6" />
        <path d="M10 7h9M10 12.5h7M10 18h9" />
      </>
    ),
    // 上下级一致性——两栏并排勘合（对照校核）
    redhead_level: (
      <>
        <rect x="3.5" y="5" width="7" height="14" rx="1" />
        <rect x="13.5" y="5" width="7" height="14" rx="1" />
        <path d="M12 8v8" strokeDasharray="2 2" />
      </>
    ),
    library: (
      <>
        <path d="M5 4h4v16H5zM11 5l3.8-.6 2.4 15.2-3.8.6z" />
      </>
    ),
    settings: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0"
      aria-hidden="true"
    >
      {paths[id]}
    </svg>
  );
}

// 函套 / 书脊气质的左栏：藏书印 + 案上当前书 + 模式导航 + 底部书库 / 设置
function Sidebar(props: {
  mode: Mode;
  onMode: (m: Mode) => void;
  currentBook: SessionMetadata | null;
  hasBook: boolean;
  /** #10 给 session 带上的题材；有值就按题材高亮可用组、没值全显（向后兼容） */
  genre?: string | null;
  /** 叙事/论述 book mode(exp035):书类据它只上对应一套镜头;空 = 退回按题材默认。
      注意跟上面的 mode(当前视图 Mode)不是一回事,故叫 bookMode。 */
  bookMode?: string | null;
  open: boolean;
  onOpenSettings: () => void;
  /** 常驻「读」门：选中书直接进沉浸阅读器（不必回书库）。 */
  onRead: () => void;
  /** 进了阅读器（整页 Reader）时为 true——让「读」项高亮，跟其它 mode 一致。 */
  readerActive?: boolean;
  /** hosted 模式登录后的当前用户;local / 未登录为 null,不渲染账号条。 */
  authUser?: AuthUser | null;
  onLogout?: () => void;
  /** 注销账号(hosted):账号条上点开的小面板里用。 */
  onDeleteAccount?: () => Promise<void>;
}) {
  const {
    mode,
    onMode,
    currentBook,
    hasBook,
    genre,
    bookMode,
    open,
    onOpenSettings,
    onRead,
    readerActive,
    authUser,
    onLogout,
    onDeleteAccount,
  } = props;

  // 题材 → 突出哪几组。null = 不偏向任何组（没 genre / 认不出的题材都走这条，全显）。
  const highlighted = genreHighlightGroups(genre, bookMode);
  // 题材(+ bookMode)→ 哪几组可见:公文/会议走垂直组、书类按叙事/论述上对应一套;null=全显(没测出兜底)。
  const visible = genreVisibleGroups(genre, bookMode);

  // 折叠状态：记每组是否收起。默认——有 genre 时不突出的组默认收起；其余全展开。
  // 用户手动点过的组用这个 Map 覆盖默认，换书（genre 变）时重置回默认。
  const [collapsedOverride, setCollapsedOverride] = useState<
    Record<string, boolean>
  >({});
  useEffect(() => {
    // genre 变了（换书 / #10 填了题材）→ 清掉手动折叠，回到题材决定的默认展开态。
    setCollapsedOverride({});
  }, [genre]);

  function defaultCollapsed(groupKey: string): boolean {
    // 没 genre 或认不出 → 全展开；有 genre → 没被突出的组默认收起。
    if (!highlighted) return false;
    return !highlighted.has(groupKey);
  }
  function isCollapsed(groupKey: string): boolean {
    return collapsedOverride[groupKey] ?? defaultCollapsed(groupKey);
  }
  function toggleGroup(groupKey: string): void {
    setCollapsedOverride((prev) => ({
      ...prev,
      [groupKey]: !isCollapsed(groupKey),
    }));
  }
  return (
    <aside
      className={[
        "fixed inset-y-0 left-0 z-40 w-[208px] shrink-0 flex flex-col",
        "transform transition-transform duration-200",
        "md:static md:translate-x-0 md:z-auto md:self-stretch",
        open ? "translate-x-0" : "-translate-x-full",
      ].join(" ")}
      style={{
        background: "var(--color-case)",
        borderRight:
          "2px solid color-mix(in oklch, var(--color-seal) 22%, transparent)",
      }}
    >
      {/* 藏书印——居中竖排：朱印 + 书鉴 */}
      <div className="pt-7 pb-5 flex flex-col items-center gap-2">
        <span
          className="seal-stamp inline-flex items-center justify-center w-11 h-11 rounded-[5px] text-[var(--color-paper)] select-none"
          style={{
            background: "var(--color-seal)",
            fontFamily: "var(--font-display)",
            fontSize: "1.55rem",
            boxShadow: "var(--shadow-soft)",
            transform: "rotate(-2deg)",
          }}
          aria-hidden="true"
        >
          鑒
        </span>
        <span
          className="text-[var(--color-ink)]"
          style={{
            fontFamily: "var(--font-display)",
            fontSize: "1.05rem",
            letterSpacing: "0.2em",
            paddingLeft: "0.2em",
          }}
        >
          书鉴
        </span>
        {DEMO && (
          <span
            className="mt-1 rounded-full px-2 py-0.5 text-caption tracking-wide"
            style={{
              background: "color-mix(in oklch, var(--color-seal) 13%, transparent)",
              color: "var(--color-seal)",
            }}
          >
            演示 · 样本《三国演义》
          </span>
        )}
      </div>

      {/* 案上当前书 */}
      <div className="px-4 pb-4">
        <div className="text-caption tracking-wider text-[var(--color-ink-muted)] mb-1.5 text-center">
          案上
        </div>
        {currentBook ? (
          <div
            className="rounded-md border px-3 py-2 text-center"
            style={{
              borderColor: "var(--color-rule)",
              background: "var(--color-paper)",
            }}
          >
            <div
              className="text-sm text-[var(--color-ink)] leading-snug truncate"
              style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
              title={currentBook.book_title}
            >
              {currentBook.book_title}
            </div>
            <div className="text-caption text-[var(--color-ink-muted)] mt-1 flex items-center justify-center gap-1.5">
              <span>{currentBook.language}</span>
              {/* 题材可见化(#2):认出的类型亮出来,左栏就是据它显隐;没认出显未分类,不静默全显误导 */}
              {genre ? (
                <span
                  className="px-1.5 py-px rounded-full"
                  style={{
                    background: "var(--color-seal-soft)",
                    color: "var(--color-seal)",
                  }}
                >
                  {genre}
                </span>
              ) : (
                <span className="italic">未分类</span>
              )}
            </div>
          </div>
        ) : (
          <div className="text-xs text-[var(--color-ink-muted)] italic text-center">
            还没择书
          </div>
        )}
      </div>

      {/* 模式导航——按意图分五组，每组一个可折叠小标题；组内图标 + 一个词。
          活动项朱砂左边线 + 淡底；题材突出的组标题描朱、不突出的默认收起。 */}
      <nav className="flex-1 px-2.5 overflow-y-auto">
        {!hasBook && (
          <p className="px-2.5 py-3 text-caption text-[var(--color-ink-muted)] leading-relaxed">
            先从书柜挑一本书，这里就列出能对它做的分析。
          </p>
        )}
        {hasBook &&
          NAV_GROUPS.map((group) => {
          // 跨垂直隐藏(#18):不在当前题材可见集里的组直接不渲染(公文藏书组 / 书藏公文组);
          // visible 为 null(没 genre/认不出)时全渲染。
          if (visible && !visible.has(group.key)) return null;
          const collapsed = isCollapsed(group.key);
          // 题材命中这组就突出标题（描朱）；没 genre 时 highlighted 为 null、都不突出。
          const featured = highlighted?.has(group.key) ?? false;
          return (
            <div key={group.key} className="mb-1.5">
              <button
                type="button"
                onClick={() => toggleGroup(group.key)}
                className="w-full flex items-center justify-between gap-1.5 px-2.5 py-1.5 rounded-md transition-colors"
                style={{
                  color: featured
                    ? "var(--color-seal)"
                    : "var(--color-ink-muted)",
                }}
                aria-expanded={!collapsed}
              >
                <span
                  className="text-caption tracking-wider"
                  style={{ fontWeight: featured ? 600 : 500 }}
                >
                  {group.title}
                </span>
                {/* 折叠箭头：展开朝下、收起朝右 */}
                <svg
                  width="11"
                  height="11"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="shrink-0 transition-transform"
                  style={{
                    transform: collapsed ? "rotate(-90deg)" : "rotate(0deg)",
                  }}
                  aria-hidden="true"
                >
                  <path d="m6 9 6 6 6-6" />
                </svg>
              </button>
              {!collapsed && (
                <ul className="space-y-0.5 mt-0.5">
                  {/* 常驻「读」门（WP-reading-workspace §2.2）：排「问 & 读」组首位，
                      选中书直接进沉浸阅读器，不必回书库。它不是一个 mode、是整页 Reader 开关。 */}
                  {group.key === "read" && (
                    <li>
                      <button
                        type="button"
                        disabled={!hasBook}
                        onClick={onRead}
                        className="w-full flex items-center gap-2.5 rounded-md pl-2.5 pr-2 py-2 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        style={
                          readerActive
                            ? {
                                background: "var(--color-seal-soft)",
                                borderLeft: "2px solid var(--color-seal)",
                                color: "var(--color-seal)",
                              }
                            : {
                                borderLeft: "2px solid transparent",
                                color: "var(--color-ink)",
                              }
                        }
                      >
                        <NavIcon id="read" />
                        <span
                          className="text-body-sm"
                          style={{
                            fontFamily: "var(--font-display)",
                            fontWeight: readerActive ? 600 : 400,
                          }}
                        >
                          读
                        </span>
                      </button>
                    </li>
                  )}
                  {group.modes.map((m) => {
                    const active = mode === m.id;
                    return (
                      <li key={m.id}>
                        <button
                          type="button"
                          disabled={!hasBook}
                          onClick={() => onMode(m.id)}
                          className="w-full flex items-center gap-2.5 rounded-md pl-2.5 pr-2 py-2 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                          style={
                            active
                              ? {
                                  background: "var(--color-seal-soft)",
                                  borderLeft: "2px solid var(--color-seal)",
                                  color: "var(--color-seal)",
                                }
                              : {
                                  borderLeft: "2px solid transparent",
                                  color: "var(--color-ink)",
                                }
                          }
                        >
                          <NavIcon id={m.id} />
                          <span
                            className="text-body-sm"
                            style={{
                              fontFamily: "var(--font-display)",
                              fontWeight: active ? 600 : 400,
                            }}
                          >
                            {m.label}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </nav>

      {/* 底部：账号条(hosted 已登录才显) + 书库 + 设置 一行 */}
      <div className="mt-auto">
      {authUser && onLogout && (
        <AccountStrip
          user={authUser}
          onLogout={onLogout}
          onDeleteAccount={onDeleteAccount}
        />
      )}
      <div
        className="px-3 py-3.5 flex items-center justify-between"
        style={{ borderTop: "1px solid var(--color-rule)" }}
      >
        <button
          type="button"
          onClick={() => onMode("library")}
          className="inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-body-sm transition-colors"
          style={
            mode === "library"
              ? { color: "var(--color-seal)" }
              : { color: "var(--color-ink-muted)" }
          }
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          </svg>
          书库
        </button>
        <div className="flex items-center gap-1">
          {/* §五:清分析缓存挪到这里(显眼小入口),不再埋设置抽屉底部 */}
          <ClearCacheButton />
          <button
            type="button"
            onClick={onOpenSettings}
            aria-label="设置 · LLM 配置"
            title="设置 · LLM 配置"
            className="inline-flex items-center justify-center w-8 h-8 rounded-md text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
          >
            <NavIcon id="settings" size={16} />
          </button>
        </div>
      </div>
      </div>
    </aside>
  );
}

// 手机端顶栏：左栏收抽屉时露出的把手 + 藏书印
function MobileBar({ onOpenNav }: { onOpenNav: () => void }) {
  return (
    <div
      className="md:hidden fixed top-0 inset-x-0 z-20 flex items-center gap-3 px-4 h-14"
      style={{
        background: "var(--color-paper-raised)",
        borderBottom: "1px solid var(--color-rule)",
      }}
    >
      <button
        type="button"
        onClick={onOpenNav}
        aria-label="打开导航"
        className="inline-flex items-center justify-center w-9 h-9 rounded-md text-[var(--color-ink)] hover:text-[var(--color-seal)]"
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
      <span
        className="seal-stamp inline-flex items-center justify-center w-7 h-7 rounded-[4px] text-[var(--color-paper)] select-none"
        style={{
          background: "var(--color-seal)",
          fontFamily: "var(--font-display)",
          fontSize: "1rem",
        }}
        aria-hidden="true"
      >
        鑒
      </span>
      <span
        className="text-base text-[var(--color-ink)]"
        style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
      >
        书鉴
      </span>
    </div>
  );
}

// 主画布每件事的版心标题：宋体大标题 + 版心式朱砂短线 + 一句说明
// 每个功能"你会得到什么"——给版心标题下的题解卡用，让进功能不再是一个光按钮
const FEATURE_INFO: Record<string, string> = {
  timeline:
    "一条按真实时间先后排好的事件线，多线 / 倒叙也理顺，每条点开看原文出处。",
  entity:
    "一个人 / 物 / 概念在全书每次出现的轨迹：在哪章、在做什么、原文为证。",
  recap: "读到第几章就回顾到第几章的前情要点，后文一个字都不剧透。",
  motif: "一个主题 / 母题在全书哪些地方复现、各处怎么体现，每处钉原文。",
  foreshadow:
    "每条伏笔从埋点章拱到回收点章画一道弧，埋了没回收的画成灰虚线悬空，一眼挑出没填的坑，点弧看两端原文。",
  subplot:
    "每条情节支线一条横向泳道：活跃段亮、休眠段灰断，两条线同章交汇画连接节点。一眼看见哪条支线断更太久、哪几章是多线交汇的高潮，点活跃段 / 交汇看两段勾连原文。",
  narrative:
    "逐章数能数的事：每章高度 = 事件数 + 转折数（伏笔回收），朱砂点标转折章。点一章列出这章实际发生的几件事，每件回原文核验。张力只在明细里附带，标「模型判读」，不当高度。",
  consistency:
    "全书前后矛盾的两处对照（如第 5 章左撇子、第 80 章用右手），编的会被滤掉。",
  argument: "作者的论证骨架：主张 + 撑住它的原文 + 在哪章，一条条理清。",
  concept: "一个概念在全书怎么从提出走到深化，分阶段、每段带原文。",
  technique: "作者怎么写：论证 / 结构 / 铺陈的手法，每条配一句原文例子。",
  cards: "一组知识点卡，每张一道启发自测题，先自己想、再翻看解释和原文。",
  style: "用词重复 / 视角越界 / 支线失踪的毛病单，保守只报清楚的、编的滤掉。",
};

function CanvasHeader({
  title,
  subtitle,
  feature,
}: {
  title: string;
  subtitle?: string;
  feature?: string;
}) {
  const youGet = feature ? FEATURE_INFO[feature] : undefined;
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2">
        <span
          className="text-[var(--color-seal)] leading-none"
          style={{ fontSize: "0.95rem" }}
          aria-hidden="true"
        >
          ❡
        </span>
        <h2
          className="text-2xl md:text-lead leading-tight text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
        >
          {title}
        </h2>
      </div>
      <div
        className="mt-2.5 h-[2px] w-[54px] rounded-full"
        style={{ background: "var(--color-seal)" }}
        aria-hidden="true"
      />
      {subtitle && !youGet && (
        <p className="mt-3 text-sm text-[var(--color-ink-muted)] leading-relaxed">
          {subtitle}
        </p>
      )}
      {youGet && (
        <div
          className="mt-4 rounded-md border px-4 py-3"
          style={{
            borderColor: "var(--color-folio-edge)",
            background: "var(--color-paper-raised)",
            boxShadow: "var(--shadow-soft)",
          }}
        >
          <div
            className="text-xs mb-1.5"
            style={{ color: "var(--color-seal)", letterSpacing: "0.08em" }}
          >
            你会得到
          </div>
          <div
            className="text-body leading-relaxed text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {youGet}
          </div>
          <div
            className="mt-3 pt-2.5 flex items-center gap-2"
            style={{ borderTop: "1px solid var(--color-rule)" }}
          >
            <SealMark size={20} />
            <span className="text-xs text-[var(--color-ink-muted)] leading-relaxed">
              每条结论都钉在原文上、核验过才盖章显示，没出处的不编、不输出。
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// 各家官方预设。BookScope 后端只认 deepseek / anthropic 两个 adapter——deepseek 这个
// 其实是 OpenAI 兼容客户端，所以"其它公司"都走 backend="deepseek" + 各自官方 base_url
// （OpenAI 兼容端点）；只有 Anthropic 走自己的 adapter（忽略 base_url）。
// model.value="" 表示用该 provider 的后端默认值（仅 deepseek/anthropic 后端默认对得上时才
// 能留空；其它家必须给确定模型名，否则会把 deepseek 的默认名发到别家端点上）。
//
// coding plan（订阅制套餐）也是 BYOK：订阅后拿一个能直发的 key + 一个 OpenAI 兼容端点，
// 跟普通按量 key 在 BookScope 看来没区别，所以当成厂商预设的一种加进来即可。详见
// docs/design/WP-llm-plan-access-probe.md。Claude 订阅 / Cursor 这类只能官方 app 里用的
// 接不了，一律不加。
//
// ⚠️ 模型名以各厂商官方最新公布为准 · 核对日期 2026-06-26。模型名滚动快，每家都留了
// "自定义模型名"口子（下面 select 的「自定义…」），拿不准就自己填。
interface ProviderPreset {
  id: string;
  label: string;
  backend: Provider;
  baseUrl: string;
  models: { value: string; label: string }[];
  /** key 输入框下方的一句提示——coding plan 用来说明填哪种 key */
  keyHint?: string;
  note?: string;
}

const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: "deepseek",
    label: "DeepSeek（默认 · 最便宜）",
    backend: "deepseek",
    baseUrl: "",
    models: [
      { value: "", label: "deepseek-v4-flash · 默认最便宜" },
      { value: "deepseek-v4-pro", label: "deepseek-v4-pro · 更强" },
    ],
  },
  {
    id: "zhipu",
    label: "智谱 GLM",
    backend: "deepseek",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    models: [
      { value: "glm-5.2", label: "glm-5.2" },
      { value: "glm-5.1", label: "glm-5.1" },
      { value: "glm-4.7", label: "glm-4.7 · 便宜" },
    ],
  },
  {
    id: "qwen",
    label: "阿里 通义千问",
    backend: "deepseek",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    models: [
      { value: "qwen3.7-max", label: "qwen3.7-max" },
      { value: "qwen3.7-plus", label: "qwen3.7-plus" },
      { value: "qwen3.6-flash", label: "qwen3.6-flash · 便宜" },
    ],
  },
  {
    id: "moonshot",
    label: "月之暗面 Kimi",
    backend: "deepseek",
    baseUrl: "https://api.moonshot.cn/v1",
    models: [
      { value: "kimi-k2.6", label: "kimi-k2.6" },
      { value: "kimi-k2.5", label: "kimi-k2.5" },
    ],
  },
  {
    id: "anthropic",
    label: "Anthropic Claude",
    backend: "anthropic",
    baseUrl: "",
    keyHint:
      "填 console.anthropic.com 的按量 API key（sk-ant-api…）。Claude 的 Pro/Max 订阅接不了，那是只许官方 app 用的 token。",
    models: [
      { value: "", label: "claude-opus-4-8 · 默认最强" },
      { value: "claude-sonnet-4-6", label: "claude-sonnet-4-6 · 均衡" },
      { value: "claude-haiku-4-5", label: "claude-haiku-4-5 · 便宜" },
      { value: "claude-fable-5", label: "claude-fable-5 · 顶配" },
    ],
  },
  {
    // 阿里云百炼 Coding Plan：一份订阅打包通义/Kimi/GLM/MiniMax，性价比最高的接入点。
    // 走 OpenAI 兼容端点，正好命中现有 base_url + key + model 三件套。
    id: "dashscope-coding",
    label: "阿里云百炼 Coding Plan（一份订阅打包多家）",
    backend: "deepseek",
    baseUrl: "https://coding.dashscope.aliyuncs.com/v1",
    keyHint:
      "填百炼 console「Coding Plan 页面」的套餐专属 key（sk-sp… 开头，跟普通按量 key 不是同一个）。",
    models: [
      { value: "qwen3.7-plus", label: "qwen3.7-plus（通义）" },
      { value: "kimi-k2.6", label: "kimi-k2.6（Kimi）" },
      { value: "glm-5.2", label: "glm-5.2（GLM）" },
      { value: "MiniMax-M2.5", label: "MiniMax-M2.5" },
    ],
  },
  {
    // 智谱 GLM Coding Plan：开放平台 key + OpenAI 兼容端点，「Claude Code 平替」定位。
    id: "zhipu-coding",
    label: "智谱 GLM Coding Plan（订阅）",
    backend: "deepseek",
    baseUrl: "https://api.z.ai/api/coding/paas/v4",
    keyHint:
      "填智谱开放平台（z.ai / bigmodel）订阅后建的 API key。端点以填表当天 z.ai 官方文档为准。",
    models: [
      { value: "glm-5.2", label: "glm-5.2" },
      { value: "glm-5.1", label: "glm-5.1" },
      { value: "glm-4.7", label: "glm-4.7 · 便宜" },
    ],
  },
  {
    id: "openai",
    label: "OpenAI",
    backend: "deepseek",
    baseUrl: "https://api.openai.com/v1",
    models: [
      { value: "gpt-5.1", label: "gpt-5.1" },
      { value: "gpt-5-mini", label: "gpt-5-mini · 便宜" },
      { value: "gpt-4.1", label: "gpt-4.1" },
    ],
  },
  {
    id: "gemini",
    label: "Google Gemini",
    backend: "deepseek",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/",
    models: [
      { value: "gemini-3-pro", label: "gemini-3-pro" },
      { value: "gemini-3-flash", label: "gemini-3-flash · 便宜" },
    ],
  },
  {
    id: "xai",
    label: "xAI Grok",
    backend: "deepseek",
    baseUrl: "https://api.x.ai/v1",
    models: [
      { value: "grok-4.1", label: "grok-4.1" },
      { value: "grok-4", label: "grok-4" },
    ],
  },
];

/** 据已存的 provider + baseUrl 反推当前选中哪个预设（baseUrl 精确匹配优先）。 */
function presetFor(provider: Provider, baseUrl: string): ProviderPreset {
  const b = baseUrl.trim();
  const byUrl = PROVIDER_PRESETS.find(
    (p) => p.backend === provider && p.baseUrl === b,
  );
  if (byUrl) return byUrl;
  if (provider === "anthropic") {
    return PROVIDER_PRESETS.find((p) => p.id === "anthropic")!;
  }
  // deepseek + 非预设 baseUrl（自定义代理/私有部署）→ 归到 DeepSeek 这档，baseUrl 照显
  return PROVIDER_PRESETS.find((p) => p.id === "deepseek")!;
}

const CUSTOM_MODEL = "__custom__";

function ProviderConfig(props: {
  provider: Provider;
  setProvider: (p: Provider) => void;
  apiKey: string;
  setApiKey: (s: string) => void;
  model: string;
  setModel: (s: string) => void;
  baseUrl: string;
  setBaseUrl: (s: string) => void;
}) {
  const {
    provider,
    setProvider,
    apiKey,
    setApiKey,
    model,
    setModel,
    baseUrl,
    setBaseUrl,
  } = props;

  const preset = presetFor(provider, baseUrl);
  const modelValues = preset.models.map((m) => m.value);
  const isCustomModel = !modelValues.includes(model);
  const showBaseUrl = preset.backend !== "anthropic";
  // 自定义 baseUrl（deepseek 档但 url 不等于官方空值）时，让用户知道在走代理
  const isProxiedDeepseek =
    preset.id === "deepseek" && baseUrl.trim() !== "";

  function selectPreset(id: string) {
    const next = PROVIDER_PRESETS.find((p) => p.id === id);
    if (!next) return;
    setProvider(next.backend);
    setBaseUrl(next.baseUrl);
    setModel(next.models[0].value); // 切家必须重置模型——旧模型名在新端点上是非法的
  }

  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-[auto_1fr] gap-3 items-center">
        <Label htmlFor="provider">厂商</Label>
        <Select
          id="provider"
          value={preset.id}
          onChange={(e) => selectPreset(e.target.value)}
          wrapperClassName="w-full"
        >
          {PROVIDER_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </Select>
      </div>

      <div className="grid grid-cols-[auto_1fr] gap-3 items-start">
        <Label htmlFor="apikey">API Key</Label>
        <div>
          <input
            id="apikey"
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="粘贴你的 key（存在本地浏览器、刷新不丢）"
            className="w-full rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] px-3 py-2 text-sm"
          />
          {preset.keyHint && (
            <p className="text-caption text-[var(--color-ink-muted)] mt-1 leading-relaxed">
              {preset.keyHint}
            </p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-[auto_1fr] gap-3 items-start">
        <Label htmlFor="model">模型</Label>
        <div>
          <Select
            id="model"
            value={isCustomModel ? CUSTOM_MODEL : model}
            onChange={(e) => {
              const v = e.target.value;
              setModel(v === CUSTOM_MODEL ? "" : v);
            }}
            wrapperClassName="w-full"
          >
            {preset.models.map((m) => (
              <option key={m.value || "__default__"} value={m.value}>
                {m.label}
              </option>
            ))}
            <option value={CUSTOM_MODEL}>自定义…</option>
          </Select>
          {isCustomModel && (
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="自己填模型名（按该厂商最新公布）"
              className="mt-2 w-full rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] px-3 py-2 text-sm font-mono"
            />
          )}
          <p className="text-caption text-[var(--color-ink-muted)] mt-1">
            {preset.id === "deepseek"
              ? "默认就是 deepseek-v4-flash（最便宜大众档）。模型名以官方最新为准，可选「自定义」改写。"
              : "模型名以该厂商官方最新公布为准，拿不准就选「自定义」自己填。"}
          </p>
        </div>
      </div>

      {showBaseUrl && (
        <div className="grid grid-cols-[auto_1fr] gap-3 items-center">
          <Label htmlFor="baseurl">Base URL</Label>
          <input
            id="baseurl"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="OpenAI 兼容 endpoint（选了厂商会自动填；走代理可改）"
            className="rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] px-3 py-2 text-sm font-mono"
          />
        </div>
      )}

      <p className="text-caption text-[var(--color-ink-muted)] leading-relaxed">
        BYOK，key 自带、直发你选的厂商，BookScope 不内置任何 key。除 Anthropic 外都走
        OpenAI 兼容接口（选厂商即自动填好官方 Base URL）。订阅制 coding plan（百炼 / 智谱）
        也是这条路，填套餐专属 key 即可。模型名以各厂商官方为准（核对日期 2026-06-26），
        滚动快就选「自定义」自己填。
        {isProxiedDeepseek && " 当前 Base URL 是自定义代理/私有部署。"}
      </p>
    </div>
  );
}

function UploadForm(props: {
  queue: UploadItem[];
  onAddFiles: (files: File[]) => void;
  onRemoveItem: (id: string) => void;
  language: string;
  setLanguage: (s: string) => void;
  uploading: boolean;
  /** 正在上传的那条 id，进度条只挂在它下面 */
  activeItemId: string | null;
  session: UploadResponse | null;
  onSubmit: (e: FormEvent) => void;
  canSubmit: boolean;
  ingestProgress: IngestProgressState | null;
}) {
  const {
    queue,
    onAddFiles,
    onRemoveItem,
    language,
    setLanguage,
    uploading,
    activeItemId,
    session,
    onSubmit,
    canSubmit,
    ingestProgress,
  } = props;
  const inputRef = useRef<HTMLInputElement | null>(null);
  // 拖拽高亮：dragOver 时给 drop 区一圈朱砂描边。enter/leave 用计数避免子元素
  // 进出抖动（dragleave 在移到子元素时也会触发）。
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);

  function pickFiles(list: FileList | null) {
    if (!list || list.length === 0) return;
    onAddFiles(Array.from(list));
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    pickFiles(e.dataTransfer?.files ?? null);
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      {/* drop 区：点开文件选择器 + 接住拖进来的文件。multiple 支持一次选多本。 */}
      <div
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          dragDepth.current += 1;
          setDragging(true);
        }}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (dragDepth.current === 0) setDragging(false);
        }}
        onDrop={handleDrop}
        role="button"
        tabIndex={0}
        aria-label="点击选择或拖放书籍文件，可多本"
        className={[
          "border-2 border-dashed rounded-lg px-6 py-8 text-center cursor-pointer transition-colors",
          dragging
            ? "border-[var(--color-seal)] bg-[var(--color-seal-soft)]"
            : "border-[var(--color-rule)] hover:border-[var(--color-seal)]/50",
        ].join(" ")}
      >
        <input
          ref={inputRef}
          id="file"
          type="file"
          multiple
          accept=".epub,.txt,.pdf,.docx,.md,.markdown"
          onChange={(e) => {
            pickFiles(e.target.files);
            // 清空 value，下次再选同名文件也能触发 onChange
            e.target.value = "";
          }}
          className="hidden"
        />
        <p className="text-sm text-[var(--color-ink-muted)]">
          {dragging
            ? "松手即可加入上传队列"
            : "点击选择或把文件拖到这里 · 一次可多本（epub / txt / pdf / docx / md）"}
        </p>
      </div>

      {/* 上传队列：每本一行，各自显示等待 / 上传中 / 成功 / 失败。 */}
      {queue.length > 0 && (
        <UploadQueueList
          queue={queue}
          activeItemId={activeItemId}
          uploading={uploading}
          onRemoveItem={onRemoveItem}
        />
      )}

      <div className="grid grid-cols-[auto_1fr] gap-3 items-center">
        <Label htmlFor="lang">语种</Label>
        <div className="w-40">
          <Select
            id="lang"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            wrapperClassName="w-full"
          >
            <option value="zh">中文</option>
            <option value="en">English</option>
            <option value="ja">日本語</option>
          </Select>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <SubmitButton
          loading={uploading}
          disabled={!canSubmit || uploading}
          label={pendingCount(queue) > 1 ? `上传并解析 ${pendingCount(queue)} 本` : "上传并解析"}
          loadingLabel="解析中 · 大书需几分钟"
        />
        {!uploading && session && (
          <div className="text-sm text-[var(--color-ink-muted)]">
            <p>
              已入库：
              <span className="font-medium text-[var(--color-ink)]">
                {session.book_title}
              </span>
            </p>
            <p className="mt-0.5">
              AI 已建好 BM25 索引和角色档（{session.chunk_count} 段 /{" "}
              {session.character_count} 个登场角色）
            </p>
            <p className="mt-0.5">试试上方示例题，或者输入自己的问题</p>
          </div>
        )}
      </div>

      {uploading && (
        <UploadProgressBar
          uploading={uploading}
          ingestProgress={ingestProgress}
        />
      )}
    </form>
  );
}

/** 还没成功的本数（queued + 失败待重试），驱动按钮文案。 */
function pendingCount(queue: UploadItem[]): number {
  return queue.filter((it) => it.status === "queued" || it.status === "error")
    .length;
}

/** 上传队列清单。每本一行：状态点 + 书名 + 大小 / 结果 / 错误 + 删除。 */
function UploadQueueList({
  queue,
  activeItemId,
  uploading,
  onRemoveItem,
}: {
  queue: UploadItem[];
  activeItemId: string | null;
  uploading: boolean;
  onRemoveItem: (id: string) => void;
}) {
  return (
    <ul className="flex flex-col rounded border border-[var(--color-rule)] divide-y divide-[var(--color-rule)] overflow-hidden">
      {queue.map((item) => {
        const isActive = item.id === activeItemId;
        return (
          <li
            key={item.id}
            className="flex items-center gap-3 px-3 py-2 bg-[var(--color-paper-raised)]"
          >
            <UploadStatusBadge status={item.status} active={isActive} />
            <div className="flex flex-col min-w-0 flex-1">
              <span
                className="text-sm text-[var(--color-ink)] truncate"
                title={item.file.name}
              >
                {item.title}
              </span>
              <span className="text-xs text-[var(--color-ink-muted)] truncate">
                {uploadItemHint(item)}
              </span>
            </div>
            {/* 上传中的那本不给删（流正在跑）；其余都可从队列移除 */}
            {!(uploading && isActive) && (
              <button
                type="button"
                onClick={() => onRemoveItem(item.id)}
                aria-label={`从队列移除 ${item.title}`}
                className="shrink-0 text-xs px-2 py-1 rounded text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
              >
                移除
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** 每条队列项右侧那行小字：按状态给不同提示。 */
function uploadItemHint(item: UploadItem): string {
  const sizeKb = `${(item.file.size / 1024).toFixed(1)} KB`;
  switch (item.status) {
    case "queued":
      return `等待上传 · ${sizeKb}`;
    case "uploading":
      return `正在解析 · ${sizeKb}`;
    case "done":
      return item.result
        ? `已入库 · ${item.result.chunk_count} 段 / ${item.result.character_count} 个角色`
        : "已入库";
    case "error":
      return `失败：${item.error?.message ?? "未知错误"}`;
    default:
      return sizeKb;
  }
}

/** 状态点：等待灰 / 上传中朱砂脉动 / 成功对勾 / 失败叉。 */
function UploadStatusBadge({
  status,
  active,
}: {
  status: UploadItemStatus;
  active: boolean;
}) {
  if (status === "done") {
    return (
      <span
        aria-label="成功"
        className="shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs text-white"
        style={{ backgroundColor: "var(--color-seal)" }}
      >
        ✓
      </span>
    );
  }
  if (status === "error") {
    return (
      <span
        aria-label="失败"
        className="shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs border border-[var(--color-seal)] text-[var(--color-seal)]"
      >
        ✕
      </span>
    );
  }
  if (status === "uploading") {
    return (
      <span
        aria-label="上传中"
        className="shrink-0 w-5 h-5 rounded-full flex items-center justify-center"
      >
        <span
          className={active ? "w-2.5 h-2.5 rounded-full animate-pulse" : "w-2.5 h-2.5 rounded-full"}
          style={{ backgroundColor: "var(--color-seal)" }}
        />
      </span>
    );
  }
  // queued
  return (
    <span
      aria-label="等待"
      className="shrink-0 w-5 h-5 rounded-full flex items-center justify-center"
    >
      <span className="w-2.5 h-2.5 rounded-full bg-[var(--color-rule)]" />
    </span>
  );
}

/**
 * 上传进度条。优先用真实 SSE batch 进度（``ingestProgress`` 有值时），
 * 否则回退到 ``useUploadProgress`` 的三段经验曲线（兜底，例如 SSE 帧迟到的
 * 那几秒）。两路 UI 视觉一致——印章红条 + 灰底，stepLabel 只换文案。
 */
function UploadProgressBar({
  uploading,
  ingestProgress,
}: {
  uploading: boolean;
  ingestProgress: IngestProgressState | null;
}) {
  const fallback = useUploadProgress(uploading);

  // 真实进度优先 —— ingest_started 已到（totalBatches 已知或 book-level
  // 命中），用它算百分比；否则用 fallback 曲线。
  const hasRealProgress =
    ingestProgress !== null && (ingestProgress.totalBatches > 0 || ingestProgress.bookCacheHit);

  let percent: number;
  let stepLabel: string;
  if (hasRealProgress && ingestProgress) {
    if (ingestProgress.bookCacheHit) {
      percent = ingestProgress.done ? 100 : 95;
      stepLabel = "整本命中缓存 · 秒进";
    } else {
      const total = Math.max(1, ingestProgress.totalBatches);
      const done = ingestProgress.completedBatches;
      // 留 5% 给 merge / register 那一小段
      percent = ingestProgress.done
        ? 100
        : Math.min(95, Math.round((done / total) * 95));
      const cacheHint =
        ingestProgress.cacheHits > 0
          ? ` · 已命中缓存 ${ingestProgress.cacheHits} 段`
          : "";
      stepLabel = ingestProgress.done
        ? "完成"
        : `AI 正在分析角色 · ${done} / ${total} 批次完成${cacheHint}`;
    }
  } else {
    percent = fallback.percent;
    stepLabel = fallback.stepLabel;
  }

  return (
    <div className="mt-2">
      <div
        className="w-full h-2 rounded overflow-hidden"
        style={{ backgroundColor: "var(--color-rule)" }}
        role="progressbar"
        aria-valuenow={Math.round(percent)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full transition-[width] duration-200 ease-out"
          style={{
            width: `${percent}%`,
            backgroundColor: "var(--color-seal)",
          }}
        />
      </div>
      <p className="mt-1.5 text-xs text-[var(--color-ink-muted)]">
        {stepLabel}
      </p>
    </div>
  );
}

// 示例题清单 —— 让用户进来就知道这工具能干什么。两组：
// 通识题（fast path · 几秒）+ 评论题（v3.5 评论家姿态 · 几秒到一两分钟）
const SUGGESTED_GENERAL = [
  "主要角色有哪几个？",
  "故事发生在什么时代？",
  "一共有多少章？",
];
const SUGGESTED_REVIEW = [
  "作者最强的论点是什么？",
  "这本书最让人意外的发现是什么？",
  "和同类书比，这本独到在哪里？",
];
// 作家诊断题——把 GO 过的差异化能力（伏笔/节奏/支线/转变/漂移，loop 已处理）
// surface 成一键示例。点一下填入输入框可再改具体章节。
const SUGGESTED_DIAGNOSTIC = [
  "有没有埋了却没回收的伏笔？",
  "全书节奏哪几章最松、哪几章最紧？",
  "主角的关键转变是渐变还是硬扳的？",
  "哪条支线铺垫偏薄、该加戏？",
  "设定或人物有没有前后矛盾、漂移？",
];

function SuggestedQuestions(props: {
  bookTitle: string;
  disabled: boolean;
  onPick: (question: string) => void;
  bookQuestions: { type: string; question: string }[];
  bookQuestionsLoading: boolean;
  onGenerateBookQuestions: () => void;
}) {
  const {
    disabled,
    onPick,
    bookQuestions,
    bookQuestionsLoading,
    onGenerateBookQuestions,
  } = props;
  return (
    <div className="mb-4 rounded border border-[var(--color-rule)] bg-[var(--color-surface)] p-3">
      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        想问点什么？点一下试试，或者自己写一道，后端会自动判要不要深查。
      </p>
      <div className="flex flex-wrap gap-2 mb-2">
        <span className="text-xs text-[var(--color-ink-muted)] self-center">
          快问（几秒就答）：
        </span>
        {SUGGESTED_GENERAL.map((q) => (
          <button
            key={q}
            type="button"
            disabled={disabled}
            onClick={() => onPick(q)}
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <span className="text-xs text-[var(--color-ink-muted)] self-center">
          深问（要查证一两分钟）：
        </span>
        {SUGGESTED_REVIEW.map((q) => (
          <button
            key={q}
            type="button"
            disabled={disabled}
            onClick={() => onPick(q)}
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-2 mt-2">
        <span className="text-xs text-[var(--color-ink-muted)] self-center">
          深度诊断（作家审稿）：
        </span>
        {SUGGESTED_DIAGNOSTIC.map((q) => (
          <button
            key={q}
            type="button"
            disabled={disabled}
            onClick={() => onPick(q)}
            className="text-xs px-2 py-1 rounded border border-[var(--color-seal)]/40 bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-2 mt-2 pt-2 border-t border-[var(--color-rule)]">
        <span className="text-xs text-[var(--color-ink-muted)] self-center">
          据这本书出的题：
        </span>
        {bookQuestions.length === 0 ? (
          <button
            type="button"
            disabled={disabled || bookQuestionsLoading}
            onClick={onGenerateBookQuestions}
            className="text-xs px-2 py-1 rounded border border-[var(--color-seal)]/40 bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {bookQuestionsLoading
              ? "据这本书出题中（约 1 分钟）…"
              : "不知道问啥？让 AI 据这本书出几道"}
          </button>
        ) : (
          bookQuestions.map((q) => (
            <button
              key={q.question}
              type="button"
              disabled={disabled}
              onClick={() => onPick(q.question)}
              title={`${q.type}（据这本书出）`}
              className="text-xs px-2 py-1 rounded border border-[var(--color-seal)]/40 bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {q.question}
            </button>
          ))
        )}
      </div>
    </div>
  );
}

// 随便问 ↔ 给目标 的小切换。给目标 = 让 agent 自己规划该跑哪几个分析、串起来综合。
function AskModeToggle({
  mode,
  onChange,
}: {
  mode: "question" | "goal";
  onChange: (m: "question" | "goal") => void;
}) {
  const tabs: { id: "question" | "goal"; label: string; hint: string }[] = [
    { id: "question", label: "随便问", hint: "问一个具体问题" },
    { id: "goal", label: "给目标", hint: "让 agent 编排着跑" },
  ];
  return (
    <div className="mb-4">
      <div
        className="inline-flex rounded-md border p-0.5"
        style={{ borderColor: "var(--color-rule)", background: "var(--color-surface)" }}
        role="tablist"
        aria-label="问书模式"
      >
        {tabs.map((t) => {
          const active = mode === t.id;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onChange(t.id)}
              className="px-3.5 py-1.5 rounded text-sm transition-colors"
              style={
                active
                  ? { background: "var(--color-seal)", color: "white" }
                  : { color: "var(--color-ink-muted)" }
              }
            >
              <span style={{ fontFamily: "var(--font-display)", fontWeight: active ? 600 : 400 }}>
                {t.label}
              </span>
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-[var(--color-ink-muted)] leading-relaxed">
        {mode === "question"
          ? "问一个具体问题，后端自动判要不要深查，这是原来的问书。"
          : "说一个目标（不知道点哪个功能也行），agent 会自己挑该跑哪几个分析、串起来跑、综合成带原文证据的结论，每块还能点进完整视图。"}
      </p>
    </div>
  );
}

// 自动建议的温和提示条——是建议不是拦截：一句话 + 一键接受 + 一键关掉。
// 用淡朱砂底色、低存在感，关掉后这次会话不再弹同一类（由父组件记 dismissed 标记）。
function AgentSuggestHint({
  text,
  actionLabel,
  onAccept,
  onDismiss,
}: {
  text: string;
  actionLabel: string;
  onAccept: () => void;
  onDismiss: () => void;
}) {
  return (
    <div
      className="reveal mb-4 flex items-start gap-3 rounded-md border px-3.5 py-2.5"
      style={{
        borderColor: "color-mix(in oklch, var(--color-seal) 30%, transparent)",
        background: "var(--color-seal-soft)",
      }}
    >
      <span
        className="mt-0.5 text-[var(--color-seal)] leading-none"
        style={{ fontSize: "0.9rem" }}
        aria-hidden
      >
        ❡
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm leading-relaxed text-[var(--color-ink)]">{text}</p>
        <div className="mt-2 flex items-center gap-3">
          <button
            type="button"
            onClick={onAccept}
            className="text-xs px-3 py-1.5 rounded bg-[var(--color-seal)] text-white hover:brightness-110 transition-all"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {actionLabel}
          </button>
          <button
            type="button"
            onClick={onDismiss}
            className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] transition-colors"
          >
            不用了
          </button>
        </div>
      </div>
    </div>
  );
}

// 互相递入口：功能视图角落一个轻链接，把当前这件事跟别的维度串起来看（升到 agent 编排）。
// 要轻、不打扰——靠右一行小字链接，不抢功能本身的版面。
function CrossDimRelay({ onRelay }: { onRelay: () => void }) {
  return (
    <div className="-mt-3 mb-4 flex justify-end">
      <button
        type="button"
        onClick={onRelay}
        className="inline-flex items-center gap-1.5 text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] transition-colors"
        title="让 agent 把这件事跟相关的几个维度串起来综合看"
      >
        <span aria-hidden>⇲</span>
        把它跟别的维度串起来看
      </button>
    </div>
  );
}

function AskForm(props: {
  question: string;
  setQuestion: (s: string) => void;
  asking: boolean;
  onSubmit: (e: FormEvent) => void;
  canSubmit: boolean;
}) {
  const { question, setQuestion, asking, onSubmit, canSubmit } = props;
  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="比如：这本书里主要有哪几个角色？他们之间是什么关系？"
        rows={3}
        className="rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] px-3 py-2 text-sm resize-y min-h-[80px]"
      />
      <SubmitButton
        loading={asking}
        disabled={!canSubmit || asking}
        label="提问"
        loadingLabel="agent 进行中 · 见下方进度"
      />
    </form>
  );
}

/**
 * 把 progress items 折叠为 "段" —— 每段要么是一个 iteration 头 + 它属下的 tools,
 * 要么是一条 meta（独占一行）。同一 iteration 的 tools 视觉上缩进共组,
 * 让用户一眼看出它们是并发跑的。
 */
type TimelineSection =
  | {
      kind: "iteration-group";
      iteration: number;
      tools: Extract<ProgressItem, { kind: "tool" }>[];
    }
  | { kind: "stray-tool"; tool: Extract<ProgressItem, { kind: "tool" }> }
  | {
      kind: "meta";
      meta: Extract<ProgressItem, { kind: "meta" }>;
    };

function buildSections(items: ProgressItem[]): TimelineSection[] {
  const sections: TimelineSection[] = [];
  let current: Extract<TimelineSection, { kind: "iteration-group" }> | null =
    null;

  for (const item of items) {
    if (item.kind === "iteration") {
      current = { kind: "iteration-group", iteration: item.iteration, tools: [] };
      sections.push(current);
    } else if (item.kind === "tool") {
      if (current && (item.iteration === null || item.iteration === current.iteration)) {
        current.tools.push(item);
      } else {
        sections.push({ kind: "stray-tool", tool: item });
      }
    } else {
      // meta 切断 iteration group：之后的 tool 不再贴回旧组
      sections.push({ kind: "meta", meta: item });
      current = null;
    }
  }
  return sections;
}

function ChapterBadge({ chapter }: { chapter: number }) {
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 text-caption rounded-sm text-white align-baseline"
      style={{
        backgroundColor: "var(--color-seal)",
        fontFamily: "var(--font-display)",
      }}
    >
      第 {chapter} 章
    </span>
  );
}

function ToolStatusDot({
  status,
  isActive,
}: {
  status: "running" | "ok" | "error";
  isActive: boolean;
}) {
  if (status === "running") {
    return (
      <span
        className="animate-pulse inline-block"
        style={{ color: isActive ? "var(--color-seal)" : "var(--color-ink-muted)" }}
      >
        ●
      </span>
    );
  }
  if (status === "error") {
    return (
      <span style={{ color: "var(--color-seal)" }} aria-label="失败">
        ✕
      </span>
    );
  }
  return (
    <span className="text-[var(--color-ink-muted)]" aria-label="完成">
      ✓
    </span>
  );
}

function ToolLine({
  tool,
  isActive,
}: {
  tool: Extract<ProgressItem, { kind: "tool" }>;
  isActive: boolean;
}) {
  const textTone =
    tool.status === "running" && isActive
      ? "text-[var(--color-ink)] font-medium"
      : "text-[var(--color-ink-muted)]";
  return (
    <p className={`text-sm leading-relaxed ${textTone}`}>
      <ToolStatusDot status={tool.status} isActive={isActive} />{" "}
      <span>{tool.label}</span>
      {tool.chapters.length > 0 && (
        <>
          {tool.chapters.map((c) => (
            <span key={c} className="ml-1.5">
              <ChapterBadge chapter={c} />
            </span>
          ))}
        </>
      )}
      {tool.status === "error" && tool.errorMessage && (
        <span className="ml-2 text-xs text-[var(--color-seal)]">
          · {tool.errorMessage}
        </span>
      )}
    </p>
  );
}

function ProgressTimeline({
  progress,
  done,
  routeDecision,
  questionProcessed,
  finalDurationMs,
}: {
  progress: ProgressItem[];
  done: boolean;
  routeDecision: RouteDecisionState | null;
  questionProcessed: QuestionProcessedState | null;
  finalDurationMs: number | null;
}) {
  const sections = buildSections(progress);
  // 找到最后一条还在 running 的 tool —— 它高亮显示当前焦点
  let lastRunning: ProgressItem | null = null;
  for (let i = progress.length - 1; i >= 0; i -= 1) {
    const item = progress[i];
    if (item.kind === "tool" && item.status === "running") {
      lastRunning = item;
      break;
    }
  }

  return (
    <div className="mt-6 border-l-2 border-[var(--color-rule)] pl-4 py-1 space-y-3">
      {routeDecision && (
        <RouteDecisionBanner
          decision={routeDecision}
          done={done}
          finalDurationMs={finalDurationMs}
        />
      )}
      {questionProcessed && (
        <QuestionBreakdown breakdown={questionProcessed} />
      )}
      <h3 className="text-xs uppercase tracking-wider text-[var(--color-ink-muted)]">
        进度 {done ? "· 完成" : ""}
      </h3>
      {progress.length === 0 && !done && (
        <p className="text-sm text-[var(--color-ink-muted)] italic">
          <span className="animate-pulse">●</span> 等待 agent 启动…
        </p>
      )}

      {sections.map((section, sIdx) => {
        if (section.kind === "iteration-group") {
          const isMultiTool = section.tools.length > 1;
          return (
            <div key={`it-${section.iteration}-${sIdx}`} className="space-y-1.5">
              <p
                className="text-xs uppercase tracking-wider text-[var(--color-ink-muted)]"
                style={{ fontFamily: "var(--font-display)" }}
              >
                第 {section.iteration} 轮
                {isMultiTool && (
                  <span className="ml-2 normal-case text-caption">
                    · {section.tools.length} 个工具并发
                  </span>
                )}
              </p>
              {section.tools.length === 0 ? (
                done ? (
                  <p className="pl-4 text-sm text-[var(--color-ink-muted)]">
                    ✓ 不调工具，直接综合
                  </p>
                ) : (
                  <p className="pl-4 text-sm text-[var(--color-ink-muted)] italic">
                    <span className="animate-pulse">●</span> 思考中…
                  </p>
                )
              ) : (
                <div className="pl-4 space-y-1.5 border-l border-[var(--color-rule)]/60">
                  {section.tools.map((tool, tIdx) => (
                    <ToolLine
                      key={`${section.iteration}:${tIdx}:${tool.toolName}`}
                      tool={tool}
                      isActive={tool === lastRunning}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        }
        if (section.kind === "stray-tool") {
          return (
            <ToolLine
              key={`stray-${sIdx}`}
              tool={section.tool}
              isActive={section.tool === lastRunning}
            />
          );
        }
        return (
          <p
            key={`meta-${sIdx}`}
            className={`text-sm leading-relaxed ${
              section.meta.tone === "warn"
                ? "text-[var(--color-seal)]"
                : "text-[var(--color-ink-muted)]"
            }`}
          >
            · {section.meta.label}
          </p>
        );
      })}
    </div>
  );
}

function AnswerBlock({ answer }: { answer: AskResponse }) {
  function exportMarkdown() {
    const lines: string[] = [];
    if (answer.question) lines.push(`# 问\n\n${answer.question}\n`);
    lines.push(`# 答\n\n${answer.answer}\n`);
    if (answer.citations.length > 0) {
      lines.push(`# 原文（${answer.citations.length} 条）\n`);
      answer.citations.forEach((c, i) =>
        lines.push(`${i + 1}. [第 ${c.chapter} 章] ${c.snippet}`),
      );
    }
    const blob = new Blob([lines.join("\n")], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `bookscope-发现-${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <article className="mt-8 space-y-7">
      {/* 朱批：AI 的判断 */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span
              className="inline-block w-1.5 h-1.5 rounded-full"
              style={{ background: "var(--color-seal)" }}
              aria-hidden="true"
            />
            <h3
              className="text-sm tracking-wide text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
            >
              评点
            </h3>
          </div>
          <button
            type="button"
            onClick={exportMarkdown}
            className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] transition-colors"
          >
            导出 Markdown
          </button>
        </div>
        <div
          className="whitespace-pre-wrap leading-[1.85] text-body text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {answer.answer}
        </div>
      </div>

      {/* 原文为证：引证卡，核验过的盖朱砂钤印 */}
      {answer.citations.length > 0 && (
        <div>
          <h3 className="text-xs tracking-wider text-[var(--color-ink-muted)] mb-3">
            原文为证 · {answer.citations.length} 条
          </h3>
          <ol className="space-y-3">
            {answer.citations.map((c, idx) => {
              const stamped =
                c.match_type === "quote" || c.match_type === "paraphrase";
              return (
                <li
                  key={idx}
                  className="relative rounded-md border px-3.5 py-3"
                  style={{
                    borderColor: "var(--color-folio-edge)",
                    background: "var(--color-paper-raised)",
                  }}
                >
                  {stamped && (
                    <SealMark
                      className="seal-stamp absolute top-2.5 right-2.5"
                      title={
                        c.match_type === "quote"
                          ? "逐字核验过原文，盖章为证"
                          : "据原文转述，已核验"
                      }
                    />
                  )}
                  <div className="text-xs text-[var(--color-ink-muted)] mb-1.5 flex items-center gap-2 pr-9">
                    <span>第 {c.chapter} 章</span>
                    {c.match_type === "quote" && (
                      <span style={{ color: "var(--color-seal)" }}>逐字核验</span>
                    )}
                    {c.match_type === "paraphrase" && <span>据原文转述</span>}
                    {c.match_type === "none" && (
                      <span className="italic">未核验</span>
                    )}
                    {c.claim_support === "weak" && (
                      <span
                        className="px-1.5 py-0.5 rounded text-caption font-medium"
                        style={{
                          color: "var(--color-seal)",
                          border: "1px solid var(--color-seal)",
                        }}
                        title="这条引用是真的，但未必撑得起答案的论断，建议自己再看一眼原文"
                      >
                        弱支撑
                      </span>
                    )}
                  </div>
                  <div
                    className="text-body leading-relaxed text-[var(--color-ink)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {c.snippet}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      <details className="text-xs text-[var(--color-ink-muted)]">
        <summary className="cursor-pointer">trace（可观测性）</summary>
        <pre className="mt-2 p-3 bg-black/5 rounded overflow-x-auto">
          {JSON.stringify(answer.trace, null, 2)}
        </pre>
      </details>
    </article>
  );
}

// 清缓存（§五：从设置抽屉底部挪到左栏底，用户找得到的显眼小入口）。
// 自带状态 + 调 /api/cache/clear，文案点明「只清分析结果、书和卷宗都不动」——跟「清空卷宗」
// （只清选的文档组）划清边界，两个「清」别再混。
function ClearCacheButton() {
  const [clearing, setClearing] = useState(false);
  const [msg, setMsg] = useState("");
  async function handleClear() {
    if (clearing) return;
    setClearing(true);
    setMsg("");
    try {
      const resp = await fetch("/api/cache/clear", { method: "POST" });
      setMsg(resp.ok ? "已清，下次分析重算" : "清理失败，稍后再试");
    } catch {
      setMsg("清理失败，稍后再试");
    } finally {
      setClearing(false);
      // 提示两秒后淡出，不长留占位
      setTimeout(() => setMsg(""), 2600);
    }
  }
  return (
    <div className="relative">
      <button
        type="button"
        onClick={handleClear}
        disabled={clearing}
        aria-label="清分析缓存"
        title="清分析缓存：只清分析结果，下次重算会重新花 token，书和卷宗都不动"
        className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-body-sm text-[var(--color-ink-muted)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
      >
        {/* 刷新 / 重算意象的小图标 */}
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
          <path d="M21 3v5h-5" />
          <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
          <path d="M3 21v-5h5" />
        </svg>
        {clearing ? "清理中…" : "清缓存"}
      </button>
      {msg && (
        <span
          className="absolute left-0 -top-5 whitespace-nowrap text-caption text-[var(--color-seal)]"
          role="status"
        >
          {msg}
        </span>
      )}
    </div>
  );
}

function SettingsDrawer(props: {
  provider: Provider;
  setProvider: (p: Provider) => void;
  apiKey: string;
  setApiKey: (s: string) => void;
  model: string;
  setModel: (s: string) => void;
  baseUrl: string;
  setBaseUrl: (s: string) => void;
  autoSuggestEnabled: boolean;
  setAutoSuggestEnabled: (b: boolean) => void;
  theme: ThemeMode;
  setTheme: (t: ThemeMode) => void;
  /** 「笔记只留本地」开关：托管版默认上账号同步，打开＝只存这台设备。 */
  notesLocalOnly: boolean;
  setNotesLocalOnly: (b: boolean) => void;
  /** 是否托管版（只有托管版才有账号可同步，本地版不显这个开关）。 */
  accountSyncAvailable: boolean;
  onClose: () => void;
}) {
  const {
    onClose,
    autoSuggestEnabled,
    setAutoSuggestEnabled,
    theme,
    setTheme,
    notesLocalOnly,
    setNotesLocalOnly,
    accountSyncAvailable,
    ...config
  } = props;
  return (
    <div
      className="reveal mt-6 rounded-lg border border-[var(--color-rule)] p-4"
      style={{
        background: "var(--color-paper-raised)",
        boxShadow: "var(--shadow-soft)",
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <h2
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          设置 · LLM 配置
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭设置"
          className="inline-flex items-center justify-center w-7 h-7 rounded-md text-[var(--color-ink-muted)] hover:text-[var(--color-seal)]"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <ProviderConfig {...config} />
      <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
        API key 只存在本地浏览器、随请求直发你选的 LLM，不经过 BookScope 服务器。
      </p>

      <div
        className="mt-4 pt-4 flex items-start justify-between gap-4"
        style={{ borderTop: "1px solid var(--color-rule)" }}
      >
        <div className="min-w-0">
          <div
            className="text-sm text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
          >
            自动建议编排
          </div>
          <p className="mt-1 text-xs text-[var(--color-ink-muted)] leading-relaxed">
            问到开放问题、或连看了好几个分析时，温和提示「要不要 agent 编排着跑」。只是建议、不打断你；不想看就关掉。
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={autoSuggestEnabled}
          onClick={() => setAutoSuggestEnabled(!autoSuggestEnabled)}
          className="relative shrink-0 mt-0.5 inline-flex h-6 w-11 items-center rounded-full transition-colors"
          style={{
            background: autoSuggestEnabled
              ? "var(--color-seal)"
              : "var(--color-rule)",
          }}
        >
          <span
            className="inline-block h-4.5 w-4.5 rounded-full bg-white transition-transform"
            style={{
              transform: autoSuggestEnabled
                ? "translateX(1.4rem)"
                : "translateX(0.18rem)",
              width: "1.05rem",
              height: "1.05rem",
            }}
          />
        </button>
      </div>

      {/* 笔记只留本地（托管版才显；本地版根本没账号，用不到这个开关） */}
      {accountSyncAvailable && (
        <div
          className="mt-4 pt-4 flex items-start justify-between gap-4"
          style={{ borderTop: "1px solid var(--color-rule)" }}
        >
          <div className="min-w-0">
            <div
              className="text-sm text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
            >
              笔记只留本地
            </div>
            <p className="mt-1 text-xs text-[var(--color-ink-muted)] leading-relaxed">
              默认把你的笔记、高亮、书签存到账号，换设备登录能接着看。打开这个开关，往后的笔记就只存在这台设备的浏览器里、不上账号，换设备也带不走。图个清净的隐私党可以开。
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={notesLocalOnly}
            aria-label="笔记只留本地，不上账号同步"
            onClick={() => setNotesLocalOnly(!notesLocalOnly)}
            className="relative shrink-0 mt-0.5 inline-flex h-6 w-11 items-center rounded-full transition-colors"
            style={{
              background: notesLocalOnly
                ? "var(--color-seal)"
                : "var(--color-rule)",
            }}
          >
            <span
              className="inline-block rounded-full bg-white transition-transform"
              style={{
                transform: notesLocalOnly
                  ? "translateX(1.4rem)"
                  : "translateX(0.18rem)",
                width: "1.05rem",
                height: "1.05rem",
              }}
            />
          </button>
        </div>
      )}

      {/* 暗色主题(#20) */}
      <div
        className="mt-4 pt-4 flex items-start justify-between gap-4"
        style={{ borderTop: "1px solid var(--color-rule)" }}
      >
        <div className="min-w-0">
          <div
            className="text-sm text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
          >
            暗色主题
          </div>
          <p className="mt-1 text-xs text-[var(--color-ink-muted)] leading-relaxed">
            护眼的暗色案头（暖炭墨调，不是冷黑）。设置存在本地，刷新不丢。
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={theme === "dark"}
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="relative shrink-0 mt-0.5 inline-flex h-6 w-11 items-center rounded-full transition-colors"
          style={{
            background:
              theme === "dark" ? "var(--color-seal)" : "var(--color-rule)",
          }}
        >
          <span
            className="inline-block rounded-full bg-white transition-transform"
            style={{
              transform:
                theme === "dark" ? "translateX(1.4rem)" : "translateX(0.18rem)",
              width: "1.05rem",
              height: "1.05rem",
            }}
          />
        </button>
      </div>

      {/* §五:清分析缓存已挪到左栏底(ClearCacheButton)——高频动作不该埋在设置抽屉底部、
          跟「配 API key」这种一次性配置挤一个抽屉。设置里不再放清缓存。 */}

      {/* 关于(#20) */}
      <div
        className="mt-4 pt-4 text-xs text-[var(--color-ink-muted)] leading-relaxed"
        style={{ borderTop: "1px solid var(--color-rule)" }}
      >
        <div
          className="text-sm text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
        >
          关于
        </div>
        书鉴 · BookScope v{APP_VERSION}，查询时智能代理 + 原文证据的深读引擎。BYOK：你的
        key 只存本地、随请求直发你选的 LLM，不经 BookScope 服务器。
        <a
          href="https://github.com/moyu-good/BookScope"
          target="_blank"
          rel="noreferrer"
          className="ml-1 text-[var(--color-seal)] hover:underline"
        >
          代码仓库
        </a>
      </div>
    </div>
  );
}

// 主页"大写特写"特化展示:按文本类型组织,每类亮它的招牌深读——这是 BookScope 的卖点
// (不是通用摘要,选一本自动认出类型上对应深读)。WP-home-specialization。
const TYPE_SHOWCASE: { type: string; sig: string }[] = [
  { type: "公文 / 红头文件", sig: "利害与风向（机会·风险·含金量）· 依据链网 · 公文结构 · 大白话逐句" },
  { type: "小说 / 网文", sig: "人物关系与演变 · 人物弧线 · 伏笔回收 · 节奏曲线" },
  { type: "历史", sig: "时间线 · 人物关系 · 节奏曲线 · 母题追踪" },
  { type: "理论 / 哲学 / 社科", sig: "论点结构 · 概念演进 · 概念关系图" },
  { type: "论文 / 工具书 / 诗歌", sig: "按体裁各有侧重；问书 / 精读 / 时间线等通用深读各类都能用" },
];

function CapabilityShowcase() {
  return (
    <section className="mt-10">
      <p
        className="text-sm font-bold text-[var(--color-ink)] mb-1"
        style={{ fontFamily: "var(--font-display)" }}
      >
        不做通用摘要，每类文本各有各的深读
      </p>
      <p className="text-sm text-[var(--color-ink-muted)] mb-4 leading-relaxed">
        从上面书架挑一本。它先认出这是哪一类书，再给这类书该有的那套深读；每个结论都能翻到原文，点开就核。
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 stagger">
        {TYPE_SHOWCASE.map((c) => (
          <div
            key={c.type}
            className="rounded-lg border border-[var(--color-rule)] p-4"
            style={{
              background: "var(--color-paper-raised)",
              boxShadow: "var(--shadow-soft)",
            }}
          >
            <div
              className="text-sm font-bold text-[var(--color-ink)] mb-1"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {c.type}
            </div>
            <div className="text-xs text-[var(--color-ink-muted)] leading-relaxed">
              {c.sig}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="mt-16 pt-6 border-t border-[var(--color-rule)] text-xs text-[var(--color-ink-muted)]">
      <p>
        BookScope r1-agent-loop · BYOK · API key 仅本地会话，不持久化 · 代码 MIT
      </p>
    </footer>
  );
}

function Label({
  htmlFor,
  children,
}: {
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="text-sm text-[var(--color-ink-muted)] min-w-[5rem]"
    >
      {children}
    </label>
  );
}

function SubmitButton({
  loading,
  disabled,
  label,
  loadingLabel,
}: {
  loading: boolean;
  disabled: boolean;
  label: string;
  loadingLabel: string;
}) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className="inline-flex items-center gap-2 bg-[var(--color-seal)] text-white px-5 py-2 rounded hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed text-sm transition-all"
      style={{ fontFamily: "var(--font-display)" }}
    >
      {loading ? (
        <>
          <span className="animate-pulse">●</span>
          {loadingLabel}
        </>
      ) : (
        label
      )}
    </button>
  );
}
