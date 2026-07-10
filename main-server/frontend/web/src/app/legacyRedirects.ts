// PHASE_10 이전 URL → 신규 IA 경로. App.tsx Navigate 에서 사용한다.

export const LEGACY_ROUTE_REDIRECTS: Record<string, string> = {
  "dashboard/overview": "/operate/control",
  "operate/queue": "/operate/tasks",
  "warehouse/manage": "/admin/warehouse",
  "tasks/editor": "/admin/map",
  "tasks/list": "/admin/map",
  "tasks/create": "/operate/inout",
  "moverec/commands": "/records/events",
  "taskrec/taskStatus": "/records/events",
  "taskrec/actions": "/records/events?tab=operator",
  "taskrec/events": "/records/events",
  "system/robots": "/admin/devices",
  "system/cameras": "/admin/devices",
  "system/commlogs": "/admin/devices",
  "system/dbtables": "/admin/system",
};

export const legacyRedirectTarget = (area?: string, section?: string): string | null => {
  if (!area || !section) return null;
  return LEGACY_ROUTE_REDIRECTS[`${area}/${section}`] ?? null;
};
