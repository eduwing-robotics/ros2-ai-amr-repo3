import { QueryClient } from "@tanstack/react-query";

// 서버 상태 캐시. 레거시의 "변경마다 전체 재조회" 패턴을 캐시 + 무효화로 대체한다.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});
