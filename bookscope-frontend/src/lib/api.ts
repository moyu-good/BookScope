import type {
  UploadResponse,
  SessionStatus,
  BookOverview,
  CharacterProfile,
  SSEEvent,
} from "./types";

const BASE = "/api";

/* ------------------------------------------------------------------ */
/*  SSE helper — returns a controller with start / abort / onEvent    */
/* ------------------------------------------------------------------ */

interface SSEController {
  start: () => void;
  abort: () => void;
  onEvent: (handler: (event: SSEEvent) => void) => void;
  onError: (handler: (err: string) => void) => void;
  onDone: (handler: () => void) => void;
}

function createSSE(
  url: string,
  body?: unknown,
  method: "GET" | "POST" = "POST",
): SSEController {
  let abortController: AbortController | null = null;
  let eventHandler: ((event: SSEEvent) => void) | null = null;
  let errorHandler: ((err: string) => void) | null = null;
  let doneHandler: (() => void) | null = null;

  async function start() {
    abortController = new AbortController();
    try {
      const res = await fetch(url, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: abortController.signal,
      });

      if (!res.ok) {
        const text = await res.text();
        errorHandler?.(text || `HTTP ${res.status}`);
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        errorHandler?.("No response body");
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data:")) continue;

          const jsonStr = trimmed.slice(5).trim();
          if (jsonStr === "[DONE]") continue;

          try {
            const parsed = JSON.parse(jsonStr) as SSEEvent;
            eventHandler?.(parsed);
          } catch {
            // skip non-JSON SSE lines
          }
        }
      }

      doneHandler?.();
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      const msg = err instanceof Error ? err.message : "SSE connection failed";
      errorHandler?.(msg);
    }
  }

  function abort() {
    abortController?.abort();
  }

  return {
    start,
    abort,
    onEvent: (h) => {
      eventHandler = h;
    },
    onError: (h) => {
      errorHandler = h;
    },
    onDone: (h) => {
      doneHandler = h;
    },
  };
}

/* ------------------------------------------------------------------ */
/*  REST endpoints                                                    */
/* ------------------------------------------------------------------ */

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function uploadFile(
  file: File,
  bookType: string,
  uiLang: string,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("book_type", bookType);
  form.append("ui_lang", uiLang);
  return jsonFetch<UploadResponse>(`${BASE}/upload`, {
    method: "POST",
    body: form,
  });
}

export function startExtraction(
  sessionId: string,
  model?: string,
): SSEController {
  const body = model ? { model } : undefined;
  return createSSE(`${BASE}/extract/${sessionId}`, body);
}

export function fetchOverview(sessionId: string): Promise<BookOverview> {
  return jsonFetch<BookOverview>(`${BASE}/book/${sessionId}/overview`);
}

export function fetchSessionStatus(
  sessionId: string,
): Promise<SessionStatus> {
  return jsonFetch<SessionStatus>(`${BASE}/session/${sessionId}/status`);
}

export function fetchCharacter(
  sessionId: string,
  name: string,
): Promise<CharacterProfile> {
  return jsonFetch<CharacterProfile>(
    `${BASE}/book/${sessionId}/character/${encodeURIComponent(name)}`,
  );
}

export function enrichCharacter(
  sessionId: string,
  name: string,
): SSEController {
  return createSSE(
    `${BASE}/book/${sessionId}/character/${encodeURIComponent(name)}/enrich`,
  );
}

export function characterChat(
  sessionId: string,
  name: string,
  message: string,
  uiLang: string,
): SSEController {
  return createSSE(
    `${BASE}/book/${sessionId}/character/${encodeURIComponent(name)}/chat`,
    { message, ui_lang: uiLang },
  );
}

export function chatStream(
  sessionId: string,
  message: string,
  uiLang: string,
): SSEController {
  return createSSE(`${BASE}/chat/stream`, {
    session_id: sessionId,
    message,
    ui_lang: uiLang,
  });
}

export function searchChunks(
  sessionId: string,
  query: string,
): Promise<unknown> {
  return jsonFetch(`${BASE}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, query }),
  });
}

export function fetchLibrary(): Promise<unknown[]> {
  return jsonFetch<unknown[]>(`${BASE}/library`);
}

export function deleteLibraryItem(filename: string): Promise<void> {
  return jsonFetch<void>(`${BASE}/library/${encodeURIComponent(filename)}`, {
    method: "DELETE",
  });
}

export function saveToLibrary(
  sessionId: string,
  tags?: string[],
): Promise<unknown> {
  return jsonFetch(`${BASE}/library/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, tags }),
  });
}

export function fetchLibraryAnalysis(
  filename: string,
): Promise<BookOverview> {
  return jsonFetch<BookOverview>(
    `${BASE}/library/${encodeURIComponent(filename)}/analysis`,
  );
}
