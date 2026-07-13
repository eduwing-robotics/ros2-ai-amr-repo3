import type { ComponentType } from "react";
import { OperatorShell } from "../domains/operate/OperatorShell";
import { Records } from "../domains/records/Records";
import { MapEditor } from "../domains/map/MapEditor";
import { DevicesAdmin } from "../domains/system/DevicesAdmin";
import { SystemAdmin } from "../domains/system/SystemAdmin";
import { WarehouseAdmin } from "../domains/warehouse/WarehouseAdmin";

// `${area}/${section}` → React 컴포넌트. 등록되지 않은 경로는 RouteView가 기본 관제로 보낸다.
export const VIEW_REGISTRY: Record<string, ComponentType> = {
  "operate/control": OperatorShell,
  "operate/inout": OperatorShell,
  "operate/tasks": OperatorShell,
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
