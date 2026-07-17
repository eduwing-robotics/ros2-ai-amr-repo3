import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_* 는 레포 루트 .env 에서 읽는다(backend LMS_* 와 동일 파일).
const repoRoot = path.resolve(__dirname, "../..");
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://localhost:8088";
const allowedHosts = (process.env.VITE_ALLOWED_HOSTS || "")
  .split(",")
  .map((host) => host.trim())
  .filter(Boolean);

export default defineConfig({
  envDir: repoRoot,
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  // 빌드 산출물은 web/dist → FastAPI 정적 서빙. dev 는 브라우저 Host를
  // 유지해 백엔드의 동일-origin 쓰기 검사를 통과시킨다.
  server: {
    port: 5173,
    allowedHosts,
    proxy: {
      "/api": { target: apiProxyTarget, changeOrigin: false },
      "/health": { target: apiProxyTarget, changeOrigin: false },
      // 개발자 API 콘솔(PHASE_42)이 스키마를 읽도록 OpenAPI 문서도 프록시.
      "/openapi.json": { target: apiProxyTarget, changeOrigin: false },
    },
  },
});
