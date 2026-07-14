// 창고/입출고 도메인 타입. 백엔드 app/models/schemas.py 의
// Item / StorageSlot / InventoryRecord / WorkOrder 를 미러한다.
import type { JsonObject } from "./entities";

// --- 품목 ---
export interface Item {
  item_code: string;
  item_name: string;
  unit: string;
  created_at?: string | null;
  updated_at?: string | null;
}
export interface ItemUpsert {
  item_code: string;
  item_name: string;
  unit?: string;
}

// --- 보관 슬롯 — API alias for locations(type=storage) ---
export interface StorageSlot {
  slot_id: string;
  location_id?: string;
  waypoint_id: string;
  label: string;
  capacity: number;
  sort_order: number;
  approach_group: string;
  enabled: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}
export interface StorageSlotUpsert {
  slot_id: string;
  waypoint_id?: string;
  label: string;
  capacity?: number;
  sort_order?: number;
  approach_group?: string;
  enabled?: boolean;
}

// --- DBML-native location (internal / future API) ---
export interface StorageLocation {
  location_id: string;
  type: "storage";
  status: string;
  floor_capacity_policy?: number;
}

// --- 재고 (location_id + floor) — slot_id/item_code는 UI alias ---
export interface InventoryRecord {
  slot_id: string;
  item_code: string;
  quantity: number;
  floor?: number;
  item_name?: string | null;
  unit?: string | null;
  slot_label?: string | null;
  capacity?: number | null;
  updated_at?: string | null;
}
export interface InventoryUpsert {
  slot_id: string;
  item_code: string;
  quantity: number;
  floor?: number;
}

// --- DBML logs ---
export interface TaskLogRecord {
  id: number;
  task_id: number;
  task_type: string;
  result: string;
  summary?: string | null;
  finished_at?: string | null;
  error_reason?: string | null;
}

export interface ItemChangeLogRecord {
  id: number;
  task_id?: number | null;
  item_code: string;
  slot_id?: string | null;
  floor?: number | null;
  event_type: string;
  quantity_change: number;
  quantity_before?: number | null;
  quantity_after?: number | null;
  reason?: string | null;
  changed_at?: string | null;
}

// --- 입출고 work order ---
export type Operation = "inbound" | "outbound";

export interface WorkOrderRobotTask {
  order_id: number;
  task_id: number;
  slot_id?: string | null;
  floor?: number | null;
  quantity: number;
  priority?: number;
  status?: string | null;
  assigned_robot_id?: string | null;
  command_id?: string | null;
  slot_label?: string | null;
  source_zone?: string | null;
  target_zone?: string | null;
  selection_reason?: string | null;
  available_qty_at_plan?: number | null;
  business_completed?: boolean;
  return_status?: "RETURNING_HOME" | "PARKING" | "PARKED" | "PARK_FAILED" | null;
  parking_error?: JsonObject | null;
}

export interface WorkOrder {
  order_id: number;
  operation: Operation | string;
  item_code: string;
  quantity: number;
  status: string;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  tasks: WorkOrderRobotTask[];
  mission_results?: JsonObject[];
  start_failed?: Array<{ task_id: number; detail: string | unknown }>;
  business_completed?: boolean;
  return_status?: "RETURNING_HOME" | "PARKING" | "PARKED" | "PARK_FAILED" | null;
  parking_error?: JsonObject | null;
}

export interface WorkOrderCreate {
  operation: Operation;
  item_code: string;
  quantity: number;
  floor?: number;
  auto_start?: boolean;
  priority?: number;
  callback_base_url?: string | null;
  created_by?: string | null;
  slot_id?: string | null;
  slot_ids?: string[] | null;
  inbound_waypoint_id?: string | null;
  outbound_waypoint_id?: string | null;
  robot_id?: string | null;
}

export interface WorkOrderPreviewRequest {
  operation: Operation;
  item_code: string;
  quantity: number;
  floor?: number;
  slot_id?: string | null;
  slot_ids?: string[] | null;
  inbound_waypoint_id?: string | null;
  outbound_waypoint_id?: string | null;
}

export interface WorkOrderPlannedSlot {
  slot_id: string;
  floor?: number | null;
  slot_label?: string | null;
  map_id?: string | null;
  source_zone?: string | null;
  target_zone?: string | null;
  selection_reason?: string | null;
  available_qty_at_plan?: number | null;
}

export interface WorkOrderPlannedZone {
  waypoint_id: string;
  name: string;
  map_id: string;
}

export interface WorkOrderPreview {
  operation: Operation | string;
  item_code: string;
  quantity: number;
  slots: WorkOrderPlannedSlot[];
  zone?: WorkOrderPlannedZone | null;
}

export const MAX_WORK_ORDER_QUANTITY = 50;
export const WORK_ORDER_QUANTITY_WARN = 20;
