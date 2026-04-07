import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, FileText, ChevronDown, Library } from "lucide-react";
import clsx from "clsx";
import { uploadFile } from "../lib/api";

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

export default function UploadPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [bookType, setBookType] = useState<string>("fiction");
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

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

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragActive(false);
  }, []);

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleUpload = useCallback(async () => {
    if (!selectedFile) return;
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
  }, [selectedFile, bookType, navigate]);

  return (
    <div className="min-h-svh flex flex-col items-center justify-center px-4 py-12">
      {/* Branding — 中文为主，英文从属 */}
      <h1 className="text-7xl sm:text-8xl mb-3 text-[var(--accent)]" style={{ fontFamily: "var(--font-display)" }}>
        书鉴
      </h1>
      <p className="text-xl sm:text-2xl mb-1 text-[var(--text)]" style={{ fontFamily: "var(--font-display)", letterSpacing: "0.2em" }}>
        解 构 每 一 本 书
      </p>
      <p className="text-xs tracking-[0.35em] text-[var(--text-secondary)] mb-2" style={{ fontFamily: "var(--font-mono)" }}>
        BOOKSCOPE
      </p>
      <div className="ink-divider w-48 mb-6" />
      <p className="text-[var(--text-secondary)] mb-10 text-center max-w-md text-sm leading-relaxed">
        上传文本，探索情感脉络、人物群像与叙事弧线
      </p>

      {/* Upload card */}
      <div className="w-full max-w-lg bg-[var(--surface)] border border-[var(--border)] rounded-xl p-6">
        {/* Drop zone */}
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => fileInputRef.current?.click()}
          className={clsx(
            "border-2 border-dashed rounded-lg p-10 flex flex-col items-center justify-center cursor-pointer transition-all duration-200",
            dragActive
              ? "border-[var(--accent)] bg-[var(--accent)]/5"
              : "border-[var(--border)] hover:border-[var(--text-secondary)]",
          )}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS}
            onChange={handleInputChange}
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
              className="w-full appearance-none bg-[var(--bg)] border border-[var(--border)] rounded-lg px-4 py-2.5 text-sm text-[var(--text)] focus:outline-none focus:border-[var(--accent)] transition-all duration-200 cursor-pointer"
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
            "mt-5 w-full py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
            selectedFile && !uploading
              ? "bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white cursor-pointer"
              : "bg-[var(--border)] text-[var(--text-secondary)] cursor-not-allowed",
          )}
        >
          {uploading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              上传中...
            </span>
          ) : (
            "开始分析"
          )}
        </button>
      </div>

      {/* Library entry */}
      <button
        onClick={() => navigate("/library")}
        className="mt-6 inline-flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors duration-200"
      >
        <Library className="w-4 h-4" />
        查看书库
      </button>
    </div>
  );
}
