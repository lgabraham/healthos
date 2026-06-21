import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// During dev, proxy /api, /webhooks, and /health to the FastAPI backend so the
// frontend can use same-origin relative URLs in both dev and prod.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // `@` -> ./src, the import alias shadcn/ui components expect.
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
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
