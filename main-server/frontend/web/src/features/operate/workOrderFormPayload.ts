import type { Operation, WorkOrderCreate, WorkOrderPreviewRequest } from "../../types";

export interface WorkOrderPayloadInput {
  operation: Operation;
  itemCode: string;
  quantity: number;
  floor?: number;
  autoStart?: boolean;
  inboundWaypointId?: string | null;
  outboundWaypointId?: string | null;
  robotId?: string;
  priority?: number;
  createdBy?: string;
  slotId?: string;
}

function waypointPayload(input: Pick<WorkOrderPayloadInput, "operation" | "inboundWaypointId" | "outboundWaypointId">) {
  return {
    inbound_waypoint_id: input.operation === "inbound" && input.inboundWaypointId ? input.inboundWaypointId : null,
    outbound_waypoint_id: input.operation === "outbound" && input.outboundWaypointId ? input.outboundWaypointId : null,
  };
}

export function buildWorkOrderPreviewBody(input: WorkOrderPayloadInput): WorkOrderPreviewRequest {
  return {
    operation: input.operation,
    item_code: input.itemCode,
    quantity: input.quantity,
    ...(input.floor ? { floor: input.floor } : {}),
    ...waypointPayload(input),
    ...(input.slotId ? { slot_id: input.slotId } : {}),
  };
}

export function buildWorkOrderCreateBody(input: WorkOrderPayloadInput): WorkOrderCreate {
  return {
    ...buildWorkOrderPreviewBody(input),
    auto_start: input.autoStart,
    ...(input.robotId ? { robot_id: input.robotId } : {}),
    ...(input.priority ? { priority: input.priority } : {}),
    ...(input.createdBy?.trim() ? { created_by: input.createdBy.trim() } : {}),
  };
}
