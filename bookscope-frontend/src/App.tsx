import { Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import UploadPage from "./pages/UploadPage";
import BookLayout from "./pages/BookLayout";
import OverviewPage from "./pages/OverviewPage";
import CharacterPage from "./pages/CharacterPage";
import ExplorePage from "./pages/ExplorePage";
import LibraryPage from "./pages/LibraryPage";
import LibraryDetailPage from "./pages/LibraryDetailPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5_000 },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/book/:sessionId" element={<BookLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="character/:name" element={<CharacterPage />} />
          <Route path="explore" element={<ExplorePage />} />
        </Route>
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/library/:filename" element={<LibraryDetailPage />} />
      </Routes>
    </QueryClientProvider>
  );
}
