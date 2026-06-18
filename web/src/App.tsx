import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { BookShelf } from "./BookShelf";
import type { SessionMetadata } from "./BookShelf";
import { AgentOrchestrate } from "./AgentOrchestrate";
import type { DrillInfo } from "./AgentOrchestrate";
import { AnnotatedReader } from "./AnnotatedReader";
import { ArgumentStructure } from "./ArgumentStructure";
import { CharacterArc } from "./CharacterArc";
import { CharacterFlow } from "./CharacterFlow";
import { CharacterGraph } from "./CharacterGraph";
import { CharacterVoice } from "./CharacterVoice";
import { ConceptEvolution } from "./ConceptEvolution";
import { ConsistencyScan } from "./ConsistencyScan";
import { EntityRecall } from "./EntityRecall";
import { ErrorBanner } from "./ErrorBanner";
import { ForeshadowArcs } from "./ForeshadowArcs";
import { NarrativeCurve } from "./NarrativeCurve";
import { PacingCurve } from "./PacingCurve";
import { Timeline } from "./Timeline";
import type { ApiError } from "./ErrorBanner";
import { HistoryPanel } from "./HistoryPanel";
import { MotifTracking } from "./MotifTracking";
import { appendEntry, newEntryId } from "./historyStorage";
import type { QAEntry } from "./historyStorage";
import { Onboarding } from "./Onboarding";
import { QuestionBreakdown } from "./QuestionBreakdown";
import { Recap } from "./Recap";
import { RelationshipTimeline } from "./RelationshipTimeline";
import { RevisionList } from "./RevisionList";
import type {
  Difficulty,
  QuestionProcessedState,
} from "./QuestionBreakdown";
import { RouteDecisionBanner } from "./RouteDecisionBanner";
import { SealMark } from "./SealMark";
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
    return {
      provider: parsed.provider as Provider,
      apiKey: parsed.apiKey,
      model: parsed.model ?? "",
      baseUrl: parsed.baseUrl ?? "",
    };
  } catch {
    return null;
  }
}

