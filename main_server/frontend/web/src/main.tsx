import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./lib/queryClient";
import { App } from "./App";
import { FeedbackProvider } from "./components/FeedbackProvider";
// 디자인 토큰(모드 색상·간격 등) — base 보다 먼저 로드.
import "./styles/tokens.css";
// 기본 관제 UI 스타일.
import "./styles/base.css";
// 콕핏 등 관제 레이아웃 보완 스타일.
// 프리미티브/신규 컴포넌트 스타일(드로어·모드 탭 등).
import "./styles/components.css";
import "./styles/admin-shell.css";
import "./styles/operator-shell.css";
import "./styles/operations-enhancements.css";
import "./styles/motion.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <FeedbackProvider>
        <App />
      </FeedbackProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
