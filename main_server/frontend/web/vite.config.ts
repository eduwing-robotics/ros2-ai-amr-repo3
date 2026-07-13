import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_* 는 레포 루트 .env 에서 읽는다(backend LMS_* 와 동일 파일).
const repoRoot = path.resolve(__dirname, "../..");
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://localhost:8088";

export default defineConfig({
  envDir: repoRoot,
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  // 빌드 산출물은 web/dist → FastAPI 정적 서빙. dev 는 /api·/health 프록시.
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiProxyTarget, changeOrigin: true },
      "/health": { target: apiProxyTarget, changeOrigin: true },
      // 개발자 API 콘솔이 스키마를 읽도록 OpenAPI 문서도 프록시.
      "/openapi.json": { target: apiProxyTarget, changeOrigin: true },
    },
  },
});
