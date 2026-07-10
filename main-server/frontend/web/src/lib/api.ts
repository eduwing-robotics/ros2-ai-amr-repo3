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

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new ApiError(text || `HTTP ${response.status}`, response.status);
  }
  // 204 등 빈 응답 방어
  const body = await response.text();
  return (body ? JSON.parse(body) : null) as T;
}

export const apiGet = <T>(path: string) => api<T>(path);
export const apiSend = <T>(path: string, method: string, body?: unknown) =>
  api<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
