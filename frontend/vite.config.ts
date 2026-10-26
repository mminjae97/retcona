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
  // `vite preview` uses these settings (headers, cors, proxy) too.
  server: {
    headers,
    // No CORS at all: the proxy below would otherwise carry another site's
    // request to the API once a preflight let it add X-Retcona-Client
    // (backend/api/main.py). The app's own page is same-origin and needs none.
    cors: false,
    proxy: {
      // backend/api (FastAPI) mounts routes at the root (e.g. /novels), not under /api
      "/api": {
        target: "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
