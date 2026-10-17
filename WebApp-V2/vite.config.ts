import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.QWENSCI_API_URL || "http://127.0.0.1:8010";

export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    host: "0.0.0.0",
    proxy: {
      "/api/disciplines/resolve": {
        target: apiTarget,
        changeOrigin: false,
        timeout: 60_000,
        proxyTimeout: 55_000,
      },
      "/api": {
        target: apiTarget,
        changeOrigin: false,
        timeout: 5000,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
