import { Navigate, Outlet, RouterProvider, createBrowserRouter } from "react-router-dom";
import NovelListPage from "./pages/NovelListPage";
import EpisodeListPage from "./pages/EpisodeListPage";
import EditorPage from "./pages/EditorPage";
import SettingsPage from "./pages/SettingsPage";
import ValidationResultPage from "./pages/ValidationResultPage";
import GraphPage from "./pages/GraphPage";
import AppShell from "./components/AppShell";

// A data router (createBrowserRouter, below) rather than plain <BrowserRouter>
// specifically so pages can use useBlocker (EditorPage, guarding unsaved,
// unbacked-up text): it needs one to also catch browser back/forward, which a
// Link-only or popstate-based guard can't — the URL has already changed by
// the time a popstate handler would see it.
function RootLayout() {
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

// Screen flow follows design doc 2.1:
// Novel list (the app opens on it) -> {settings management / manuscript editor} -> run validation -> validation results
//                                  -> per-novel relationship graph · timeline
const router = createBrowserRouter([
  {
    element: <RootLayout />,
    // Relative (no leading "/"): they're joined onto the pathless layout
    // route above, which is also how nested route paths in this router are
    // meant to be written — an absolute child path here would only be valid
    // if it repeated the parent's own path, which this layout doesn't have.
    children: [
      { index: true, element: <NovelListPage /> },
      { path: "novels/:novelId/settings", element: <SettingsPage /> },
      { path: "novels/:novelId/episodes", element: <EpisodeListPage /> },
      { path: "novels/:novelId/episodes/:episodeId", element: <EditorPage /> },
      { path: "novels/:novelId/episodes/:episodeId/result", element: <ValidationResultPage /> },
      { path: "novels/:novelId/graph", element: <GraphPage /> },
      // Anything else, e.g. a bookmark of a removed screen (/login, /mypage,
      // /dashboard): the novel list.
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
