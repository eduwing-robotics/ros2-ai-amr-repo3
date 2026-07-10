import { useEffect, useState } from "react";

/** pose 신선도 표시를 위해 1초마다 now를 갱신한다. */
export function usePoseClock(intervalMs = 1000) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return nowMs;
}
