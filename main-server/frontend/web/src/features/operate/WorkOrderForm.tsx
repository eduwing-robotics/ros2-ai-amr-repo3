import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Panel } from "../../components/Panel";
import { Field } from "../../components/Field";
import { Button } from "../../components/Button";
import { ApiError } from "../../lib/api";
import { pairsFromWaypoints } from "../../lib/dockPairs";
import { operationLabel, zoneTypeForOperation } from "../../lib/workOrderLabels";
import {
  emptySlotCount,
  parseWorkOrderApiDetail,
  slotCandidatesForOperation,
  stockOnHandForItem,
  WORK_ORDER_ERROR_HINTS,
} from "../../lib/workOrderPlanning";
import { useItems, useInventory, useStorageSlots } from "../../hooks/useWarehouseData";
import { useAllWaypoints } from "../../hooks/useScenarioData";
import { useCreateWorkOrder, useWorkOrderPreview } from "../../hooks/useWorkOrders";
import type { Operation, Robot, WorkOrder } from "../../types";
import {
  MAX_WORK_ORDER_QUANTITY,
  WORK_ORDER_QUANTITY_WARN,
} from "../../types/warehouse";
import { WorkOrderPreviewPanel } from "./WorkOrderPreviewPanel";
import { WorkOrderResultNotice } from "./WorkOrderResultNotice";
import { buildWorkOrderCreateBody, buildWorkOrderPreviewBody } from "./workOrderFormPayload";

type AssignMode = "auto" | "manual";

function resetFormFields() {
  return { itemCode: "", quantity: "1", zoneId: "" };
}

function validationMessage({
  disabled,
  itemCode,
  qty,
  quantityOverMax,
  quantityOverStock,
  stockOnHand,
  noEmptySlot,
  needsZone,
  operation,
  manualSlotMissing,
}: {
  disabled?: boolean;
  itemCode: string;
  qty: number;
  quantityOverMax: boolean;
  quantityOverStock: boolean | "";
  stockOnHand: number;
  noEmptySlot: boolean;
  needsZone: boolean;
  operation: Operation;
  manualSlotMissing: boolean;
}) {
  if (disabled) return "비상 정지 중 — 입출고 실행 불가";
  if (!itemCode) return "품목을 선택하세요.";
  if (!Number.isFinite(qty) || qty < 1) return "수량은 1 이상이어야 합니다.";
  if (quantityOverMax) return WORK_ORDER_ERROR_HINTS.quantity_exceeds_limit;
  if (quantityOverStock) return `보유 재고(${stockOnHand})를 초과할 수 없습니다.`;
  if (noEmptySlot) return "빈 슬롯이 없습니다.";
  if (needsZone) return `${operationLabel(operation)} 존을 선택하세요.`;
  if (manualSlotMissing) return "수동 모드: 보관 슬롯 1곳을 선택하세요.";
  return null;
}

