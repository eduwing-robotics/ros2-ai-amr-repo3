import type { ComponentType } from "react";
import { OperatorShell } from "../features/operate/OperatorShell";
import { Records } from "../features/records/Records";
import { MapEditor } from "../features/mapEditor/MapEditor";
import { DevicesAdmin } from "../features/system/DevicesAdmin";
import { SystemAdmin } from "../features/system/SystemAdmin";
import { WarehouseAdmin } from "../features/warehouse/WarehouseAdmin";

// `${area}/${section}` → React 컴포넌트. 등록되지 않은 경로는 RouteView가 기본 관제로 보낸다.
export const VIEW_REGISTRY: Record<string, ComponentType> = {
  "operate/control": OperatorShell,
  "operate/inout": OperatorShell,
  "operate/tasks": OperatorShell,
  "operate/inventory": OperatorShell,
  "operate/events": OperatorShell,
  "admin/map": MapEditor,
  "admin/warehouse": WarehouseAdmin,
  "admin/devices": DevicesAdmin,
  "admin/system": SystemAdmin,
  "records/events": Records,
};

export const lookupView = (area?: string, section?: string): ComponentType | undefined => {
  if (area === "records") return VIEW_REGISTRY[`records/${section}`] ?? VIEW_REGISTRY["records/events"];
  return VIEW_REGISTRY[`${area}/${section}`];
};
