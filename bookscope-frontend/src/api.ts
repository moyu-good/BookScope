/** BookScope API client */

export interface UploadResponse {
  session_id: string;
  title: string;
  language: string;
  total_chunks: number;
}

export interface ChapterSummary {
  chunk_index: number;
  title: string;
  summary: string;
  key_events: string[];
  characters_mentioned: string[];
}

export interface CharacterProfile {
  name: string;
  aliases: string[];
  description: string;
  voice_style: string;
  motivations: string[];
  key_chapter_indices: number[];
  arc_summary: string;
}

export interface BookKnowledgeGraph {
  book_title: string;
  language: string;
  chapter_summaries: ChapterSummary[];
  characters: CharacterProfile[];
  overall_summary: string;
  themes: string[];
}

export async function uploadFile(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/upload", { method: "POST", body: form });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
}

export type SSEEvent =
  | { type: "progress"; current: number; total: number }
  | { type: "done"; graph: BookKnowledgeGraph }
  | { type: "message"; content: string };

export async function* extractSSE(
  sessionId: string,
  model = "claude-haiku-4-5",
): AsyncGenerator<SSEEvent> {
  const res = await fetch("/api/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, model }),
  });
  if (!res.ok || !res.body) {
    const detail = await res.json().then((d) => d.detail).catch(() => null);
    throw new Error(detail ?? `提取失败 (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        yield JSON.parse(line.slice(6));
      }
    }
  }
}

export async function* chatSSE(
  sessionId: string,
  message: string,
  model = "claude-haiku-4-5",
): AsyncGenerator<SSEEvent> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message, model }),
  });
  if (!res.ok || !res.body) {
    const detail = await res.json().then((d) => d.detail).catch(() => null);
    throw new Error(detail ?? `对话失败 (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        yield JSON.parse(line.slice(6));
      }
    }
  }
}
