import { useState, useCallback, useRef } from "react";
import type { SSEEvent } from "../types";

interface SSEState<T> {
  events: T[];
  isRunning: boolean;
  error: string | null;
  start: (url: string, body?: unknown) => void;
  abort: () => void;
}

export function useSSE<T = SSEEvent>(): SSEState<T> {
  const [events, setEvents] = useState<T[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsRunning(false);
  }, []);

  const start = useCallback(
    (url: string, body?: unknown) => {
      abort();
      setEvents([]);
      setError(null);
      setIsRunning(true);

      const controller = new AbortController();
      abortRef.current = controller;

      (async () => {
        try {
          const res = await fetch(url, {
            method: body ? "POST" : "GET",
            headers: body ? { "Content-Type": "application/json" } : undefined,
            body: body ? JSON.stringify(body) : undefined,
            signal: controller.signal,
          });

          if (!res.ok) {
            const text = await res.text();
            setError(text || `HTTP ${res.status}`);
            setIsRunning(false);
            return;
          }

          const reader = res.body?.getReader();
          if (!reader) {
            setError("No response body");
            setIsRunning(false);
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
                const parsed = JSON.parse(jsonStr) as T;
                setEvents((prev) => [...prev, parsed]);
              } catch {
                // skip non-JSON lines
              }
            }
          }

          setIsRunning(false);
        } catch (err: unknown) {
          if (err instanceof DOMException && err.name === "AbortError") {
            setIsRunning(false);
            return;
          }
          const msg =
            err instanceof Error ? err.message : "SSE connection failed";
          setError(msg);
          setIsRunning(false);
        }
      })();
    },
    [abort],
  );

  return { events, isRunning, error, start, abort };
}
