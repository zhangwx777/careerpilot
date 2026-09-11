import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const runtime = globalThis as typeof globalThis & {
    process?: { env?: Record<string, string | undefined> };
  };
  const apiTarget = runtime.process?.env?.VITE_API_TARGET ?? env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": apiTarget,
        "/health": apiTarget,
      },
    },
  };
});