function savePersistedConfig(config: PersistedConfig): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(config));
  } catch {
    // 隐私模式 / 配额满 / SSR ——失败默默忽略不阻断主流程
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
  // app-shell 当前主画布显示哪一件事（左栏导航切换）
  const [mode, setMode] = useState<
    | "library"
    | "ask"
    | "annotate"
    | "graph"
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
    | "style"
    | "recap"
    | "concept"
    | "motif"
    | "technique"
    | "cards"
    | "revision"
  >("library");
  // 手机端左栏收成抽屉，这个控制开合
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // 配置变化时同步写 localStorage
  useEffect(() => {
    savePersistedConfig({ provider, apiKey, model, baseUrl });
  }, [provider, apiKey, model, baseUrl]);

  // 上传区
  const [file, setFile] = useState<File | null>(null);
  const [bookTitle, setBookTitle] = useState("");
  const [language, setLanguage] = useState("zh");
  const [uploading, setUploading] = useState(false);
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

  // 书柜刷新触发器：上传成功后 + 删除成功后递增
  const [shelfRefresh, setShelfRefresh] = useState(0);
  // 上传成功后让书柜自动选中新书
  const [pendingAutoSelectId, setPendingAutoSelectId] = useState<string | null>(
    null,
  );

  // 问书两条路：question=随便问（原 ask 路径，不动）；goal=给目标（agent 编排路径）
  const [askMode, setAskMode] = useState<"question" | "goal">("question");

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
  }, [currentSession?.session_id]);

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
    setMode("ask");
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

  function effectiveBaseUrl(): string {
    // 仅 deepseek 走 base_url（代理 / 其他 OpenAI 兼容 endpoint）；anthropic 后端会忽略
    if (provider === "anthropic") return "";
    return baseUrl.trim();
  }

  async function handleUpload(e: FormEvent) {
    e.preventDefault();
    if (!file || !bookTitle || !apiKey) return;
    setError(null);
    setUploading(true);
    setIngestProgress(INGEST_PROGRESS_INITIAL);
    try {
      let finalResult: UploadResponse | null = null;
      const stream = streamUploadBook({
        file,
        bookTitle,
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
          const {
            event_type: _et,
            ...rest
          } = event as UploadCompleteFrame;
          finalResult = rest as UploadResponse;
        } else if (event.event_type === "upload_error") {
          // SSE 流内 ingest 失败 —— 翻译成 ErrorBanner
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
      setLastUpload(finalResult);
      uploadedSessionIdsRef.current.add(finalResult.session_id);
      setHasUploaded(true);
      // 让书柜重新拉 list 并自动选中新书
      setPendingAutoSelectId(finalResult.session_id);
      setShelfRefresh((n) => n + 1);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setUploading(false);
      setIngestProgress(null);
    }
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

  return (
    <div className="min-h-screen md:p-3">
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
        open={sidebarOpen}
        onOpenSettings={() => {
          setSettingsOpen(true);
          setSidebarOpen(false);
        }}
      />

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
              先填一个 LLM 的 API key 才能用——点这里去
              <span style={{ color: "var(--color-seal)" }}>设置</span>
              （左栏底部，自带的 key、不上传服务器）。
            </button>
          )}

          {/* 主画布：一次只显示一件事 */}
          {(mode === "library" || !currentSession) && (
            <section>
              <CanvasHeader
                title="选一本书"
                subtitle="从书库挑一本，或上传新的——选定后左栏会列出能对它做的事。"
              />
              {!currentSession && <CapabilityShowcase />}
              <Onboarding type="first_visit" triggered />
              <BookShelf
                activeSessionId={currentSession?.session_id ?? null}
                onSelect={handleSelectShelfBook}
                onDeleted={handleDeletedShelfBook}
                refreshTrigger={shelfRefresh}
                pendingAutoSelectId={pendingAutoSelectId}
                onAutoSelected={handleAutoSelected}
              />
              <Onboarding
                type="first_switch"
                triggered={hasSwitched}
                bookTitle={currentSession?.book_title ?? ""}
              />
              {DEMO ? (
                <div className="mt-6 pt-5 border-t border-[var(--color-rule)]">
                  <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed">
                    这是只读演示，预置了一本《三国演义》的真实分析结果。想分析
                    <strong>你自己的书</strong>（epub / txt / pdf）？{" "}
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
                    书架里没有？上传一本新的（epub / txt / pdf）：
                  </p>
                  <UploadForm
                    file={file}
                    setFile={setFile}
                    bookTitle={bookTitle}
                    setBookTitle={setBookTitle}
                    language={language}
                    setLanguage={setLanguage}
                    uploading={uploading}
                    session={lastUpload}
                    onSubmit={handleUpload}
                    canSubmit={!!file && !!bookTitle && !!apiKey}
                    ingestProgress={ingestProgress}
                  />
                </div>
              )}
            </section>
          )}

          {currentSession && (
            <>
              <div className={mode === "ask" ? "" : "hidden"}>
                <CanvasHeader
                  title="问书"
                  subtitle={`在读《${currentSession.book_title}》——带原文证据答深问题，没出处的结论一概不给。`}
                />
                <Onboarding type="first_upload" triggered={hasUploaded} />
                {/* 随便问 ↔ 给目标：前者走原问答（不动）；后者让 agent 自己编排该跑哪几个分析 */}
                {!DEMO && (
                  <AskModeToggle mode={askMode} onChange={setAskMode} />
                )}
                {askMode === "question" || DEMO ? (
                  <>
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
                  />
                )}
              </div>

              <div className={mode === "annotate" ? "" : "hidden"}>
                <CanvasHeader
                  title="精读"
                  subtitle="读原文本身——读到某处行间浮一条带原文证据的批注（这里埋了伏笔、这句和别章矛盾、某母题又一次复现）。选要哪几层，点朱砂记号看批注 + 原文，跨章批注一键跳到它牵连的另一处。"
                />
                <AnnotatedReader
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "graph" ? "" : "hidden"}>
                <CanvasHeader
                  title="关系图"
                  subtitle="谁和谁、什么关系——切换人物 / 概念两种单位，每条边点得到原文。"
                />
                <CharacterGraph
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "reltime" ? "" : "hidden"}>
                <CanvasHeader
                  title="关系演变"
                  subtitle="给关系网加一根时间轴——拖到第几章看那一刻谁和谁多亲近，或选一对人看关系怎么一章章走到这一步，每个转折钉在原文。"
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
                  subtitle="每人一条横线穿过全书——同章同场聚成束、退场线止。一眼看见谁何时入场、哪几章是群戏，点束看原文。"
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
                  subtitle="给主要角色画两条曲线——戏份密度看谁何时主导这本书，处境升降看谁过得顺不顺。渐变写成平滑爬升、硬扳写成直角拐弯，点起伏点看原文。"
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
                  subtitle="给一个角色归拢他全书的对白，刻画说话的腔调，再标出哪几句「不像他说的」——合理的剧情驱动口吻变化不报，每条挂原文，你自己判断。"
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
                  subtitle="每条伏笔从埋点章拱到回收点章画一道弧——埋了没回收的画成灰虚线悬空，一眼挑出没填的坑，点弧看两端原文。"
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
                  subtitle="每条情节支线一条横向泳道——活跃段亮、休眠段灰断，两条线同章交汇画连接节点。一眼看见哪条支线断更太久、哪几章是多线交汇的高潮，点活跃段 / 交汇看原文。"
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
                  subtitle="多线、倒叙也理清真实的时间先后，每条事件钉在原文。"
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
                  title="实体回溯"
                  feature="entity"
                  subtitle="输一个人 / 物 / 地点 / 概念，回溯它在全书每次出现——在做什么、在哪章、带原文。"
                />
                <EntityRecall
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                  prefill={entityPrefill}
                />
              </div>

              <div className={mode === "recap" ? "" : "hidden"}>
                <CanvasHeader
                  title="前情回顾"
                  feature="recap"
                  subtitle="读到第几章告诉我，回顾到此为止的前情——后文绝不剧透（模型根本看不到后文）。"
                />
                <Recap
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "motif" ? "" : "hidden"}>
                <CanvasHeader
                  title="母题追踪"
                  feature="motif"
                  subtitle="输一个主题/母题，看它在全书哪些地方复现——每处怎么体现、在哪章，带原文。"
                />
                <MotifTracking
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                  prefill={motifPrefill}
                />
              </div>

              <div className={mode === "pacing" ? "" : "hidden"}>
                <CanvasHeader
                  title="节奏"
                  feature="pacing"
                  subtitle="逐章看张力高低——哪几章松、哪几章是高潮，点柱看依据。"
                />
                <PacingCurve
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
                  subtitle="一道章节横轴叠四维——张力起落、情感正负、视角切换、主/支线，看出整本书的形状，点章看依据。"
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
                  subtitle="扫全书前后矛盾——每条两处对照原文，编出来的会被滤掉。"
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
                  subtitle="拆这本书的论证骨架——作者主张了什么、靠什么撑，每条钉在原文。"
                />
                <ArgumentStructure
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                />
              </div>

              <div className={mode === "concept" ? "" : "hidden"}>
                <CanvasHeader
                  title="概念演进"
                  feature="concept"
                  subtitle="输一个概念，看它在全书怎么一步步发展——每阶段在哪章、被怎么用/深化，带原文。"
                />
                <ConceptEvolution
                  sessionId={currentSession.session_id}
                  provider={provider}
                  apiKey={apiKey}
                  model={model}
                  baseUrl={effectiveBaseUrl()}
                  prefill={conceptPrefill}
                />
              </div>

              <div className={mode === "technique" ? "" : "hidden"}>
                <CanvasHeader
                  title="写作手法"
                  feature="technique"
                  subtitle="看作者怎么写——论证 / 结构 / 铺陈 / 用语的手法，每条配原文例子，学手艺。"
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
                  subtitle="据书出知识点卡——每张一道启发自测题，先自己想，再翻看解释和原文。"
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
                  subtitle="扫用词重复 / 视角越界 / 支线失踪——保守只报清楚的，每条钉原文，编的滤掉。"
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
                  subtitle="把扫出的矛盾 / 断伏笔 / 塌节奏 / 文体毛病攒成一份带原文的修改清单——逐条勾「待改 / 已改 / 不改」，改完一键导出带走。核不过原文的发现不进清单。"
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
            </>
          )}

          <Footer />
        </div>
      </main>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 子组件
