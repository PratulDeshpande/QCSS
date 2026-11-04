import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The bridge (qcss-dashboard) serves the API on :8765; in development Vite proxies /api to it, so the browser only
// ever talks to one origin and the CSRF/header guards behave exactly as in production.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8765", ws: true } },
  },
  build: { outDir: "dist", chunkSizeWarningLimit: 1500 },
  test: { environment: "jsdom", globals: false, include: ["src/**/*.test.{ts,tsx}"] },
});
