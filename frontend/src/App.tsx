import { useEffect } from "react";
import { BrowserRouter, Routes, Route, useLocation, useNavigate } from "react-router-dom";
import { onAuthExpired } from "./api/client";
import { getUserId } from "./utils/session";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import EpisodeListPage from "./pages/EpisodeListPage";
import EditorPage from "./pages/EditorPage";
import SettingsPage from "./pages/SettingsPage";
import ValidationResultPage from "./pages/ValidationResultPage";
import MyPage from "./pages/MyPage";
import GraphPage from "./pages/GraphPage";

// Sends the user to the login screen when the API reports the session is over,
// remembering where they were headed so LoginPage can bring them back afterwards.
function AuthExpiryRedirect() {
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(
    () =>
      onAuthExpired(({ sessionEnded }) => {
        if (location.pathname === "/login") return;
        navigate("/login", {
          replace: true,
          // Who was signed in, when a session did end: only that account is
          // taken back to this page. A visitor who never signed in has no one to protect.
          state: { returnTo: location.pathname + location.search, sessionEnded, userId: sessionEnded ? getUserId() : null },
        });
      }),
    [navigate, location.pathname, location.search],
  );
  return null;
}

// Screen flow follows design doc 2.1:
// Login -> Dashboard -> {settings management / manuscript editor} -> run validation -> validation results
//                     -> My Page -> per-novel relationship graph · timeline
export default function App() {
  return (
    <BrowserRouter>
      <AuthExpiryRedirect />
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