// ---------------------------------------------------------------------------

type Mode =
  | "library"
  | "ask"
  | "annotate"
  | "graph"
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
  | "style"
  | "recap"
  | "concept"
  | "motif"
  | "technique"
  | "cards"
  | "revision";

const NAV_MODES: { id: Mode; label: string }[] = [
  { id: "ask", label: "问书" },
  { id: "annotate", label: "精读" },
  { id: "graph", label: "关系图" },
  { id: "reltime", label: "关系演变" },
  { id: "flow", label: "叙事流" },
  { id: "chararc", label: "人物弧线" },
  { id: "charvoice", label: "声口一致" },
  { id: "foreshadow", label: "伏笔回收" },
  { id: "subplot", label: "支线编织" },
  { id: "timeline", label: "时间线" },
  { id: "entity", label: "实体回溯" },
  { id: "recap", label: "前情回顾" },
  { id: "motif", label: "母题追踪" },
  { id: "pacing", label: "节奏" },
  { id: "narrative", label: "叙事曲线" },
  { id: "consistency", label: "一致性" },
  { id: "argument", label: "论点结构" },
  { id: "concept", label: "概念演进" },
  { id: "technique", label: "写作手法" },
  { id: "cards", label: "知识卡片" },
  { id: "style", label: "文体体检" },
  { id: "revision", label: "改稿清单" },
];

