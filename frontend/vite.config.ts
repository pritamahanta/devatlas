import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In dev, /api/* is proxied to the FastAPI backend (no CORS setup needed).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  test: { environment: "node" },
});
