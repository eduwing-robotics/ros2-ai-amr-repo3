import { useState } from "react";
import { Panel } from "../../components/Panel";
import { Field } from "../../components/Field";
import { Button } from "../../components/Button";
import type { StorageSlot } from "../../types";
import type { useWarehouseMutations } from "../warehouse/useWarehouseData";
import { EMPTY_SLOT, type RunWarehouseMutation } from "./warehouseAdminForms";

type WarehouseMutations = ReturnType<typeof useWarehouseMutations>;

export function WarehouseSlotsPanel({
  slots,
  mutations,
  run,
}: {
  slots: StorageSlot[];
  mutations: WarehouseMutations;
  run: RunWarehouseMutation;
}) {
  const [slotForm, setSlotForm] = useState(EMPTY_SLOT);
  const [editingSlotId, setEditingSlotId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const resetSlotForm = () => {
    setSlotForm(EMPTY_SLOT);
    setEditingSlotId(null);
  };

  const editSlot = (s: StorageSlot) => {
    setSlotForm({
      slotId: s.slot_id,
      slotLabel: s.label,
      waypointId: s.waypoint_id || s.slot_id,
      sortOrder: String(s.sort_order ?? 0),
      approachGroup: s.approach_group || "",
      enabled: s.enabled ?? true,
    });
    setEditingSlotId(s.slot_id);
  };

  return (
    <Panel title={`보관 슬롯 / locations (${slots.length})`}>
      <p className="muted-hint">DBML <code>locations(type=storage)</code>. 슬롯(층 셀) 1칸당 파레트 1개 정책입니다.</p>
      <div className="form-grid compact">
        <Field label="슬롯 ID (location_id)">
          <input
            value={slotForm.slotId}
            disabled={editingSlotId != null}
            onChange={(e) => setSlotForm((f) => ({ ...f, slotId: e.target.value }))}
          />
        </Field>
        <Field label="라벨">
          <input value={slotForm.slotLabel} onChange={(e) => setSlotForm((f) => ({ ...f, slotLabel: e.target.value }))} placeholder="표시명 (미입력 시 ID)" />
        </Field>
        <Field label="waypoint_id">
          <input value={slotForm.waypointId} onChange={(e) => setSlotForm((f) => ({ ...f, waypointId: e.target.value }))} placeholder="미입력 시 슬롯 ID" />
        </Field>
        <Field label="정렬순서">
          <input type="number" value={slotForm.sortOrder} onChange={(e) => setSlotForm((f) => ({ ...f, sortOrder: e.target.value }))} />
        </Field>
        <Field label="접근그룹">
          <input value={slotForm.approachGroup} onChange={(e) => setSlotForm((f) => ({ ...f, approachGroup: e.target.value }))} placeholder="선택" />
        </Field>
        <Field label="활성">
          <label>
            <input type="checkbox" checked={slotForm.enabled} onChange={(e) => setSlotForm((f) => ({ ...f, enabled: e.target.checked }))} />
            {" "}enabled
          </label>
        </Field>
        <div className="action-row">
          <Button
            disabled={!slotForm.slotId || mutations.upsertSlot.isPending}
            onClick={() => run(async () => {
              await mutations.upsertSlot.mutateAsync({
                slot_id: slotForm.slotId.trim(),
                label: slotForm.slotLabel.trim() || slotForm.slotId.trim(),
                waypoint_id: slotForm.waypointId.trim() || slotForm.slotId.trim(),
                sort_order: Number(slotForm.sortOrder) || 0,
                approach_group: slotForm.approachGroup.trim(),
                enabled: slotForm.enabled,
              });
              resetSlotForm();
            })}
          >
            {editingSlotId ? "수정 저장" : "추가"}
          </Button>
          {editingSlotId ? (
            <Button variant="secondary" onClick={resetSlotForm}>취소</Button>
          ) : null}
        </div>
      </div>
      <div className="table-wrap clean-table">
        <table>
          <thead><tr><th>슬롯</th><th>location_id</th><th>waypoint</th><th>순서</th><th>그룹</th><th>활성</th><th></th></tr></thead>
          <tbody>
            {slots.length === 0 ? <tr><td colSpan={7} className="empty">슬롯 없음</td></tr> :
              slots.map((s) => (
                <tr key={s.slot_id}>
                  <td>{s.label}</td><td className="mono">{s.slot_id}</td><td className="mono">{s.waypoint_id || "-"}</td>
                  <td>{s.sort_order ?? 0}</td><td>{s.approach_group || "-"}</td><td>{s.enabled ? "Y" : "N"}</td>
                  <td>
                    <Button variant="row" onClick={() => editSlot(s)}>수정</Button>
                    {pendingDelete === s.slot_id ? (
                      <span className="delete-confirm">
                        <Button variant="danger" onClick={() => run(async () => { await mutations.deleteSlot.mutateAsync(s.slot_id); setPendingDelete(null); })}>확인</Button>
                        <Button variant="secondary" onClick={() => setPendingDelete(null)}>취소</Button>
                      </span>
                    ) : (
                      <Button variant="row-danger" onClick={() => setPendingDelete(s.slot_id)}>삭제</Button>
                    )}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
