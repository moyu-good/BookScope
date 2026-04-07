/**
 * BookScope API client.
 *
 * All calls go through the Vite dev proxy (/api → localhost:8000).
 */

const BASE = "/api";

// ── Types ────────────────────────────────────────────────────────────────────

export interface UploadResponse {
  session_id: string;
  title: string;
  language: string;
  total_chunks: number;
  total_words: number;
}

export interface SessionResponse {
  session_id: string;
  title: string;
  language: string;
  total_chunks: number;
  total_words: number;
  has_analysis: boolean;
  has_knowledge_graph: boolean;
}

export interface AnalysisProgress {
  type: "progress";
  stage: string;
  current: number;
  total: number;
}

export interface ReadabilityInfo {
  score: number;
  label: string;
  confidence: number;
}

export interface ReaderVerdict {
  sentence: string;
  for_you: string;
  not_for_you: string;
  confidence: number;
}

export interface AnalysisResult {
  type: "done";
  emotion_scores: EmotionScore[];
  style_scores: StyleScore[];
  arc_pattern: string;
  dominant_emotion: string;
  valence_series: number[];
  readability: ReadabilityInfo;
  reader_verdict: ReaderVerdict;
}

export interface EmotionScore {
  chunk_index: number;
  anger: number;
  anticipation: number;
  disgust: number;
  fear: number;
  joy: number;
  sadness: number;
  surprise: number;
  trust: number;
  emotion_density: number;
}

export interface StyleScore {
  chunk_index: number;
  avg_sentence_length: number;
  ttr: number;
  noun_ratio: number;
  verb_ratio: number;
  adj_ratio: number;
  adv_ratio: number;
}

export interface EmotionOverview {
  emotions: Record<string, number>;
  dominant_emotion: string;
  emotion_density_avg: number;
}

export interface HeatmapData {
  chunk_labels: string[];
  emotion_labels: string[];
  matrix: number[][];
}

export interface TimelineData {
  chunk_indices: number[];
  series: Record<string, number[]>;
}

export interface StyleRadarData {
  metrics: Record<string, number>;
}

export interface ArcPatternData {
  arc_pattern: string;
  valence_series: number[];
}

export interface SearchResult {
  chunk_index: number;
  text_preview: string;
  highlight_positions: number[][];
  match_count: number;
}

export interface ChatMessage {
  type: "message" | "done";
  content?: string;
}

// ── Upload ───────────────────────────────────────────────────────────────────

export async function uploadFile(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
}

// ── Session ──────────────────────────────────────────────────────────────────

export async function getSession(
  sessionId: string
): Promise<SessionResponse> {
  const res = await fetch(`${BASE}/session/${sessionId}`);
  if (!res.ok) throw new Error(`Session not found: ${res.status}`);
  return res.json();
}

// ── Analysis (SSE) ───────────────────────────────────────────────────────────

export function analyzeSSE(
  sessionId: string,
  bookType: string,
  uiLang: string,
  onProgress: (data: AnalysisProgress) => void,
  onDone: (result: AnalysisResult) => void,
  onError: (err: Error) => void
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      book_type: bookType,
      ui_lang: uiLang,
    }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`Analyze failed: ${res.status}`);
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const json = line.slice(6);
          try {
            const data = JSON.parse(json);
            if (data.type === "progress") onProgress(data);
            else if (data.type === "done") onDone(data);
          } catch {
            // skip malformed lines
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== "AbortError") onError(err);
    });

  return controller;
}

// ── Charts ───────────────────────────────────────────────────────────────────

export async function fetchEmotionOverview(
  sessionId: string
): Promise<EmotionOverview> {
  const res = await fetch(`${BASE}/charts/${sessionId}/emotion-overview`);
  if (!res.ok) throw new Error(`Chart fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchHeatmap(
  sessionId: string
): Promise<HeatmapData> {
  const res = await fetch(`${BASE}/charts/${sessionId}/emotion-heatmap`);
  if (!res.ok) throw new Error(`Chart fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchTimeline(
  sessionId: string
): Promise<TimelineData> {
  const res = await fetch(`${BASE}/charts/${sessionId}/emotion-timeline`);
  if (!res.ok) throw new Error(`Chart fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchStyleRadar(
  sessionId: string
): Promise<StyleRadarData> {
  const res = await fetch(`${BASE}/charts/${sessionId}/style-radar`);
  if (!res.ok) throw new Error(`Chart fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchArcPattern(
  sessionId: string
): Promise<ArcPatternData> {
  const res = await fetch(`${BASE}/charts/${sessionId}/arc-pattern`);
  if (!res.ok) throw new Error(`Chart fetch failed: ${res.status}`);
  return res.json();
}

// ── Search ───────────────────────────────────────────────────────────────────

export async function searchChunks(
  sessionId: string,
  query: string
): Promise<{ total_matches: number; results: SearchResult[] }> {
  const res = await fetch(`${BASE}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, query }),
  });
  if (!res.ok) throw new Error(`Search failed: ${res.status}`);
  return res.json();
}

// ── Chat (SSE) ───────────────────────────────────────────────────────────────

export function chatSSE(
  sessionId: string,
  message: string,
  uiLang: string,
  onMessage: (content: string) => void,
  onDone: () => void,
  onError: (err: Error) => void,
  characterName?: string
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      ui_lang: uiLang,
      character_name: characterName || null,
    }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`Chat failed: ${res.status}`);
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data: ChatMessage = JSON.parse(line.slice(6));
            if (data.type === "message" && data.content) onMessage(data.content);
            else if (data.type === "done") onDone();
          } catch {
            // skip
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== "AbortError") onError(err);
    });

  return controller;
}
