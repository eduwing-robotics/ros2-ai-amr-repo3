import type { ReactNode } from "react";

// 검색/필터/버튼을 가로로 배치하는 툴바(.toolbar).
export function Toolbar({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`toolbar ${className}`.trim()}>{children}</div>;
}
