import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, BookOpen, ChevronDown } from "lucide-react";
import { uploadFile } from "../lib/api";

const BOOK_TYPES = [
  { value: "fiction", label: "Fiction" },
  { value: "non-fiction", label: "Non-Fiction" },
  { value: "poetry", label: "Poetry" },
  { value: "drama", label: "Drama" },
  { value: "academic", label: "Academic" },
  { value: "biography", label: "Biography" },
  { value: "children", label: "Children's" },
  { value: "philosophy", label: "Philosophy" },
] as const;

export default function UploadPage() {
  const navigate = useNavigate();
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bookType, setBookType] = useState("fiction");

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      setUploading(true);
      try {
        const res = await uploadFile(file);
        navigate(`/analyze/${res.session_id}`, {
          state: {
            title: res.title,
            language: res.language,
            total_chunks: res.total_chunks,
            total_words: res.total_words,
            bookType,
          },
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setUploading(false);
      }
    },
    [navigate, bookType],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const onFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-lg">
        {/* Logo & Title */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-3 mb-4">
            <BookOpen className="w-10 h-10 text-[var(--bs-accent)]" strokeWidth={1.5} />
            <h1 className="text-4xl font-light tracking-tight">BookScope</h1>
          </div>
          <p className="text-[var(--bs-text-muted)] text-lg">
            Upload a book. Understand what it says, how it feels, and who lives in it.
          </p>
        </div>

        {/* Book Type Selector */}
        <div className="mb-6 flex justify-center">
          <div className="relative">
            <select
              value={bookType}
              onChange={(e) => setBookType(e.target.value)}
              className="appearance-none bg-[var(--bs-surface)] border border-[var(--bs-border)]
                         rounded-xl px-4 py-2.5 pr-10 text-sm text-[var(--bs-text)]
                         focus:border-[var(--bs-accent)] outline-none transition-colors cursor-pointer"
            >
              {BOOK_TYPES.map(({ value, label }) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--bs-text-muted)] pointer-events-none" />
          </div>
        </div>

        {/* Drop Zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`
            relative border-2 border-dashed rounded-2xl p-12 text-center
            transition-all duration-200 cursor-pointer
            ${dragging
              ? "border-[var(--bs-accent)] bg-[var(--bs-accent)]/5 scale-[1.02]"
              : "border-[var(--bs-border)] hover:border-[var(--bs-accent)]/50 hover:bg-white/50"
            }
            ${uploading ? "pointer-events-none opacity-60" : ""}
          `}
        >
          <input
            type="file"
            accept=".txt,.epub,.pdf"
            onChange={onFileInput}
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            disabled={uploading}
          />
          <Upload
            className={`mx-auto mb-4 w-8 h-8 ${
              dragging ? "text-[var(--bs-accent)]" : "text-[var(--bs-text-muted)]"
            }`}
            strokeWidth={1.5}
          />
          {uploading ? (
            <p className="text-[var(--bs-text-muted)]">Uploading...</p>
          ) : (
            <>
              <p className="text-[var(--bs-text)] font-medium mb-1">
                Drop your book here
              </p>
              <p className="text-sm text-[var(--bs-text-muted)]">
                .txt, .epub, or .pdf
              </p>
            </>
          )}
        </div>

        {error && (
          <p className="mt-4 text-center text-red-600 text-sm">{error}</p>
        )}
      </div>
    </div>
  );
}
