import { useState } from "react";
import { describeApiError } from "../../lib/apiErrors";
import { useItems, useStorageSlots, useInventory, useWarehouseMutations } from "../warehouse/useWarehouseData";
import { WarehouseItemsPanel } from "./WarehouseItemsPanel";
import { WarehouseSlotsPanel } from "./WarehouseSlotsPanel";
import { WarehouseInventoryPanel } from "./WarehouseInventoryPanel";

export function WarehouseAdmin() {
  const { data: items = [] } = useItems();
  const { data: slots = [] } = useStorageSlots();
  const { data: inventory = [] } = useInventory();
  const mutations = useWarehouseMutations();
  const [tab, setTab] = useState<"items" | "slots" | "inventory">("items");
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(describeApiError(e));
    }
  };

  return (
    <div className="ops-page">
      <div className="ops-heading">
        <div>
          <h2>슬롯 · 재고 · 품목</h2>
          <p>입출고 자동화가 의존하는 마스터 데이터를 정의한다. 행별 수정은 upsert API로 저장한다.</p>
        </div>
      </div>
      <div className="tab-bar">
        {(["items", "slots", "inventory"] as const).map((t) => (
          <button key={t} type="button" className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t === "items" ? "품목" : t === "slots" ? "슬롯" : "재고"}
          </button>
        ))}
      </div>
      {error ? <div className="inline-alert warn">{error}</div> : null}

      {tab === "items" ? <WarehouseItemsPanel items={items} mutations={mutations} run={run} /> : null}
      {tab === "slots" ? <WarehouseSlotsPanel slots={slots} mutations={mutations} run={run} /> : null}
      {tab === "inventory" ? (
        <WarehouseInventoryPanel
          inventory={inventory}
          slots={slots}
          items={items}
          mutations={mutations}
          run={run}
        />
      ) : null}
    </div>
  );
}
