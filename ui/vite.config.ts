/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `pnpm dev` proxies the server's own paths to a running harness, so the UI
// talks to the real API on one origin, as it does when FastAPI serves the build.
const harness = process.env.HH_DEV_HARNESS_URL ?? "http://127.0.0.1:8080";
const proxied = ["/api", "/healthz", "/readyz", "/openapi.json"];

export default defineConfig({
  plugins: [
    // The router plugin must run before React's: it generates src/routeTree.gen.ts.
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    proxy: Object.fromEntries(proxied.map((path) => [path, { target: harness }])),
  },
  build: {
    // Hashed file names under /assets are what FastAPI caches as immutable.
    assetsDir: "assets",
    sourcemap: false,
    // One app shell, loaded once over the tailnet and then cached as immutable.
    chunkSizeWarningLimit: 1024,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
