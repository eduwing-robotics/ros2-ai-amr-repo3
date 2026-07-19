/**
 * 책임: 브라우저의 Main API JSON 요청과 오류 변환을 소유한다.
 * 비책임: 재시도 정책, 서버 상태, Movement 완료 판정.
 */
// 타입화 fetch 클라이언트. 레거시 app.js 의 api() 를 대체한다.
// 기본 base 는 동일 origin 의 /api/v1 (dev 는 vite 프록시가 :8088 로 전달).
export const API_BASE =
  (typeof window !== "undefined" &&
    (window as unknown as { APP_CONFIG?: { MAIN_API_BASE?: string } }).APP_CONFIG?.MAIN_API_BASE) ||
  "/api/v1";

/** API prefix를 제거한 서버 루트(같은 origin이면 ""). OpenAPI 문서·절대경로 호출용. */
export const apiRoot = (): string => API_BASE.replace(/\/api\/v1\/?$/, "");

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

const API_TIMEOUT_MS = 15_000;

/** HTTP 2xx JSON만 반환하며 15초 timeout과 status를 보존한 ApiError를 적용한다. */
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, API_TIMEOUT_MS);
  const callerSignal = options.signal;
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) abortFromCaller();
  else callerSignal?.addEventListener("abort", abortFromCaller, { once: true });

  try {
    const response = await fetch(API_BASE + path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      signal: controller.signal,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new ApiError(text || "HTTP " + response.status, response.status);
    }
    const body = await response.text();
    return (body ? JSON.parse(body) : null) as T;
  } catch (error) {
    if (timedOut) throw new ApiError("요청 시간이 초과되었습니다.", 408);
    throw error;
  } finally {
    window.clearTimeout(timeout);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }
}

export const apiGet = <T>(path: string) => api<T>(path);
export const apiSend = <T>(path: string, method: string, body?: unknown) =>
  api<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
