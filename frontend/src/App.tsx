import { BrowserRouter, Routes, Route } from "react-router-dom";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import EpisodeListPage from "./pages/EpisodeListPage";
import EditorPage from "./pages/EditorPage";
import SettingsPage from "./pages/SettingsPage";
import ValidationResultPage from "./pages/ValidationResultPage";
import MyPage from "./pages/MyPage";
import GraphPage from "./pages/GraphPage";

// Screen flow follows design doc 2.1:
// Login -> Dashboard -> {settings management / manuscript editor} -> run validation -> validation results
//                     -> My Page -> per-novel relationship graph · timeline
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<DashboardPage />} />
        <Route path="/novels/:novelId/settings" element={<SettingsPage />} />
        <Route path="/novels/:novelId/episodes" element={<EpisodeListPage />} />
        <Route path="/novels/:novelId/episodes/:episodeId" element={<EditorPage />} />
        <Route path="/novels/:novelId/episodes/:episodeId/result" element={<ValidationResultPage />} />
        <Route path="/mypage" element={<MyPage />} />
        <Route path="/novels/:novelId/graph" element={<GraphPage />} />
      </Routes>
    </BrowserRouter>
  );
}
