/**
 * BYOK Settings — context + localStorage persistence.
 *
 * Users configure their own LLM provider, API key, model, and base URL.
 * Settings are stored in localStorage and synced to the backend on change.
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { createElement } from "react";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export type LLMProvider = "anthropic" | "openai_compatible";

export interface LLMSettings {
  provider: LLMProvider;
  api_key: string;
  base_url: string;
  model: string;
}

export interface SettingsContextValue {
  settings: LLMSettings;
  updateSettings: (patch: Partial<LLMSettings>) => void;
  isConfigured: boolean;
  syncing: boolean;
}

/* ------------------------------------------------------------------ */
/*  Provider presets                                                   */
/* ------------------------------------------------------------------ */

export interface ProviderPreset {
  id: string;
  label: string;
  provider: LLMProvider;
  base_url: string;
  models: string[];
  defaultModel: string;
  placeholder: string; // API key placeholder hint
}

export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: "anthropic",
    label: "Anthropic (Claude)",
    provider: "anthropic",
    base_url: "",
    models: [
      "claude-haiku-4-5",
      "claude-sonnet-4-5-20250514",
      "claude-opus-4-5-20250514",
    ],
    defaultModel: "claude-haiku-4-5",
    placeholder: "sk-ant-...",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    provider: "openai_compatible",
    base_url: "https://api.deepseek.com",
    models: ["deepseek-chat", "deepseek-reasoner"],
    defaultModel: "deepseek-chat",
    placeholder: "sk-...",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    provider: "openai_compatible",
    base_url: "https://openrouter.ai/api/v1",
    models: [
      "anthropic/claude-haiku-4-5",
      "anthropic/claude-sonnet-4-5",
      "deepseek/deepseek-chat-v3-0324",
      "google/gemini-2.5-flash-preview",
    ],
    defaultModel: "deepseek/deepseek-chat-v3-0324",
    placeholder: "sk-or-...",
  },
  {
    id: "siliconflow",
    label: "SiliconFlow (硅基流动)",
    provider: "openai_compatible",
    base_url: "https://api.siliconflow.cn/v1",
    models: [
      "deepseek-ai/DeepSeek-V3",
      "Qwen/Qwen2.5-72B-Instruct",
      "THUDM/glm-4-9b-chat",
    ],
    defaultModel: "deepseek-ai/DeepSeek-V3",
    placeholder: "sk-...",
  },
  {
    id: "ollama",
    label: "Ollama (本地)",
    provider: "openai_compatible",
    base_url: "http://localhost:11434/v1",
    models: ["llama3", "qwen2", "deepseek-v2"],
    defaultModel: "llama3",
    placeholder: "ollama（无需密钥，填任意值）",
  },
  {
    id: "custom",
    label: "自定义 (OpenAI 兼容)",
    provider: "openai_compatible",
    base_url: "",
    models: [],
    defaultModel: "",
    placeholder: "你的 API 密钥",
  },
];

/* ------------------------------------------------------------------ */
/*  localStorage                                                      */
/* ------------------------------------------------------------------ */

const STORAGE_KEY = "bookscope_llm_settings";

const DEFAULT_SETTINGS: LLMSettings = {
  provider: "anthropic",
  api_key: "",
  base_url: "",
  model: "",
};

function loadSettings(): LLMSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<LLMSettings>;
      return { ...DEFAULT_SETTINGS, ...parsed };
    }
  } catch {
    // corrupted
  }
  return { ...DEFAULT_SETTINGS };
}

function saveSettings(s: LLMSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

/* ------------------------------------------------------------------ */
/*  Backend sync                                                      */
/* ------------------------------------------------------------------ */

async function syncToBackend(s: LLMSettings): Promise<void> {
  try {
    await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(s),
    });
  } catch {
    // backend unreachable — settings still saved locally
  }
}

/* ------------------------------------------------------------------ */
/*  Context                                                           */
/* ------------------------------------------------------------------ */

const SettingsContext = createContext<SettingsContextValue>({
  settings: DEFAULT_SETTINGS,
  updateSettings: () => {},
  isConfigured: false,
  syncing: false,
});

export function useSettings(): SettingsContextValue {
  return useContext(SettingsContext);
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<LLMSettings>(loadSettings);
  const [syncing, setSyncing] = useState(false);

  // Sync to backend on mount
  useEffect(() => {
    if (settings.api_key) {
      syncToBackend(settings);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const updateSettings = useCallback((patch: Partial<LLMSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      saveSettings(next);
      // Async sync to backend
      setSyncing(true);
      syncToBackend(next).finally(() => setSyncing(false));
      return next;
    });
  }, []);

  const isConfigured = Boolean(settings.api_key);

  return createElement(
    SettingsContext.Provider,
    { value: { settings, updateSettings, isConfigured, syncing } },
    children,
  );
}
