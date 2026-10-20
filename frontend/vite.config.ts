import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server proxies the API to a locally running backend (docker compose up). The production build is served by Caddy.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8087", changeOrigin: false },
      "/demo/api": { target: "http://127.0.0.1:8087", changeOrigin: false },
      "/health": { target: "http://127.0.0.1:8087", changeOrigin: false },
    },
  },
  build: { sourcemap: false, chunkSizeWarningLimit: 1200 },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
} as never);
