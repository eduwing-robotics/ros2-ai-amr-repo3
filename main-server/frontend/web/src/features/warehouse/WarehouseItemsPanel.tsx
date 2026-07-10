import { useState } from "react";
import { Panel } from "../../components/Panel";
import { Field } from "../../components/Field";
import { Button } from "../../components/Button";
import type { Item } from "../../types";
import type { useWarehouseMutations } from "../../hooks/useWarehouseData";
import { EMPTY_ITEM, type RunWarehouseMutation } from "./warehouseAdminForms";

type WarehouseMutations = ReturnType<typeof useWarehouseMutations>;

export function WarehouseItemsPanel({
  items,
  mutations,
  run,
}: {
  items: Item[];
  mutations: WarehouseMutations;
  run: RunWarehouseMutation;
}) {
  const [itemForm, setItemForm] = useState(EMPTY_ITEM);
  const [editingItemCode, setEditingItemCode] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const resetItemForm = () => {
    setItemForm(EMPTY_ITEM);
    setEditingItemCode(null);
  };

  const editItem = (it: Item) => {
    setItemForm({ itemCode: it.item_code, itemName: it.item_name, unit: it.unit || "EA" });
    setEditingItemCode(it.item_code);
  };

  return (
    <Panel title={`품목 마스터 (${items.length})`}>
      <div className="form-grid compact">
        <Field label="코드">
          <input
            value={itemForm.itemCode}
            disabled={editingItemCode != null}
            onChange={(e) => setItemForm((f) => ({ ...f, itemCode: e.target.value }))}
          />
        </Field>
        <Field label="이름">
          <input value={itemForm.itemName} onChange={(e) => setItemForm((f) => ({ ...f, itemName: e.target.value }))} />
        </Field>
        <Field label="단위">
          <input value={itemForm.unit} onChange={(e) => setItemForm((f) => ({ ...f, unit: e.target.value }))} />
        </Field>
        <div className="action-row">
          <Button
            disabled={!itemForm.itemCode || !itemForm.itemName || mutations.upsertItem.isPending}
            onClick={() => run(async () => {
              await mutations.upsertItem.mutateAsync({
                item_code: itemForm.itemCode.trim(),
                item_name: itemForm.itemName.trim(),
                unit: itemForm.unit.trim() || "EA",
              });
              resetItemForm();
            })}
          >
            {editingItemCode ? "수정 저장" : "추가"}
          </Button>
          {editingItemCode ? (
            <Button variant="secondary" onClick={resetItemForm}>취소</Button>
          ) : null}
        </div>
      </div>
      <div className="table-wrap clean-table">
        <table>
          <thead><tr><th>코드</th><th>이름</th><th>단위</th><th></th></tr></thead>
          <tbody>
            {items.length === 0 ? <tr><td colSpan={4} className="empty">품목 없음</td></tr> :
              items.map((it) => (
                <tr key={it.item_code}>
                  <td className="mono">{it.item_code}</td><td>{it.item_name}</td><td>{it.unit}</td>
                  <td>
                    <Button variant="row" onClick={() => editItem(it)}>수정</Button>
                    {pendingDelete === it.item_code ? (
                      <span className="delete-confirm">
                        <Button variant="danger" onClick={() => run(async () => { await mutations.deleteItem.mutateAsync(it.item_code); setPendingDelete(null); })}>확인</Button>
                        <Button variant="secondary" onClick={() => setPendingDelete(null)}>취소</Button>
                      </span>
                    ) : (
                      <Button variant="row-danger" onClick={() => setPendingDelete(it.item_code)}>삭제</Button>
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
