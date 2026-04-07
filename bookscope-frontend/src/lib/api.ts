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

// ── Insight types ───────────────────────────────────────────────────────────

export interface NarrativeToken {
  type: "token" | "done" | "error";
  text?: string;
  message?: string;
}

export interface EmotionalStage {
  stage: string;
  emotion: string;
  event: string;
}

export interface SoulCharacter {
  name: string;
  aliases: string[];
  description: string;
  voice_style: string;
  motivations: string[];
  key_chapter_indices: number[];
  arc_summary: string;
  personality_type: string;
  key_quotes: string[];
  values: string[];
  emotional_stages: EmotionalStage[];
}

export interface SoulEnrichProgress {
  type: "progress" | "done";
  current?: number;
  total?: number;
  character?: string;
  characters?: SoulCharacter[];
}

export interface BookClubPack {
  questions: string[];
  difficulty: "Easy" | "Medium" | "Challenging";
  target_audience: string;
  arc_summary: string;
}

export interface BookRecommendation {
  title: string;
  author: string;
  reason: string;
}

export interface RecommendationsResponse {
  recommendations: BookRecommendation[];
}

// ── Library types ───────────────────────────────────────────────────────────

export interface LibraryItem {
  filename: string;
  path: string;
  title: string;
  arc_pattern: string;
  total_chunks: number;
  total_words: number;
  language: string;
  analyzed_at: string;
  tags: string[];
}

export interface LibraryListResponse {
  items: LibraryItem[];
  total: number;
}

export interface ShareResponse {
  token: string;
  url: string;
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

// ── Insights (LLM) ─────────────────────────────────────────────────────────

export function narrativeSSE(
  sessionId: string,
  bookType: string,
  uiLang: string,
  onToken: (text: string) => void,
  onDone: (fullText: string) => void,
  onError: (err: Error) => void
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/insights/narrative`, {
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
      if (!res.ok) throw new Error(`Narrative failed: ${res.status}`);
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
            const data: NarrativeToken = JSON.parse(line.slice(6));
            if (data.type === "token" && data.text) onToken(data.text);
            else if (data.type === "done" && data.text) onDone(data.text);
            else if (data.type === "error") onError(new Error(data.message || "LLM error"));
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

export function soulEnrichSSE(
  sessionId: string,
  onProgress: (data: SoulEnrichProgress) => void,
  onDone: (characters: SoulCharacter[]) => void,
  onError: (err: Error) => void
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/insights/soul-enrich`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`Soul enrich failed: ${res.status}`);
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
            const data: SoulEnrichProgress = JSON.parse(line.slice(6));
            if (data.type === "progress") onProgress(data);
            else if (data.type === "done" && data.characters) onDone(data.characters);
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

export async function fetchBookClubPack(
  sessionId: string,
  bookType: string,
  uiLang: string
): Promise<BookClubPack> {
  const res = await fetch(`${BASE}/insights/book-club-pack`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      book_type: bookType,
      ui_lang: uiLang,
    }),
  });
  if (!res.ok) throw new Error(`Book club pack failed: ${res.status}`);
  return res.json();
}

export async function fetchRecommendations(
  sessionId: string,
  bookType: string,
  uiLang: string
): Promise<RecommendationsResponse> {
  const res = await fetch(`${BASE}/insights/recommendations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      book_type: bookType,
      ui_lang: uiLang,
    }),
  });
  if (!res.ok) throw new Error(`Recommendations failed: ${res.status}`);
  return res.json();
}

// ── Library ─────────────────────────────────────────────────────────────────

export async function saveToLibrary(
  sessionId: string,
  tags: string[] = []
): Promise<{ saved: boolean; filename: string }> {
  const res = await fetch(`${BASE}/library/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, tags }),
  });
  if (!res.ok) throw new Error(`Save failed: ${res.status}`);
  return res.json();
}

export async function fetchLibrary(): Promise<LibraryListResponse> {
  const res = await fetch(`${BASE}/library`);
  if (!res.ok) throw new Error(`Library fetch failed: ${res.status}`);
  return res.json();
}

export async function deleteFromLibrary(filename: string): Promise<void> {
  const res = await fetch(`${BASE}/library/${filename}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
}

// ── Share ────────────────────────────────────────────────────────────────────

export async function createShareLink(
  sessionId: string
): Promise<ShareResponse> {
  const res = await fetch(`${BASE}/share/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) throw new Error(`Share failed: ${res.status}`);
  return res.json();
}

// ── Export ───────────────────────────────────────────────────────────────────

export function getExportJsonUrl(sessionId: string): string {
  return `${BASE}/export/${sessionId}/json`;
}

export function getExportMarkdownUrl(sessionId: string): string {
  return `${BASE}/export/${sessionId}/markdown`;
}
