import type { ReactNode } from "react";

// 카드형 패널. title 을 주면 h2 헤더가 붙는다(.panel h2 스타일).
export function Panel({
  title,
  children,
  className = "",
}: {
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`panel ${className}`.trim()}>
      {title ? <h2>{title}</h2> : null}
      {children}
    </div>
  );
}