export function WorkOrderForm({
  robots,
  onClose,
  disabled,
  emergencyRobots = [],
}: {
  robots: Robot[];
  onClose?: () => void;
  disabled?: boolean;
  emergencyRobots?: string[];
}) {
  const { data: items = [], isLoading: itemsLoading, isError: itemsError } = useItems();
  const { data: inventory = [] } = useInventory();
  const { data: slots = [] } = useStorageSlots();
  const { data: waypoints = [] } = useAllWaypoints();
  const create = useCreateWorkOrder();

  const [operation, setOperation] = useState<Operation>("inbound");
  const [floor, setFloor] = useState("1");
  const [assignMode, setAssignMode] = useState<AssignMode>("auto");
  const [robotId, setRobotId] = useState("");
  const [manualSlotId, setManualSlotId] = useState("");
  const [itemCode, setItemCode] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [zoneId, setZoneId] = useState("");
  const [autoStart, setAutoStart] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [result, setResult] = useState<WorkOrder | null>(null);

  const selectedRobotEmergency = Boolean(robotId && emergencyRobots.includes(robotId));
  const formBlocked = Boolean(disabled) || selectedRobotEmergency;

  const qty = Number(quantity);
  const selectedFloor = Number(floor) === 2 ? 2 : 1;
  const floorIsAuto = assignMode === "auto";
  const requestedFloor = floorIsAuto ? undefined : selectedFloor;
  const zoneType = zoneTypeForOperation(operation);
  const zoneOptions = useMemo(
    () => waypoints.filter(
      (wp) => wp.waypoint_type === zoneType && (wp.status ?? "ACTIVE") === "ACTIVE",
    ),
    [waypoints, zoneType],
  );
  const linkedDockPairs = useMemo(() => pairsFromWaypoints(waypoints), [waypoints]);

  useEffect(() => {
    setError(null);
    setErrorCode(null);
    setResult(null);
  }, [operation, itemCode, quantity, zoneId, requestedFloor]);

  useEffect(() => {
    setManualSlotId("");
  }, [operation, itemCode, requestedFloor]);

  useEffect(() => {
    if (zoneOptions.length === 1) {
      setZoneId(zoneOptions[0].waypoint_id);
    } else if (zoneId && !zoneOptions.some((z) => z.waypoint_id === zoneId)) {
      setZoneId("");
    }
  }, [zoneOptions, zoneId]);

  const stockOnHand = useMemo(
    () => stockOnHandForItem(inventory, itemCode, requestedFloor),
    [inventory, itemCode, requestedFloor],
  );

  const emptySlots = useMemo(() => {
    if (operation !== "inbound") return 0;
    return emptySlotCount(slots, inventory, requestedFloor);
  }, [operation, slots, inventory, requestedFloor]);

  const quantityWarn = qty > WORK_ORDER_QUANTITY_WARN;
  const quantityOverMax = qty > MAX_WORK_ORDER_QUANTITY;
  const quantityOverStock = operation === "outbound" && itemCode && qty > stockOnHand;
  const noEmptySlot = operation === "inbound" && !!itemCode && emptySlots < 1;

  const slotCandidates = useMemo(
    () => slotCandidatesForOperation(operation, slots, inventory, itemCode, qty, selectedFloor),
    [operation, slots, inventory, itemCode, qty, selectedFloor],
  );

  const manualSlotReady = assignMode === "manual" && manualSlotId.length > 0;

  const selectedZoneMissingScan = !!zoneId && !linkedDockPairs.some((p) => p.dock_waypoint_id === zoneId && p.dock_mode === "aruco");
  const needsZone = zoneOptions.length > 0 && !zoneId;
  const manualSlotMissing = assignMode === "manual" && !manualSlotReady;

  const payloadInput = {
    operation,
    itemCode,
    quantity: qty,
    floor: requestedFloor,
    inboundWaypointId: zoneId,
    outboundWaypointId: zoneId,
    slotId: manualSlotReady ? manualSlotId : undefined,
  };

  const previewBody =
    itemCode && Number.isFinite(qty) && qty >= 1 && qty <= MAX_WORK_ORDER_QUANTITY
      && (assignMode === "auto" || manualSlotReady)
      ? buildWorkOrderPreviewBody(payloadInput)
      : null;

  const preview = useWorkOrderPreview(previewBody);
  const submitValidation = validationMessage({
    disabled,
    itemCode,
    qty,
    quantityOverMax,
    quantityOverStock,
    stockOnHand,
    noEmptySlot,
    needsZone,
    operation,
    manualSlotMissing,
  });
  const submitDisabled = formBlocked || create.isPending || items.length === 0 || submitValidation !== null;

  const submit = async () => {
    setError(null);
    setErrorCode(null);
    setResult(null);
    if (submitValidation) {
      setError(submitValidation);
      return;
    }
    try {
      const order = await create.mutateAsync(buildWorkOrderCreateBody({
        ...payloadInput,
        autoStart,
        robotId,
      }));
      setResult(order);
      const reset = resetFormFields();
      setItemCode(reset.itemCode);
      setQuantity(reset.quantity);
      setZoneId(reset.zoneId);
    } catch (e) {
      if (e instanceof ApiError) {
        const detail = parseWorkOrderApiDetail(e.message);
        setErrorCode(detail);
        setError(WORK_ORDER_ERROR_HINTS[detail] || detail || `요청 실패 (HTTP ${e.status})`);
      } else {
        setError((e as Error).message);
      }
    }
  };


  return (
    <Panel title="입출고 요청">
      {error ? (
        <div className="inline-alert warn">
          {error}
          {errorCode === "insufficient_inventory" ? (
            <div className="action-row" style={{ marginTop: 8 }}>
              <Link className="btn secondary" to="/admin/warehouse">재고 보기</Link>
            </div>
          ) : null}
          {errorCode === "no_available_slot" ? (
            <div className="action-row" style={{ marginTop: 8 }}>
              <Link className="btn secondary" to="/admin/warehouse">슬롯 보기</Link>
            </div>
          ) : null}
        </div>
      ) : null}
      {result ? <WorkOrderResultNotice result={result} autoStart={autoStart} requestedFloor={requestedFloor} /> : null}
      <div className="toolbar">
        <Button variant={operation === "inbound" ? "primary" : "secondary"} onClick={() => setOperation("inbound")}>입고</Button>
        <Button variant={operation === "outbound" ? "primary" : "secondary"} onClick={() => setOperation("outbound")}>출고</Button>
      </div>
      <div className="toolbar" style={{ marginTop: 8 }}>
        <span className="muted">슬롯 할당</span>
        <Button variant={assignMode === "auto" ? "primary" : "secondary"} onClick={() => setAssignMode("auto")}>자동</Button>
        <Button variant={assignMode === "manual" ? "primary" : "secondary"} onClick={() => setAssignMode("manual")}>직접 지정</Button>
      </div>
      {itemsLoading ? <p className="muted">품목 목록 불러오는 중…</p> : null}
      {itemsError ? (
        <div className="inline-alert warn">
          품목 목록을 불러오지 못했습니다. <Link to="/admin/warehouse">창고 관리</Link>에서 품목을 등록하세요.
        </div>
      ) : null}
      {!itemsLoading && !itemsError && items.length === 0 ? (
        <div className="inline-alert warn">
          등록된 품목이 없습니다. <Link to="/admin/warehouse">창고 관리</Link>에서 품목을 먼저 등록하세요.
        </div>
      ) : null}
      <div className="form-grid compact">
        <Field label="품목">
          <select value={itemCode} onChange={(e) => setItemCode(e.target.value)} disabled={items.length === 0}>
            <option value="">품목 선택</option>
            {items.map((it) => <option key={it.item_code} value={it.item_code}>{it.item_name} ({it.item_code})</option>)}
          </select>
          {itemCode ? (
            <span className="muted">
              {operation === "outbound"
                ? `${floorIsAuto ? "전체 층" : `${selectedFloor}층`} 재고 ${stockOnHand}개`
                : `${floorIsAuto ? "전체 층" : `${selectedFloor}층`} 빈 셀 ${emptySlots}곳`}
            </span>
          ) : null}
        </Field>
        <Field label="수량">
          <input
            type="number"
            min={1}
            max={MAX_WORK_ORDER_QUANTITY}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
          {quantityWarn && !quantityOverMax ? (
            <span className="muted">수량은 작업 1건 완료 시 재고에 반영됩니다 (물리 이동 1회).</span>
          ) : null}
          {quantityOverMax ? <span className="pill err">최대 {MAX_WORK_ORDER_QUANTITY}개</span> : null}
          {quantityOverStock ? <span className="pill err">재고 부족</span> : null}
          {noEmptySlot ? <span className="pill err">빈 슬롯 없음</span> : null}
        </Field>
        {floorIsAuto ? (
          <Field label="층">
            <span className="muted">1/2층 자동</span>
          </Field>
        ) : (
          <Field label="층">
            <select value={floor} onChange={(e) => setFloor(e.target.value)}>
              <option value="1">1층</option>
              <option value="2">2층</option>
            </select>
            <span className="muted">리프트 dock_transfer level {selectedFloor}</span>
          </Field>
        )}
        {zoneOptions.length > 0 ? (
          <Field label={`${operationLabel(operation)} 존`}>
            <select value={zoneId} onChange={(e) => setZoneId(e.target.value)}>
              {zoneOptions.length > 1 ? <option value="">존 선택</option> : null}
              {zoneOptions.map((z) => (
                <option key={z.waypoint_id} value={z.waypoint_id}>{z.name} ({z.waypoint_id})</option>
              ))}
            </select>
          </Field>
        ) : (
          <p className="muted">
            {operationLabel(operation)} 존이 없습니다. <Link to="/admin/map">맵 편집</Link>에서 존을 등록하세요.
          </p>
        )}
        {zoneId && selectedZoneMissingScan ? (
          <p className="muted" style={{ marginTop: 4 }}>
            선택한 {operationLabel(operation)} 존에 ArUco 스캔 페어가 없습니다. <Link to="/admin/map">맵 편집</Link>에서 스캔 마커를 연결하세요.
          </p>
        ) : null}
        {assignMode === "manual" && itemCode ? (
          <Field label="보관 슬롯">
            {slotCandidates.length === 0 ? (
              <span className="pill err">선택 가능한 슬롯이 없습니다.</span>
            ) : (
              <select value={manualSlotId} onChange={(e) => setManualSlotId(e.target.value)}>
                <option value="">슬롯 선택</option>
                {slotCandidates.map((c) => (
                  <option key={c.slot_id} value={c.slot_id}>
                    {c.label} ({c.slot_id}) — {c.hint}
                  </option>
                ))}
              </select>
            )}
          </Field>
        ) : null}
        <Field label="로봇 배정">
          <select value={robotId} onChange={(e) => setRobotId(e.target.value)}>
            <option value="">자동 배정</option>
            {robots.map((r) => (
              <option key={r.robot_id} value={r.robot_id}>{r.display_name || r.robot_id}</option>
            ))}
          </select>
          {robotId && selectedRobotEmergency ? (
            <span className="pill err">선택한 로봇이 비상 정지 상태입니다</span>
          ) : null}
          {robotId && !selectedRobotEmergency ? (
            <span className="muted">생성 시 {robotId}에 즉시 배정 (유휴·localized·명령 수신 가능해야 함)</span>
          ) : null}
        </Field>
      </div>
      {preview.data ? <WorkOrderPreviewPanel preview={preview.data} /> : null}
      {preview.isError ? (
        <div className="inline-alert warn" style={{ marginTop: 8 }}>
          계획 미리보기 실패 — 실행 시 서버에서 다시 검증합니다.
        </div>
      ) : null}
      <div className="action-row">
        <label className="switch-line">
          <input
            type="checkbox"
            checked={autoStart}
            onChange={(e) => setAutoStart(e.target.checked)}
            disabled={selectedZoneMissingScan}
          />
          생성 후 자동 시작
        </label>
        {selectedZoneMissingScan ? (
          <span className="muted">스캔 페어 없음 — 자동 시작 불가, 생성만 가능</span>
        ) : null}
        {onClose ? <Button variant="secondary" onClick={onClose}>닫기</Button> : null}
        <Button
          onClick={submit}
          disabled={submitDisabled}
        >
          {create.isPending ? "요청 중" : "실행"}
        </Button>
      </div>
    </Panel>
  );
}
