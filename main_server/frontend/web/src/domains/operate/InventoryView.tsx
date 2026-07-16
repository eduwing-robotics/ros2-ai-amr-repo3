import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Panel } from "../../components/Panel";
import { Button } from "../../components/Button";
import { useInventory, useItems, useStorageSlots } from "../warehouse/useWarehouseData";
import type { InventoryRecord } from "../../types/warehouse";

/** 운영용 읽기전용 재고 뷰. 편집은 관리 ▸ 슬롯·재고·품목에 유지.
 *  compact=관제 코크핏 밴드용(편집 푸터 생략). */
export function InventoryView({
  compact = false,
  onSlotFocus,
  onSubviewChange,
}: {
  compact?: boolean;
  onSlotFocus?: (waypointId: string | null) => void;
  onSubviewChange?: (subview: "item" | "slot") => void;
} = {}) {
  const [floorFilter, setFloorFilter] = useState<0 | 1 | 2>(0); // 0=전체
  const { data: inventory = [], isLoading, isError, refetch, isFetching } = useInventory(
    floorFilter ? { floor: floorFilter } : undefined,
  );
  const { data: slots = [] } = useStorageSlots();
  const { data: items = [] } = useItems();
  const [q, setQ] = useState("");
  const [subview, setSubview] = useState<"item" | "slot">("item");
  const [selectedCellKey, setSelectedSlotId] = useState<string | null>(null);

  useEffect(() => { onSubviewChange?.(subview); }, [subview, onSubviewChange]);
  useEffect(() => () => onSlotFocus?.(null), [onSlotFocus]);
  const changeSubview = (next: "item" | "slot") => {
    setSubview(next);
    if (next === "item") { setSelectedSlotId(null); onSlotFocus?.(null); }
  };
  const selectSlot = (cellKey: string, waypointId: string) => {
    const next = selectedCellKey === cellKey ? null : cellKey;
    setSelectedSlotId(next);
    onSlotFocus?.(next ? waypointId : null);
  };
  const floors = useMemo(() => (floorFilter ? [floorFilter] : [1, 2]), [floorFilter]);

  const itemTotals = useMemo(() => {
    const byCode = new Map<string, { code: string; name: string; qty: number }>();
    for (const it of items) byCode.set(it.item_code, { code: it.item_code, name: it.item_name, qty: 0 });
    for (const r of inventory) {
      const cur = byCode.get(r.item_code) ?? { code: r.item_code, name: r.item_name ?? r.item_code, qty: 0 };
      cur.qty += r.quantity;
      byCode.set(r.item_code, cur);
    }
    return [...byCode.values()].sort((a, b) => b.qty - a.qty || a.code.localeCompare(b.code));
  }, [items, inventory]);

  const filteredTotals = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return itemTotals;
    return itemTotals.filter((t) => t.name.toLowerCase().includes(needle) || t.code.toLowerCase().includes(needle));
  }, [itemTotals, q]);

  const slotRows = useMemo(() => {
    const byCell = new Map<string, InventoryRecord[]>();
    for (const r of inventory) {
      const key = `${r.slot_id}:${r.floor ?? 1}`;
      const arr = byCell.get(key) ?? [];
      arr.push(r);
      byCell.set(key, arr);
    }
    return [...slots]
      .sort((a, b) => a.sort_order - b.sort_order || a.slot_id.localeCompare(b.slot_id))
      .flatMap((s) => floors.map((floor) => {
        const recs = (byCell.get(`${s.slot_id}:${floor}`) ?? []).filter((r) => r.quantity > 0);
        const used = recs.reduce((n, r) => n + r.quantity, 0);
        return { slot: s, floor, recs, used };
      }));
  }, [slots, inventory, floors]);

  const totalQty = useMemo(() => inventory.reduce((n, r) => n + r.quantity, 0), [inventory]);
  const usedSlots = slotRows.filter((s) => s.used > 0).length;
  const totalCells = slots.length * floors.length;

  const itemSection = (
    <section className="inv-section">
      <div className="inv-section-head">
        <h3>품목별 재고</h3>
        <input className="search" placeholder="품목 검색" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="table-wrap clean-table compact-table">
        <table>
          <thead><tr><th>품목</th><th className="num">수량</th></tr></thead>
          <tbody>
            {filteredTotals.length === 0 ? (
              <tr><td colSpan={2} className="empty">{q ? "검색 결과 없음" : "재고 없음"}</td></tr>
            ) : filteredTotals.map((t) => (
              <tr key={t.code}>
                <td>{t.name} <span className="muted mono">({t.code})</span></td>
                <td className="num"><span className={t.qty === 0 ? "pill warn" : "pill ok"}>{t.qty}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );

  const slotSection = (
    <section className="inv-section">
      <div className="inv-section-head"><h3>슬롯별 재고</h3></div>
      <div className="table-wrap clean-table compact-table">
        <table>
          <thead><tr><th>슬롯</th><th>층</th><th className="num">셀 용량</th><th className="num">사용</th><th>품목</th></tr></thead>
          <tbody>
            {slotRows.length === 0 ? (
              <tr><td colSpan={5} className="empty">등록된 슬롯 없음</td></tr>
            ) : slotRows.map(({ slot, floor, recs, used }) => (
              <tr key={`${slot.slot_id}:${floor}`} className={selectedCellKey === `${slot.slot_id}:${floor}` ? "selected" : ""} tabIndex={0} aria-selected={selectedCellKey === `${slot.slot_id}:${floor}`} onClick={() => selectSlot(`${slot.slot_id}:${floor}`, slot.waypoint_id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectSlot(`${slot.slot_id}:${floor}`, slot.waypoint_id); } }}>
                <td>{slot.label || slot.slot_id}</td>
                <td>{floor}층</td>
                <td className="num">{slot.capacity}</td>
                <td className="num"><span className={used >= slot.capacity ? "pill warn" : used > 0 ? "pill ok" : "pill idle"}>{used}</span></td>
                <td>{recs.length === 0 ? <span className="muted">비어있음</span> : recs.map((r) => `${r.item_name ?? r.item_code} ${r.quantity}`).join(" · ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );

  return (
    <Panel title="재고" className={`inventory-view${compact ? " compact" : ""}`}>
      <div className="toolbar">
        <div className="metric"><span>품목</span><strong>{itemTotals.length}</strong></div>
        <div className="metric"><span>총재고</span><strong>{totalQty}</strong></div>
        <div className="metric"><span>셀사용</span><strong>{usedSlots}/{totalCells}</strong></div>
        <div className="toolbar-spacer" />
        <div className="segmented" role="group" aria-label="층 필터">
          {([[0, "전체"], [1, "1층"], [2, "2층"]] as const).map(([f, label]) => (
            <Button
              key={f}
              variant={floorFilter === f ? "primary" : "secondary"}
              onClick={() => setFloorFilter(f)}
            >
              {label}
            </Button>
          ))}
        </div>
        <Button variant="secondary" onClick={() => refetch()} disabled={isFetching}>{isFetching ? "갱신 중" : "새로고침"}</Button>
      </div>

      {isError ? <div className="inline-alert warn">재고를 불러오지 못했습니다.</div> : null}
      {isLoading ? <p className="muted">재고 불러오는 중…</p> : null}

      <div className="segmented inv-subview" role="tablist" aria-label="재고 보기">
          <button type="button" role="tab" aria-selected={subview === "item"} className={subview === "item" ? "active" : ""} onClick={() => changeSubview("item")}>품목별</button>
          <button type="button" role="tab" aria-selected={subview === "slot"} className={subview === "slot" ? "active" : ""} onClick={() => changeSubview("slot")}>슬롯별</button>
      </div>

      {subview === "item" ? itemSection : null}
      {subview === "slot" ? slotSection : null}

      {compact ? null : (
        <div className="action-row inv-footer">
          <span className="muted">편집은 관리 ▸ 슬롯·재고·품목에서</span>
          <Link className="btn secondary" to="/admin/warehouse">관리에서 열기</Link>
        </div>
      )}
    </Panel>
  );
}
