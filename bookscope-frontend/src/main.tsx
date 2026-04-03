import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { UploadPage } from "./pages/UploadPage";
import { CharactersPage } from "./pages/CharactersPage";
import { ChatPage } from "./pages/ChatPage";
import { FontShowcase } from "./pages/FontShowcase";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/characters" element={<CharactersPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/fonts" element={<FontShowcase />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