// agent 编排菜单的功能名（后端 orchestrate FEATURE_MENU 的键）→ App 的 mode。
// drill-into 用：点「点开看完整 X 视图」时据功能名跳进左栏那个功能的完整视图。
const FEATURE_TO_MODE: Record<string, Mode> = {
  character_graph: "graph",
  character_flow: "flow",
  timeline: "timeline",
  consistency: "consistency",
  entity_recall: "entity",
  concept_evolution: "concept",
  motif: "motif",
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

// 细线 SVG 导航图标——不用 emoji、不引图标库
function NavIcon({
  id,
  size = 17,
}: {
  id: Mode | "settings";
  size?: number;
}) {
  const paths: Record<string, React.ReactNode> = {
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
    pacing: <path d="M5 20v-9M10 20V5M15 20v-6M20 20V8" />,
    narrative: (
      <>
        <path d="M3 12c2-7 4 5 6-1s4 4 6-2 4 3 6-1" />
        <path d="M3 18h18" />
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
  open: boolean;
  onOpenSettings: () => void;
}) {
  const { mode, onMode, currentBook, hasBook, open, onOpenSettings } = props;
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
            className="mt-1 rounded-full px-2 py-0.5 text-[10px] tracking-wide"
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
        <div className="text-[10.5px] tracking-wider text-[var(--color-ink-muted)] mb-1.5 text-center">
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
            <div className="text-[10.5px] text-[var(--color-ink-muted)] mt-0.5">
              {currentBook.language}
            </div>
          </div>
        ) : (
          <div className="text-xs text-[var(--color-ink-muted)] italic text-center">
            还没择书
          </div>
        )}
      </div>

      {/* 模式导航——图标 + 一个词，活动项朱砂左边线 + 淡底；功能说明在主区标题下 */}
      <nav className="flex-1 px-2.5 overflow-y-auto">
        <ul className="space-y-0.5">
          {NAV_MODES.map((m) => {
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
                    className="text-[13.5px]"
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
      </nav>

      {/* 底部：书库 + 设置 一行 */}
      <div
        className="px-3 py-3.5 mt-auto flex items-center justify-between"
        style={{ borderTop: "1px solid var(--color-rule)" }}
      >
        <button
          type="button"
          onClick={() => onMode("library")}
          className="inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] transition-colors"
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
    "一个人 / 物 / 概念在全书每次出现的轨迹——在哪章、在做什么、原文为证。",
  recap: "读到第几章就回顾到第几章的前情要点——后文一个字都不剧透。",
  motif: "一个主题 / 母题在全书哪些地方复现、各处怎么体现，每处钉原文。",
  foreshadow:
    "每条伏笔从埋点章拱到回收点章画一道弧——埋了没回收的画成灰虚线悬空，一眼挑出没填的坑，点弧看两端原文。",
  subplot:
    "每条情节支线一条横向泳道——活跃段亮、休眠段灰断，两条线同章交汇画连接节点。一眼看见哪条支线断更太久、哪几章是多线交汇的高潮，点活跃段 / 交汇看两段勾连原文。",
  pacing: "逐章的张力曲线——哪几章松（拖沓）、哪几章是高潮，点柱看依据。",
  narrative:
    "一道横轴叠四维——张力起落 + 情感正负 + 视角切换 + 主/支线，看出整本书是个什么形状，每章钉原文。",
  consistency:
    "全书前后矛盾的两处对照（如第 5 章左撇子、第 80 章用右手），编的会被滤掉。",
  argument: "作者的论证骨架——主张 + 撑住它的原文 + 在哪章，一条条理清。",
  concept: "一个概念在全书怎么从提出走到深化，分阶段、每段带原文。",
  technique: "作者怎么写——论证 / 结构 / 铺陈的手法，每条配一句原文例子。",
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
          className="text-2xl md:text-[1.7rem] leading-tight text-[var(--color-ink)]"
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
            className="text-[14px] leading-relaxed text-[var(--color-ink)]"
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
              每条结论都钉在原文上、核验过才盖章显示——没出处的不编、不输出。
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
// 模型名按各厂商公开档列，BYOK 用户可随时改写——下面 select 留了"自定义"口子。
interface ProviderPreset {
  id: string;
  label: string;
  backend: Provider;
  baseUrl: string;
  models: { value: string; label: string }[];
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
      { value: "deepseek-v4", label: "deepseek-v4 · 更强" },
      { value: "deepseek-reasoner", label: "deepseek-reasoner · 推理" },
    ],
  },
  {
    id: "zhipu",
    label: "智谱 GLM",
    backend: "deepseek",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    models: [
      { value: "glm-4.6", label: "glm-4.6" },
      { value: "glm-4.5", label: "glm-4.5" },
      { value: "glm-4-flash", label: "glm-4-flash · 便宜" },
    ],
  },
  {
    id: "qwen",
    label: "阿里 通义千问",
    backend: "deepseek",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    models: [
      { value: "qwen-max", label: "qwen-max" },
      { value: "qwen-plus", label: "qwen-plus" },
      { value: "qwen-turbo", label: "qwen-turbo · 便宜" },
    ],
  },
  {
    id: "moonshot",
    label: "月之暗面 Kimi",
    backend: "deepseek",
    baseUrl: "https://api.moonshot.cn/v1",
    models: [
      { value: "kimi-k2-0905-preview", label: "kimi-k2" },
      { value: "moonshot-v1-128k", label: "moonshot-v1-128k" },
      { value: "moonshot-v1-32k", label: "moonshot-v1-32k" },
    ],
  },
  {
    id: "anthropic",
    label: "Anthropic Claude",
    backend: "anthropic",
    baseUrl: "",
    models: [
      { value: "", label: "claude-sonnet-4-6 · 默认" },
      { value: "claude-opus-4-8", label: "claude-opus-4-8 · 最强" },
      { value: "claude-haiku-4-5-20251001", label: "claude-haiku-4-5 · 便宜" },
    ],
  },
  {
    id: "openai",
    label: "OpenAI",
    backend: "deepseek",
    baseUrl: "https://api.openai.com/v1",
    models: [
      { value: "gpt-4o", label: "gpt-4o" },
      { value: "gpt-4o-mini", label: "gpt-4o-mini · 便宜" },
      { value: "gpt-4.1", label: "gpt-4.1" },
    ],
  },
  {
    id: "gemini",
    label: "Google Gemini",
    backend: "deepseek",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/",
    models: [
      { value: "gemini-2.5-pro", label: "gemini-2.5-pro" },
      { value: "gemini-2.5-flash", label: "gemini-2.5-flash · 便宜" },
      { value: "gemini-2.0-flash", label: "gemini-2.0-flash" },
    ],
  },
  {
    id: "xai",
    label: "xAI Grok",
    backend: "deepseek",
    baseUrl: "https://api.x.ai/v1",
    models: [
      { value: "grok-4", label: "grok-4" },
      { value: "grok-3", label: "grok-3" },
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
        <select
          id="provider"
          value={preset.id}
          onChange={(e) => selectPreset(e.target.value)}
          className="rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm"
        >
          {PROVIDER_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-[auto_1fr] gap-3 items-center">
        <Label htmlFor="apikey">API Key</Label>
        <input
          id="apikey"
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="仅本地会话保存；刷新页面即失效"
          className="rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm"
        />
      </div>

      <div className="grid grid-cols-[auto_1fr] gap-3 items-start">
        <Label htmlFor="model">模型</Label>
        <div>
          <select
            id="model"
            value={isCustomModel ? CUSTOM_MODEL : model}
            onChange={(e) => {
              const v = e.target.value;
              setModel(v === CUSTOM_MODEL ? "" : v);
            }}
            className="w-full rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm"
          >
            {preset.models.map((m) => (
              <option key={m.value || "__default__"} value={m.value}>
                {m.label}
              </option>
            ))}
            <option value={CUSTOM_MODEL}>自定义…</option>
          </select>
          {isCustomModel && (
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="自己填模型名（按该厂商最新公布）"
              className="mt-2 w-full rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm font-mono"
            />
          )}
          <p className="text-[11px] text-[var(--color-ink-muted)] mt-1">
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
            className="rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm font-mono"
          />
        </div>
      )}

      <p className="text-[11px] text-[var(--color-ink-muted)] leading-relaxed">
        BYOK——key 自带、直发你选的厂商，BookScope 不内置任何 key。除 Anthropic 外都走
        OpenAI 兼容接口（选厂商即自动填好官方 Base URL）。
        {isProxiedDeepseek && " 当前 Base URL 是自定义代理/私有部署。"}
      </p>
    </div>
  );
}

function UploadForm(props: {
  file: File | null;
  setFile: (f: File | null) => void;
  bookTitle: string;
  setBookTitle: (s: string) => void;
  language: string;
  setLanguage: (s: string) => void;
  uploading: boolean;
  session: UploadResponse | null;
  onSubmit: (e: FormEvent) => void;
  canSubmit: boolean;
  ingestProgress: IngestProgressState | null;
}) {
  const {
    file,
    setFile,
    bookTitle,
    setBookTitle,
    language,
    setLanguage,
    uploading,
    session,
    onSubmit,
    canSubmit,
    ingestProgress,
  } = props;
  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <label
        htmlFor="file"
        className="border-2 border-dashed border-[var(--color-rule)] rounded-lg px-6 py-8 text-center cursor-pointer hover:border-[var(--color-seal)]/50 transition-colors"
      >
        <input
          id="file"
          type="file"
          accept=".epub,.txt,.pdf"
          onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            setFile(f);
            if (f && !bookTitle) {
              setBookTitle(f.name.replace(/\.(epub|txt|pdf)$/i, ""));
            }
          }}
          className="hidden"
        />
        <p className="text-sm">
          {file ? (
            <>
              <span className="font-medium">{file.name}</span>
              <span className="text-[var(--color-ink-muted)]">
                {" · "}
                {(file.size / 1024).toFixed(1)} KB
              </span>
            </>
          ) : (
            <span className="text-[var(--color-ink-muted)]">
              点击或拖放 epub / txt / pdf 文件
            </span>
          )}
        </p>
      </label>

      <div className="grid grid-cols-[auto_1fr_auto_1fr] gap-3 items-center">
        <Label htmlFor="title">书名</Label>
        <input
          id="title"
          value={bookTitle}
          onChange={(e) => setBookTitle(e.target.value)}
          required
          className="rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm"
        />
        <Label htmlFor="lang">语种</Label>
        <input
          id="lang"
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm font-mono w-24"
        />
      </div>

      <div className="flex items-center gap-4">
        <SubmitButton
          loading={uploading}
          disabled={!canSubmit || uploading}
          label="上传并解析"
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
        想问点什么？点一下试试，或者自己写一道——后端会自动判要不要深查。
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
          ? "问一个具体问题，后端自动判要不要深查——这是原来的问书。"
          : "说一个目标（不知道点哪个功能也行），agent 会自己挑该跑哪几个分析、串起来跑、综合成带原文证据的结论，每块还能点进完整视图。"}
      </p>
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
        className="rounded border border-[var(--color-rule)] bg-white px-3 py-2 text-sm resize-y min-h-[80px]"
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
      className="inline-flex items-center px-1.5 py-0.5 text-[11px] rounded-sm text-white align-baseline"
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
                  <span className="ml-2 normal-case text-[11px]">
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
          className="whitespace-pre-wrap leading-[1.85] text-[15.5px] text-[var(--color-ink)]"
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
                        className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                        style={{
                          color: "var(--color-seal)",
                          border: "1px solid var(--color-seal)",
                        }}
                        title="这条引用是真的，但未必撑得起答案的论断——建议自己再看一眼原文"
                      >
                        弱支撑
                      </span>
                    )}
                  </div>
                  <div
                    className="text-[14px] leading-relaxed text-[var(--color-ink)]"
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

