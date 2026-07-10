import { useMemo, useState } from "react";
import { DataTable, type Column } from "./DataTable";

interface FilterableTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  getKey: (row: T, index: number) => string | number;
  searchFields: (keyof T)[];
  statusField?: keyof T;
  emptyText?: string;
}

// 레거시 getFilter/matchRow/populateStatus 를 재사용 컴포넌트로.
// 검색(부분일치) + 선택적 상태 필터 + N/total 카운트 를 DataTable 위에 얹는다.
export function FilterableTable<T>({ columns, rows, getKey, searchFields, statusField, emptyText }: FilterableTableProps<T>) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");

  const statusOptions = useMemo(() => {
    if (!statusField) return [];
    return [...new Set(rows.map((r) => String(r[statusField] ?? "")).filter(Boolean))].sort();
  }, [rows, statusField]);

  const filtered = useMemo(() => {
    const query = q.toLowerCase().trim();
    return rows.filter((r) => {
      if (status && statusField && String(r[statusField] ?? "") !== status) return false;
      if (!query) return true;
      return searchFields.map((f) => String(r[f] ?? "")).join(" ").toLowerCase().includes(query);
    });
  }, [rows, q, status, statusField, searchFields]);

  return (
    <>
      <div className="toolbar">
        <input className="search" placeholder="검색" value={q} onChange={(e) => setQ(e.target.value)} />
        {statusField && (
          <select className="filter" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">상태: 전체</option>
            {statusOptions.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
        <span className="rowcount">{filtered.length} / {rows.length}</span>
      </div>
      <DataTable columns={columns} rows={filtered} getKey={getKey} emptyText={emptyText} />
    </>
  );
}
