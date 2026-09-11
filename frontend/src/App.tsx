import { BrowserRouter, Routes, Route } from "react-router-dom";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import EditorPage from "./pages/EditorPage";
import SettingsPage from "./pages/SettingsPage";
import ValidationResultPage from "./pages/ValidationResultPage";
import MyPage from "./pages/MyPage";
import GraphPage from "./pages/GraphPage";

// 화면 흐름은 설계서 2.1을 따른다:
// 로그인 -> 대시보드 -> {설정 카드 관리 / 원고 작성 에디터} -> 검증 실행 -> 검증 결과
//                    -> 마이페이지 -> 작품별 관계도·타임라인
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<DashboardPage />} />
        <Route path="/novels/:novelId/settings" element={<SettingsPage />} />
        <Route path="/novels/:novelId/episodes/:episodeId" element={<EditorPage />} />
        <Route path="/novels/:novelId/episodes/:episodeId/result" element={<ValidationResultPage />} />
        <Route path="/mypage" element={<MyPage />} />
        <Route path="/novels/:novelId/graph" element={<GraphPage />} />
      </Routes>
    </BrowserRouter>
  );
}
