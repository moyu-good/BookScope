/* Shared TypeScript interfaces for BookScope v5 */

export interface UploadResponse {
  session_id: string;
  title: string;
  language: string;
  total_chunks: number;
  total_words: number;
}

export interface SessionStatus {
  extraction_status: "idle" | "running" | "done" | "error";
  has_knowledge_graph: boolean;
  has_analysis: boolean;
  has_soul_enrichment: Record<string, boolean>;
}

export interface ChapterSummary {
  chunk_index: number;
  title: string;
  summary: string;
  key_events: string[];
  characters_mentioned: string[];
}

export interface ChapterAnalysis {
  chapter_index: number;
  title: string;
  chunk_indices: number[];
  analysis: string;
  key_points: string[];
  characters_involved: string[];
  significance: string;
}

export interface ThemeAnalysis {
  theme: string;
  description: string;
}

export interface CharacterBrief {
  name: string;
  description: string;
  aliases: string[];
  arc_summary: string;
  has_soul: boolean;
}

export interface ReaderVerdict {
  sentence: string;
  for_you: string;
  not_for_you: string;
  confidence: number;
}

export interface Readability {
  score: number;
  label: string;
  confidence: number;
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

export interface NarrativePoint {
  chapter_index: number;
  title: string;
  intensity: number;
  event_label: string;
  point_type: string;
}

export interface BookOverview {
  title: string;
  language: string;
  total_chunks: number;
  total_words: number;
  book_type: string;
  extraction_status: string;
  // KG fields (optional, appear when KG ready)
  overall_summary?: string;
  book_outline?: string;
  themes?: string[];
  theme_analyses?: ThemeAnalysis[];
  chapter_summaries?: ChapterSummary[];
  chapter_analyses?: ChapterAnalysis[];
  characters_brief?: CharacterBrief[];
  narrative_rhythm?: NarrativePoint[];
  // Analysis fields (optional, appear when analysis ready)
  arc_pattern?: string;
  dominant_emotion?: string;
  valence_series?: number[];
  readability?: Readability;
  reader_verdict?: ReaderVerdict;
  emotion_scores?: EmotionScore[];
}

export interface CharacterProfile {
  name: string;
  aliases: string[];
  description: string;
  voice_style: string;
  motivations: string[];
  arc_summary: string;
  key_chapter_indices: number[];
  has_soul: boolean;
  personality_type: string;
  values?: string[];
  key_quotes?: string[];
  emotional_stages?: { stage: string; emotion: string; event: string }[];
}

export interface SSEEvent {
  type: string;
  [key: string]: unknown;
}
