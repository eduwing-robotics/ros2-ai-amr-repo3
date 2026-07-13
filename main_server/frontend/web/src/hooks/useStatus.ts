import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { StatusSnapshot } from "../types";

// 관제 라이브 스냅샷. 레거시는 1.5s 폴링이었으나 부하를 줄여 2s 로 둔다.
// 같은 queryKey 를 쓰면 여러 컴포넌트(헤더/대시보드)가 캐시를 공유한다.
export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: () => apiGet<StatusSnapshot>("/status"),
    refetchInterval: 2000,
  });
}
