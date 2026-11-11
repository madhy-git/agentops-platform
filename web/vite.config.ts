/// <reference types="vitest/config" />
// Vite: dev server with hot reload, and the production build (a static bundle that nginx serves).
//
// LEARNING NOTE: the browser always calls the API at the SAME origin under /api (dev: this proxy; cluster: nginx,
// deploy/k8s-local/web.yaml). Same origin means no CORS configuration on the API, and the API never has to
// trust another website's requests.
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.AGENTOPS_API ?? "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: { environment: "node" },
});
