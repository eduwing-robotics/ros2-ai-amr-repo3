/** API 콘솔 OpenAPI 파싱·분류 (PHASE_42/49). */

import { exampleFor, type OpenApiDoc, type OpenApiSchema } from "./openApiForm";

export type ApiMethod = "get" | "post" | "put" | "patch" | "delete";
export const API_METHODS: ApiMethod[] = ["get", "post", "put", "patch", "delete"];

export type ApiChannel = "callback" | "proxy";
export type ApiCategory = "all" | "robot" | "database" | "map" | "work" | "vision" | "system" | "warehouse" | "logs" | "other";

export const CATEGORY_LABEL: Record<ApiCategory, string> = {
  all: "전체",
  robot: "로봇 제어",
  database: "DB",
  map: "맵/구역",
  work: "작업",
  vision: "비전/카메라",
  system: "시스템",
  warehouse: "재고",
  logs: "로그",
  other: "기타",
};

export const CATEGORY_ORDER: Exclude<ApiCategory, "all">[] = [
  "robot", "work", "map", "vision", "warehouse", "database", "logs", "system", "other",
];

export const CHANNEL_LABEL: Record<ApiChannel, string> = {
  callback: "콜백 — 외부에서 Main으로 보고(수신)",
  proxy: "프록시 — 이동/비전/카메라 서버로 전달(송신)",
};

export const DANGER_RE = /estop|missions|robot-commands|movement|teleop/i;

const CALLBACK_KEYS = new Set([
  "POST /api/v1/movement/command-events",
  "POST /api/v1/movement/results",
  "POST /api/v1/movement/robots/{robot_name}/status",
  "POST /api/v1/robot-poses/report",
  "POST /api/v1/robots/{robot_id}/pose",
  "POST /api/v1/movement/missions/{command_id}/pose",
]);

const PROXY_KEYS = new Set([
  "GET /api/v1/aruco/latest",
  "GET /api/v1/robots/{robot_id}/nav-state",
  "POST /api/v1/robots/{robot_id}/initial-pose",
  "POST /api/v1/robot/estop",
  "POST /api/v1/robot/clear_estop",
  "POST /api/v1/comm/probe/movement",
  "POST /api/v1/comm/probe/camera",
  "POST /api/v1/teleop",
  "POST /api/v1/robot-commands",
]);

export interface ApiParam {
  name: string;
  in: string;
  required?: boolean;
  schema?: OpenApiSchema;
  description?: string;
}

export interface ApiOp {
  id: string;
  method: ApiMethod;
  path: string;
  summary: string;
  description: string;
  tag: string;
  category: Exclude<ApiCategory, "all">;
  params: ApiParam[];
  bodySchema?: OpenApiSchema;
  channel: ApiChannel | null;
}

function classifyChannel(method: ApiMethod, path: string): ApiChannel | null {
  const key = `${method.toUpperCase()} ${path}`;
  if (CALLBACK_KEYS.has(key)) return "callback";
  if (PROXY_KEYS.has(key)) return "proxy";
  if (path.startsWith("/api/v1/vision/")) return "proxy";
  return null;
}

function classifyCategory(path: string, tag: string): Exclude<ApiCategory, "all"> {
  const s = `${path} ${tag}`.toLowerCase();
  if (/robot-commands|teleop|estop|robots|movement|missions|aruco|initial-pose|localization|nav-state/.test(s)) return "robot";
  if (/work-orders|tasks/.test(s)) return "work";
  if (/maps|map-assets|waypoints/.test(s)) return "map";
  if (/vision|camera/.test(s)) return "vision";
  if (/inventory|items|storage-slots/.test(s)) return "warehouse";
  if (/db\/tables|db_admin|database/.test(s)) return "database";
  if (/comm\/logs|events|records/.test(s)) return "logs";
  if (/status|system|health|comm\/probe/.test(s)) return "system";
  return "other";
}

export function parseApiOps(doc: OpenApiDoc): ApiOp[] {
  const ops: ApiOp[] = [];
  for (const [path, item] of Object.entries(doc.paths || {})) {
    for (const m of API_METHODS) {
      const o = (item as Record<string, unknown>)[m] as Record<string, unknown> | undefined;
      if (!o) continue;
      const tag = (Array.isArray(o.tags) && o.tags[0]) ? String(o.tags[0]) : "기타";
      ops.push({
        id: `${m} ${path}`,
        method: m,
        path,
        summary: String(o.summary || ""),
        description: String(o.description || ""),
        tag,
        category: classifyCategory(path, tag),
        params: ((o.parameters as unknown[]) || []).map((p) => {
          const row = p as Record<string, unknown>;
          return {
            name: String(row.name),
            in: String(row.in),
            required: Boolean(row.required),
            schema: row.schema as OpenApiSchema | undefined,
            description: row.description ? String(row.description) : undefined,
          };
        }),
        bodySchema: (o.requestBody as { content?: { "application/json"?: { schema?: OpenApiSchema } } })?.content?.["application/json"]?.schema,
        channel: classifyChannel(m, path),
      });
    }
  }
  return ops.sort((a, b) => a.tag.localeCompare(b.tag) || a.path.localeCompare(b.path) || a.method.localeCompare(b.method));
}

export { exampleFor };
