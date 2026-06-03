import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During dev, proxy /api, /webhooks, and /health to the FastAPI backend so the
// frontend can use same-origin relative URLs in both dev and prod.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/webhooks": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});