function SettingsDrawer(props: {
  provider: Provider;
  setProvider: (p: Provider) => void;
  apiKey: string;
  setApiKey: (s: string) => void;
  model: string;
  setModel: (s: string) => void;
  baseUrl: string;
  setBaseUrl: (s: string) => void;
  onClose: () => void;
}) {
  const { onClose, ...config } = props;
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
    </div>
  );
}

const CAPABILITIES = [
  { t: "问书", d: "带原文证据答深问题——没出处的结论一概不输出" },
  { t: "人物关系图", d: "谁和谁、什么关系，每条边都点得到原文" },
  { t: "概念关系图", d: "理论书的概念怎么勾连，给学习者看脉络" },
  { t: "时间线", d: "多线、倒叙也理清真实的时间先后" },
  { t: "节奏曲线", d: "逐章看张力——哪几章松、哪几章是高潮" },
  { t: "设定一致性", d: "扫全书前后矛盾，编出来的会被滤掉" },
  { t: "每书出题", d: "据这本书出该问的诊断题，降低「不会问」的门槛" },
];

function CapabilityShowcase() {
  return (
    <section className="mt-10">
      <p className="text-sm text-[var(--color-ink-muted)] mb-4 leading-relaxed">
        选一本书，BookScope 替你深读——下面每件事都现读现答、每个结论钉在原文上：
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 stagger">
        {CAPABILITIES.map((c) => (
          <div
            key={c.t}
            className="rounded-lg border border-[var(--color-rule)] p-4 hover:border-[var(--color-seal)] transition-colors"
            style={{
              background: "var(--color-paper-raised)",
              boxShadow: "var(--shadow-soft)",
            }}
          >
            <div
              className="text-sm font-bold text-[var(--color-ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {c.t}
            </div>
            <div className="text-xs text-[var(--color-ink-muted)] mt-1 leading-relaxed">
              {c.d}
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
