import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import UploadPage from "./pages/UploadPage";
import AnalyzePage from "./pages/AnalyzePage";
import BookPage from "./pages/BookPage";
import LibraryPage from "./pages/LibraryPage";
import SharePage from "./pages/SharePage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5 * 60_000 },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/analyze/:sessionId" element={<AnalyzePage />} />
          <Route path="/book/:sessionId" element={<BookPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/share/:token" element={<SharePage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
