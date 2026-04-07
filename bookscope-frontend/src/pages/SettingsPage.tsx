import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Eye, EyeOff, Zap, Check, X } from "lucide-react";
import clsx from "clsx";
import {
  useSettings,
  PROVIDER_PRESETS,
  type ProviderPreset,
} from "../lib/settings";

export default function SettingsPage() {
  const navigate = useNavigate();
  const { settings, updateSettings } = useSettings();

  // Detect which preset matches current settings
  const activePresetId = useMemo(() => {
    const match = PROVIDER_PRESETS.find(
      (p) =>
        p.provider === settings.provider &&
        (p.base_url === settings.base_url ||
          (!p.base_url && !settings.base_url)),
    );
    return match?.id ?? "custom";
  }, [settings.provider, settings.base_url]);

  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    msg: string;
  } | null>(null);

  const activePreset =
    PROVIDER_PRESETS.find((p) => p.id === activePresetId) ??
    PROVIDER_PRESETS[PROVIDER_PRESETS.length - 1];

  const handlePresetChange = (preset: ProviderPreset) => {
    updateSettings({
      provider: preset.provider,
      base_url: preset.base_url,
      model: preset.defaultModel,
    });
    setTestResult(null);
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch("/api/settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      const data = await res.json();
      setTestResult({
        ok: data.ok,
        msg: data.ok ? "连接成功" : data.error || "连接失败",
      });
    } catch {
      setTestResult({ ok: false, msg: "无法连接后端服务" });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="min-h-svh flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-[var(--bg)]/80 backdrop-blur-md border-b border-[var(--border)]">
        <div className="max-w-2xl mx-auto px-4 h-14 flex items-center gap-3">
          <button
            onClick={() => navigate(-1)}
            className="p-2 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all duration-200"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <h1
            className="text-xl text-[var(--accent)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            设置
          </h1>
        </div>
      </header>

      <main className="flex-1 max-w-2xl mx-auto w-full px-4 py-8 space-y-8">
        {/* Section: LLM Provider */}
        <section>
          <h2
            className="text-xl text-[var(--accent)] mb-1"
            style={{ fontFamily: "var(--font-display)" }}
          >
            语言模型
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-5">
            配置你自己的 LLM 供应商和 API 密钥。书鉴不提供内置
            API，所有调用使用你的账号。
          </p>

          {/* Provider preset cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-6">
            {PROVIDER_PRESETS.map((preset) => (
              <button
                key={preset.id}
                onClick={() => handlePresetChange(preset)}
                className={clsx(
                  "px-3 py-2.5 rounded-lg border text-left transition-all duration-200 text-sm",
                  activePresetId === preset.id
                    ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]"
                    : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] hover:border-[var(--text-secondary)]",
                )}
              >
                {preset.label}
              </button>
            ))}
          </div>

          {/* API Key */}
          <div className="space-y-4">
            <div>
              <label className="block text-xs text-[var(--text-secondary)] mb-1.5 uppercase tracking-wider">
                API 密钥
              </label>
              <div className="relative">
                <input
                  type={showKey ? "text" : "password"}
                  value={settings.api_key}
                  onChange={(e) => {
                    updateSettings({ api_key: e.target.value });
                    setTestResult(null);
                  }}
                  placeholder={activePreset.placeholder}
                  className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-lg px-4 py-2.5 text-sm text-[var(--text)] focus:outline-none focus:border-[var(--accent)] transition-all duration-200 pr-10 font-mono"
                />
                <button
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] hover:text-[var(--text)] transition-colors"
                >
                  {showKey ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
                  )}
                </button>
              </div>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">
                密钥仅保存在你的浏览器本地，不会上传到任何第三方服务
              </p>
            </div>

            {/* Base URL (for openai_compatible) */}
            {settings.provider === "openai_compatible" && (
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1.5 uppercase tracking-wider">
                  API 地址
                </label>
                <input
                  type="text"
                  value={settings.base_url}
                  onChange={(e) => {
                    updateSettings({ base_url: e.target.value });
                    setTestResult(null);
                  }}
                  placeholder="https://api.deepseek.com"
                  className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-lg px-4 py-2.5 text-sm text-[var(--text)] focus:outline-none focus:border-[var(--accent)] transition-all duration-200 font-mono"
                />
              </div>
            )}

            {/* Model */}
            <div>
              <label className="block text-xs text-[var(--text-secondary)] mb-1.5 uppercase tracking-wider">
                模型
              </label>
              {activePreset.models.length > 0 ? (
                <select
                  value={settings.model}
                  onChange={(e) => {
                    updateSettings({ model: e.target.value });
                    setTestResult(null);
                  }}
                  className="w-full appearance-none bg-[var(--bg)] border border-[var(--border)] rounded-lg px-4 py-2.5 text-sm text-[var(--text)] focus:outline-none focus:border-[var(--accent)] transition-all duration-200 cursor-pointer"
                >
                  {activePreset.models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={settings.model}
                  onChange={(e) => {
                    updateSettings({ model: e.target.value });
                    setTestResult(null);
                  }}
                  placeholder="模型 ID（如 gpt-4o-mini）"
                  className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-lg px-4 py-2.5 text-sm text-[var(--text)] focus:outline-none focus:border-[var(--accent)] transition-all duration-200 font-mono"
                />
              )}
            </div>

            {/* Test connection */}
            <div className="flex items-center gap-3">
              <button
                onClick={handleTest}
                disabled={!settings.api_key || testing}
                className={clsx(
                  "inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200",
                  settings.api_key && !testing
                    ? "bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white cursor-pointer"
                    : "bg-[var(--border)] text-[var(--text-secondary)] cursor-not-allowed",
                )}
              >
                {testing ? (
                  <>
                    <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    测试中...
                  </>
                ) : (
                  <>
                    <Zap className="w-3.5 h-3.5" />
                    测试连接
                  </>
                )}
              </button>

              {testResult && (
                <span
                  className={clsx(
                    "inline-flex items-center gap-1 text-sm",
                    testResult.ok ? "text-green-400" : "text-red-400",
                  )}
                >
                  {testResult.ok ? (
                    <Check className="w-3.5 h-3.5" />
                  ) : (
                    <X className="w-3.5 h-3.5" />
                  )}
                  {testResult.msg}
                </span>
              )}
            </div>
          </div>
        </section>

        <div className="ink-divider" />

        {/* Info section */}
        <section className="space-y-3">
          <h2
            className="text-xl text-[var(--accent)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            关于 BYOK
          </h2>
          <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-4 text-sm text-[var(--text-secondary)] space-y-2 leading-relaxed">
            <p>
              <strong className="text-[var(--text)]">BYOK</strong> (Bring Your
              Own Key) 意味着你使用自己的 API
              账号调用语言模型。书鉴不提供任何内置 API 或密钥。
            </p>
            <p>
              推荐选择：
              <strong className="text-[var(--text)]">DeepSeek</strong>{" "}
              性价比最高（中文优化，每百万 token ≈ ¥1），
              <strong className="text-[var(--text)]">Anthropic Claude</strong>{" "}
              质量最佳，
              <strong className="text-[var(--text)]">SiliconFlow</strong>{" "}
              国内直连无需翻墙。
            </p>
            <p>
              如果没有 API 密钥，情绪分析和文风分析仍可使用（本地模型），但知识图谱提取、角色深潜和 AI
              对话功能将不可用。
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}
