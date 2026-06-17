import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Upload,
  FileText,
  ChevronDown,
  Library,
  Settings,
  BookOpen,
  Loader2,
  Zap,
  Eye,
  EyeOff,
  Check,
  X,
} from "lucide-react";
import clsx from "clsx";
import { uploadFile, fetchActiveSessions } from "../lib/api";
import {
  useSettings,
  PROVIDER_PRESETS,
  type ProviderPreset,
} from "../lib/settings";

const BOOK_TYPES = [
  { value: "fiction", label: "小说" },
  { value: "non-fiction", label: "非虚构" },
  { value: "poetry", label: "诗歌" },
  { value: "drama", label: "戏剧" },
  { value: "academic", label: "学术" },
  { value: "biography", label: "传记" },
  { value: "children", label: "儿童文学" },
  { value: "philosophy", label: "哲学" },
] as const;

const ACCEPTED_EXTENSIONS = ".txt,.epub,.pdf";

const STATUS_LABELS: Record<string, string> = {
  idle: "等待提取",
  running: "提取中",
  done: "已完成",
  error: "出错",
};

export default function UploadPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { isConfigured, settings, updateSettings } = useSettings();

  const [bookType, setBookType] = useState<string>("fiction");
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  // Inline API setup state
  const [showApiSetup, setShowApiSetup] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    msg: string;
  } | null>(null);

  // Recent sessions
  const { data: sessionsData } = useQuery({
    queryKey: ["active-sessions"],
    queryFn: fetchActiveSessions,
    staleTime: 10_000,
  });

  const recentSessions = sessionsData?.sessions ?? [];

  const handleFile = useCallback((file: File) => {
    setSelectedFile(file);
    setError(null);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragActive(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleUpload = useCallback(async () => {
    if (!selectedFile) return;

    // If API not configured, show inline setup instead of navigating away
    if (!isConfigured) {
      setShowApiSetup(true);
      return;
    }

    setUploading(true);
    setError(null);

    try {
      const res = await uploadFile(selectedFile, bookType, "zh");
      navigate(`/book/${res.session_id}`, {
        state: { bookType, uiLang: "zh", title: res.title },
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Upload failed";
      setError(msg);
      setUploading(false);
    }
  }, [selectedFile, bookType, navigate, isConfigured]);

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

  const handlePresetChange = (preset: ProviderPreset) => {
    updateSettings({
      provider: preset.provider,
      base_url: preset.base_url,
      model: preset.defaultModel,
    });
    setTestResult(null);
  };

  const activePresetId =
    PROVIDER_PRESETS.find(
      (p) =>
        p.provider === settings.provider &&
        (p.base_url === settings.base_url || (!p.base_url && !settings.base_url)),
    )?.id ?? "custom";

  const activePreset =
    PROVIDER_PRESETS.find((p) => p.id === activePresetId) ??
    PROVIDER_PRESETS[PROVIDER_PRESETS.length - 1];

  return (
    <div className="min-h-svh flex flex-col items-center px-4 py-12">
      {/* Branding */}
      <div className="flex flex-col items-center mb-8 mt-8">
        <h1
          className="text-7xl sm:text-8xl mb-3 text-[var(--accent)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          书鉴
        </h1>
        <p
          className="text-xl sm:text-2xl mb-1 text-[var(--text)]"
          style={{ fontFamily: "var(--font-display)", letterSpacing: "0.2em" }}
        >
          解 构 每 一 本 书
        </p>
        <p
          className="text-xs tracking-[0.35em] text-[var(--text-secondary)] mb-2"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          BOOKSCOPE
        </p>
        <div className="ink-divider w-48 mb-4" />
        <p className="text-[var(--text-secondary)] text-center max-w-md text-sm leading-relaxed">
          上传文本，探索情感脉络、人物群像与叙事弧线
        </p>
      </div>

      {/* Recent sessions */}
      {recentSessions.length > 0 && (
        <div className="w-full max-w-lg mb-6 animate-[fadeSlideIn_0.4s_ease-out_both]">
          <h2
            className="text-lg text-[var(--accent)] mb-3"
            style={{ fontFamily: "var(--font-display)" }}
          >
            最近分析
          </h2>
          <div className="space-y-2">
            {recentSessions.slice(0, 5).map((s) => (
              <button
                key={s.session_id}
                onClick={() => navigate(`/book/${s.session_id}`)}
                className="w-full text-left bg-[var(--surface)] border border-[var(--border)] rounded-xl px-4 py-3 hover:border-[var(--accent)]/30 hover:bg-[var(--surface-hover)] transition-all group"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <BookOpen className="w-4 h-4 text-[var(--accent)] shrink-0" />
                    <span className="text-sm text-[var(--text)] truncate group-hover:text-[var(--accent)] transition-colors">
                      {s.title}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span
                      className={clsx(
                        "px-2 py-0.5 text-[10px] font-medium rounded-full",
                        s.extraction_status === "done"
                          ? "bg-[var(--trust)]/15 text-[var(--trust)]"
                          : s.extraction_status === "running"
                            ? "bg-[var(--accent)]/15 text-[var(--accent)]"
                            : s.extraction_status === "error"
                              ? "bg-red-500/15 text-red-400"
                              : "bg-[var(--surface-hover)] text-[var(--text-secondary)]",
                      )}
                    >
                      {STATUS_LABELS[s.extraction_status] ?? s.extraction_status}
                    </span>
                    <span className="text-[10px] text-[var(--text-secondary)]">
                      {s.total_words.toLocaleString()} 字
                    </span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Upload card */}
      <div className="w-full max-w-lg bg-[var(--surface)] border border-[var(--border)] rounded-xl p-6">
        {/* Drop zone */}
        <div
          onDrop={handleDrop}
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onClick={() => fileInputRef.current?.click()}
          className={clsx(
            "border-2 border-dashed rounded-lg p-10 flex flex-col items-center justify-center cursor-pointer transition-all",
            dragActive
              ? "border-[var(--accent)] bg-[var(--accent)]/5"
              : "border-[var(--border)] hover:border-[var(--text-secondary)]",
          )}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
            }}
            className="hidden"
          />

          {selectedFile ? (
            <>
              <FileText className="w-10 h-10 text-[var(--accent)] mb-3" />
              <p className="text-sm font-medium truncate max-w-full">
                {selectedFile.name}
              </p>
              <p className="text-xs text-[var(--text-secondary)] mt-1">
                {(selectedFile.size / 1024).toFixed(0)} KB — 点击更换文件
              </p>
            </>
          ) : (
            <>
              <Upload className="w-10 h-10 text-[var(--text-secondary)] mb-3" />
              <p className="text-sm text-[var(--text-secondary)]">
                拖放 <span className="text-[var(--text)]">.txt</span>、
                <span className="text-[var(--text)]">.epub</span> 或{" "}
                <span className="text-[var(--text)]">.pdf</span> 文件到此处
              </p>
              <p className="text-xs text-[var(--text-secondary)] mt-1">
                或点击选择文件
              </p>
            </>
          )}
        </div>

        {/* Book type selector */}
        <div className="mt-5">
          <label className="block text-xs text-[var(--text-secondary)] mb-2 uppercase tracking-wider">
            书籍类型
          </label>
          <div className="relative">
            <select
              value={bookType}
              onChange={(e) => setBookType(e.target.value)}
              className="w-full appearance-none bg-[var(--bg)] border border-[var(--border)] rounded-lg px-4 py-2.5 text-sm text-[var(--text)] focus:outline-none focus:border-[var(--accent)] transition-all cursor-pointer"
            >
              {BOOK_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-secondary)] pointer-events-none" />
          </div>
        </div>

        {/* Error */}
        {error && (
          <p className="mt-4 text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
            {error}
          </p>
        )}

        {/* Upload button */}
        <button
          onClick={handleUpload}
          disabled={!selectedFile || uploading}
          className={clsx(
            "mt-5 w-full py-2.5 rounded-lg text-sm font-medium transition-all",
            selectedFile && !uploading
              ? "bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white cursor-pointer"
              : "bg-[var(--border)] text-[var(--text-secondary)] cursor-not-allowed",
          )}
        >
          {uploading ? (
            <span className="flex items-center justify-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              上传中...
            </span>
          ) : !isConfigured && selectedFile ? (
            "配置 API 并开始分析"
          ) : (
            "开始分析"
          )}
        </button>
      </div>

      {/* Inline API setup — appears when user tries to upload without API key */}
      {showApiSetup && !isConfigured && (
        <div className="w-full max-w-lg mt-4 bg-[var(--surface)] border border-[var(--accent)]/30 rounded-xl p-5 animate-[fadeSlideIn_0.3s_ease-out_both]">
          <h3
            className="text-lg text-[var(--accent)] mb-1"
            style={{ fontFamily: "var(--font-display)" }}
          >
            快速配置 API
          </h3>
          <p className="text-xs text-[var(--text-secondary)] mb-4">
            知识图谱提取需要 LLM 支持。配置后即可开始分析。
          </p>

          {/* Provider presets */}
          <div className="grid grid-cols-3 gap-1.5 mb-4">
            {PROVIDER_PRESETS.slice(0, 5).map((preset) => (
              <button
                key={preset.id}
                onClick={() => handlePresetChange(preset)}
                className={clsx(
                  "px-2 py-2 rounded-lg border text-xs font-medium transition-all",
                  activePresetId === preset.id
                    ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]"
                    : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--text-secondary)]",
                )}
              >
                {preset.label}
              </button>
            ))}
          </div>

          {/* API Key */}
          <div className="relative mb-3">
            <input
              type={showKey ? "text" : "password"}
              value={settings.api_key}
              onChange={(e) => {
                updateSettings({ api_key: e.target.value });
                setTestResult(null);
              }}
              placeholder={activePreset.placeholder}
              className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-lg px-4 py-2.5 text-sm text-[var(--text)] focus:outline-none focus:border-[var(--accent)] transition-all pr-10 font-mono"
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

          <p className="text-[10px] text-[var(--text-secondary)] mb-3">
            密钥仅保存在浏览器本地，不会上传到第三方
          </p>

          {/* Test + Continue */}
          <div className="flex items-center gap-2">
            <button
              onClick={handleTest}
              disabled={!settings.api_key || testing}
              className={clsx(
                "inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all",
                settings.api_key && !testing
                  ? "bg-[var(--surface-hover)] text-[var(--text)] hover:bg-[var(--border)] cursor-pointer"
                  : "bg-[var(--border)] text-[var(--text-secondary)] cursor-not-allowed",
              )}
            >
              <Zap className="w-3 h-3" />
              测试
            </button>

            {testResult && (
              <span
                className={clsx(
                  "inline-flex items-center gap-1 text-xs",
                  testResult.ok ? "text-[var(--trust)]" : "text-red-400",
                )}
              >
                {testResult.ok ? (
                  <Check className="w-3 h-3" />
                ) : (
                  <X className="w-3 h-3" />
                )}
                {testResult.msg}
              </span>
            )}

            <div className="flex-1" />

            {isConfigured && (
              <button
                onClick={() => {
                  setShowApiSetup(false);
                  handleUpload();
                }}
                className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-xs font-medium hover:bg-[var(--accent-hover)] transition-all"
              >
                开始分析
              </button>
            )}
          </div>

          <button
            onClick={() => navigate("/settings")}
            className="mt-3 text-[10px] text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors"
          >
            更多选项请前往完整设置页面 →
          </button>
        </div>
      )}

      {/* Bottom links */}
      <div className="mt-6 flex items-center gap-4">
        <button
          onClick={() => navigate("/library")}
          className="inline-flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors"
        >
          <Library className="w-4 h-4" />
          书库
        </button>
        <span className="text-[var(--border)]">·</span>
        <button
          onClick={() => navigate("/settings")}
          className="inline-flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors"
        >
          <Settings className="w-4 h-4" />
          设置
        </button>
      </div>
    </div>
  );
}
