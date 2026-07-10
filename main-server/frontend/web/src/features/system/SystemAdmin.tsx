import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useDbRows, useDbTables } from "../../hooks/useAdminData";
import { useStatus } from "../../hooks/useStatus";
import { Button } from "../../components/Button";
import { Pill } from "../../components/Pill";
import { cell } from "../../lib/format";

const fmt = (v: unknown): string => {
  const raw = cell(typeof v === "object" && v !== null ? JSON.stringify(v) : v);
  return raw.length > 140 ? `${raw.slice(0, 140)}...` : raw;
};

function DbTablesPanel() {
  const { data: tables = [] } = useDbTables();
  const [selected, setSelected] = useState("");
  const [limit, setLimit] = useState(100);

  useEffect(() => {
    if (!selected && tables.length) setSelected(tables[0].table_name);
  }, [tables, selected]);

  const active = selected || tables[0]?.table_name || "";
  const { data: payload } = useDbRows(active || undefined, limit);
  const columns = payload?.columns ?? [];
  const rows = payload?.rows ?? [];

  return (
    <div className="system-db-panel">
      <div className="system-db-tables">
        {tables.length === 0 ? <div className="empty">노출 가능한 테이블 없음</div> : tables.map((t) => (
          <div
            key={t.table_name}
            className={`card clickable${t.table_name === active ? " active" : ""}`}
            onClick={() => setSelected(t.table_name)}
          >
            <strong>{t.table_name}</strong>
            <div>rows: {t.row_count}</div>
          </div>
        ))}
      </div>
      <div className="system-db-rows">
        <div className="toolbar">
          <h3>{payload?.table_name ?? "—"}</h3>
          <select className="rowsel" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {[50, 100, 200, 500].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <span className="rowcount">{rows.length} rows</span>
        </div>
        <div className="table-wrap clean-table">
          <table>
            <thead><tr>{columns.map((c) => <th key={c.name}>{c.name}</th>)}</tr></thead>
            <tbody>
              {rows.length === 0 ? <tr><td colSpan={Math.max(columns.length, 1)} className="empty">row 없음</td></tr> :
                rows.map((row, i) => <tr key={i}>{columns.map((c) => <td key={c.name} className="mono">{fmt(row[c.name])}</td>)}</tr>)}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function SystemAdmin() {
  const queryClient = useQueryClient();
  const { data, isError, refetch, isFetching } = useStatus();
  const system = (data?.system ?? {}) as { movement_mode?: string; camera?: { api_base_url?: string } };
  const healthRows = Object.entries(data?.movement_health ?? {});

  const reconnect = () => {
    void refetch();
    void queryClient.invalidateQueries({ queryKey: ["movement-sync-status"] });
  };

  return (
    <div className="ops-page">
      <div className="ops-heading">
        <div>
          <h2>시스템</h2>
          <p>서버 연결 상태와 DB 탐색</p>
        </div>
        <Button variant="secondary" onClick={reconnect} disabled={isFetching}>
          {isFetching ? "조회 중…" : "재연결 시도"}
        </Button>
      </div>
      <div className="grid2 system-admin-grid">
        <div className="panel">
          <h2>서버 연결</h2>
          {isError ? <div className="inline-alert warn">상태 조회 실패</div> : null}
          <div className="rail-list">
            <div className="card"><strong>Main DB</strong><div><Pill status="ok" /> 연결</div></div>
            <div className="card">
              <strong>Movement client</strong>
              <div className="mono">{cell(system.movement_mode)}</div>
            </div>
            <div className="card">
              <strong>Camera API</strong>
              <div className="mono">{cell(system.camera?.api_base_url) || "unset"}</div>
            </div>
            {healthRows.map(([robot_id, health]) => (
              <div className="card" key={robot_id}>
                <strong>{robot_id}</strong>
                <div><Pill status={(health as { ok?: boolean }).ok ? "online" : "offline"} /></div>
                <div className="mono">{cell((health as { error?: string }).error)}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <h2>DB Tables</h2>
          <DbTablesPanel />
        </div>
      </div>
    </div>
  );
}
