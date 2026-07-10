import { useEffect, useState } from "react";

// 헤더 상시 시각(24h). 관제 상태바의 기본 요소.
export function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return <span className="mono">{now.toLocaleTimeString("ko-KR", { hour12: false })}</span>;
}
