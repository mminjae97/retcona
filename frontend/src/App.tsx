import { useEffect } from "react";
import { Outlet, RouterProvider, createBrowserRouter, useLocation, useNavigate } from "react-router-dom";
import { onAuthExpired } from "./api/client";
import { getUserId } from "./utils/session";
import LoginPage from "./pages/LoginPage";
import GoogleCallbackPage from "./pages/GoogleCallbackPage";
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
        // The token is already dead (apiFetch cleared it before firing this);
        // this navigate() can still be declined by a page's own useBlocker
        // (e.g. the editor, guarding unsaved/unbacked-up text) — the data
        // router below is what makes that possible for a forced,
        // non-Link navigation like this one.
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

// A data router (createBrowserRouter, below) rather than plain <BrowserRouter>
// specifically so pages can use useBlocker (EditorPage, guarding unsaved,
// unbacked-up text): it needs one to also catch browser back/forward, which a
// Link-only or popstate-based guard can't — the URL has already changed by
// the time a popstate handler would see it.
function RootLayout() {
  return (
    <>
      <AuthExpiryRedirect />
      <Outlet />
    </>
  );
}

// Screen flow follows design doc 2.1:
// Login -> Dashboard -> {settings management / manuscript editor} -> run validation -> validation results
//                     -> My Page -> per-novel relationship graph · timeline
const router = createBrowserRouter([
  {
    element: <RootLayout />,
    // Relative (no leading "/"): they're joined onto the pathless layout
    // route above, which is also how nested route paths in this router are
    // meant to be written — an absolute child path here would only be valid
    // if it repeated the parent's own path, which this layout doesn't have.
    children: [
      { path: "login", element: <LoginPage /> },
      { path: "auth/google/callback", element: <GoogleCallbackPage /> },
      { index: true, element: <DashboardPage /> },
      { path: "novels/:novelId/settings", element: <SettingsPage /> },
      { path: "novels/:novelId/episodes", element: <EpisodeListPage /> },
      { path: "novels/:novelId/episodes/:episodeId", element: <EditorPage /> },
      { path: "novels/:novelId/episodes/:episodeId/result", element: <ValidationResultPage /> },
      { path: "mypage", element: <MyPage /> },
      { path: "novels/:novelId/graph", element: <GraphPage /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
