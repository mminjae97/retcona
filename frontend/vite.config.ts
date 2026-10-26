import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The page may not be framed by another site: with no accounts, a framed app
// would be the author's own (clickjacking its delete buttons).
const headers = {
  "X-Frame-Options": "DENY",
  "Content-Security-Policy": "frame-ancestors 'none'",
};

export default defineConfig({
  plugins: [react()],
  // One fixed port, failing if it's taken rather than moving to the next one:
  // the API accepts browser requests from this origin only (ALLOWED_ORIGINS,
  // backend/api/main.py). `vite preview` serves on it too.
  server: {
    port: 5173,
    strictPort: true,
    headers,
    proxy: {
      // backend/api (FastAPI) mounts routes at the root (e.g. /novels), not under /api
      "/api": {
        target: "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  preview: {
    port: 5173,
    strictPort: true,
    headers,
  },
});
