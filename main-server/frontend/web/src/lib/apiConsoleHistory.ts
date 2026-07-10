/** API 콘솔 히스토리·스니펫 (PHASE_49-E). */

export interface ApiHistoryEntry {
  id: string;
  method: string;
  path: string;
  url: string;
  status: number;
  ms: number;
  at: string;
  body?: string;
}

const HISTORY_KEY = "lms.apiConsole.history";
const AUTO_GET_KEY = "lms.apiConsole.autoGet";
const MAX_HISTORY = 30;

export function loadAutoGetExecute(): boolean {
  try {
    return localStorage.getItem(AUTO_GET_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveAutoGetExecute(on: boolean): void {
  try {
    localStorage.setItem(AUTO_GET_KEY, on ? "1" : "0");
  } catch { /* ignore */ }
}

export function loadApiHistory(): ApiHistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ApiHistoryEntry[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function pushApiHistory(entry: Omit<ApiHistoryEntry, "id">): ApiHistoryEntry[] {
  const next: ApiHistoryEntry[] = [
    { ...entry, id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}` },
    ...loadApiHistory(),
  ].slice(0, MAX_HISTORY);
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  } catch { /* ignore */ }
  return next;
}

export function recentCommandIds(history: ApiHistoryEntry[]): string[] {
  const ids: string[] = [];
  for (const h of history) {
    if (!h.body) continue;
    try {
      const parsed = JSON.parse(h.body) as { command_id?: string };
      if (parsed.command_id && !ids.includes(parsed.command_id)) ids.push(parsed.command_id);
    } catch { /* skip */ }
    const m = h.url.match(/robot-commands\/([^/?]+)/);
    if (m?.[1] && !ids.includes(m[1])) ids.push(m[1]);
  }
  return ids.slice(0, 12);
}

export function toCurl(method: string, url: string, body?: string): string {
  const lines = [`curl -X ${method.toUpperCase()} '${url}'`];
  if (body?.trim()) {
    lines.push("  -H 'Content-Type: application/json'");
    lines.push(`  -d '${body.replace(/'/g, "'\\''")}'`);
  }
  return lines.join(" \\\n");
}

export function toFetchSnippet(method: string, url: string, body?: string): string {
  const init: string[] = [`method: '${method.toUpperCase()}'`];
  if (body?.trim()) {
    init.push("headers: { 'Content-Type': 'application/json' }");
    init.push(`body: JSON.stringify(${body})`);
  }
  return `fetch('${url}', {\n  ${init.join(",\n  ")}\n}).then(r => r.text()).then(console.log)`;
}
