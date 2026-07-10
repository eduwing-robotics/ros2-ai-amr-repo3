import { useState } from "react";
import { Panel } from "../../components/Panel";
import { Field } from "../../components/Field";
import { Button } from "../../components/Button";
import type { InventoryRecord, Item, StorageSlot } from "../../types";
import type { useWarehouseMutations } from "../../hooks/useWarehouseData";
import { EMPTY_INV, invKey, type RunWarehouseMutation } from "./warehouseAdminForms";

type WarehouseMutations = ReturnType<typeof useWarehouseMutations>;

export function WarehouseInventoryPanel({
  inventory,
  slots,
  items,
  mutations,
  run,
}: {
  inventory: InventoryRecord[];
  slots: StorageSlot[];
  items: Item[];
  mutations: WarehouseMutations;
  run: RunWarehouseMutation;
}) {
  const [invForm, setInvForm] = useState(EMPTY_INV);
  const [editingInvKey, setEditingInvKey] = useState<string | null>(null);

  const resetInvForm = () => {
    setInvForm(EMPTY_INV);
    setEditingInvKey(null);
  };

  const editInventory = (r: InventoryRecord) => {
    setInvForm({
      slot: r.slot_id,
      item: r.item_code,
      floor: String(r.floor ?? 1),
      qty: String(r.quantity ?? 0),
    });
    setEditingInvKey(invKey(r));
  };

  return (
    <Panel title={`재고 (${inventory.length})`}>
      <div className="form-grid compact">
        <Field label="슬롯">
          <select value={invForm.slot} disabled={editingInvKey != null} onChange={(e) => setInvForm((f) => ({ ...f, slot: e.target.value }))}>
            <option value="">선택</option>
            {slots.map((s) => <option key={s.slot_id} value={s.slot_id}>{s.label}</option>)}
          </select>
        </Field>
        <Field label="품목">
          <select value={invForm.item} disabled={editingInvKey != null} onChange={(e) => setInvForm((f) => ({ ...f, item: e.target.value }))}>
            <option value="">선택</option>
            {items.map((it) => <option key={it.item_code} value={it.item_code}>{it.item_name}</option>)}
          </select>
        </Field>
        <Field label="층 (1|2)">
          <select value={invForm.floor} disabled={editingInvKey != null} onChange={(e) => setInvForm((f) => ({ ...f, floor: e.target.value }))}>
            <option value="1">1</option>
            <option value="2">2</option>
          </select>
        </Field>
        <Field label="수량">
          <input type="number" min={0} value={invForm.qty} onChange={(e) => setInvForm((f) => ({ ...f, qty: e.target.value }))} />
        </Field>
        <div className="action-row">
          <Button
            disabled={!invForm.slot || !invForm.item || mutations.upsertInventory.isPending}
            onClick={() => run(async () => {
              await mutations.upsertInventory.mutateAsync({
                slot_id: invForm.slot,
                item_code: invForm.item,
                quantity: Number(invForm.qty) || 0,
                floor: Number(invForm.floor) || 1,
              });
              resetInvForm();
            })}
          >
            {editingInvKey ? "수량 수정" : "수량 반영"}
          </Button>
          {editingInvKey ? (
            <Button variant="secondary" onClick={resetInvForm}>취소</Button>
          ) : null}
        </div>
      </div>
      <div className="table-wrap clean-table">
        <table>
          <thead><tr><th>슬롯</th><th>층</th><th>품목</th><th>수량</th><th></th></tr></thead>
          <tbody>
            {inventory.length === 0 ? <tr><td colSpan={5} className="empty">재고 없음</td></tr> :
              inventory.map((r) => (
                <tr key={invKey(r)}>
                  <td>{r.slot_label || r.slot_id}</td><td>{r.floor ?? 1}</td><td>{r.item_name || r.item_code}</td>
                  <td>{r.quantity}</td>
                  <td>
                    <Button variant="row" onClick={() => editInventory(r)}>수정</Button>
                    <Button
                      variant="row-danger"
                      disabled={mutations.upsertInventory.isPending}
                      onClick={() => run(() => mutations.upsertInventory.mutateAsync({
                        slot_id: r.slot_id,
                        item_code: r.item_code,
                        quantity: 0,
                        floor: r.floor ?? 1,
                      }))}
                    >
                      초기화
                    </Button>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
