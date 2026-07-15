import { useState } from "react";
import { useStatus } from "../../hooks/useStatus";
import { useAdminMutations } from "../../hooks/useAdminData";
import { useCommLogs, useProbes } from "../../hooks/useCommLogs";
import { DataTable, type Column } from "../../components/DataTable";
import { Pill } from "../../components/Pill";
import { Panel } from "../../components/Panel";
import { Field } from "../../components/Field";
import { Button } from "../../components/Button";
import { ApiError } from "../../lib/api";
import { cell } from "../../lib/format";
import type { CommLog } from "../../hooks/useCommLogs";
import type { CameraSource, Robot } from "../../types";
import { MapGoto } from "../movement/MapGoto";

const EMPTY_ROBOT = { robot_id: "", display_name: "", status: "IDLE", enabled: true, battery: "" };
const EMPTY_CAMERA = { source_id: "", label: "", robot_id: "", status: "not_connected", stream_url: "" };

const logColumns: Column<CommLog>[] = [
  { header: "시각", cell: (r) => cell(r.finished_at || r.started_at) },
  { header: "service", cell: (r) => cell(r.service) },
  { header: "결과", cell: (r) => <><Pill status={r.ok ? "ok" : "error"} /> {cell(r.status)}</> },
  { header: "ms", className: "mono", cell: (r) => cell(r.elapsed_ms) },
  { header: "url", className: "mono", cell: (r) => cell(r.url) },
];

export function DevicesAdmin() {
  const { data } = useStatus();
  const { saveRobot, deleteRobot, saveCamera, deleteCamera } = useAdminMutations();
  const [robotForm, setRobotForm] = useState(EMPTY_ROBOT);
  const [cameraForm, setCameraForm] = useState(EMPTY_CAMERA);
  const [service, setService] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{ kind: "robot" | "camera"; id: string } | null>(null);
  const { data: commData } = useCommLogs(service, 80);
  const { probeMovement } = useProbes();

  const robots = data?.robots ?? [];
  const cameras = data?.camera_sources ?? [];
  const logs = commData?.logs ?? [];

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    }
  };

  const editRobot = (r: Robot) => setRobotForm({
    robot_id: r.robot_id,
    display_name: r.display_name,
    status: r.status,
    enabled: r.enabled,
    battery: r.battery == null ? "" : String(r.battery),
  });

  const editCamera = (c: CameraSource) => setCameraForm({
    source_id: c.source_id,
    label: c.label,
    robot_id: c.robot_id ?? "",
    status: c.status ?? "not_connected",
    stream_url: c.stream_url ?? "",
  });

  return (
    <div className="ops-page devices-admin">
      <div className="ops-heading">
        <div>
          <h2>로봇 · 카메라</h2>
          <p>장치 등록·점검과 통신 로그</p>
        </div>
        <Button variant="secondary" onClick={() => probeMovement.mutate()}>Movement probe</Button>
      </div>

      {error ? <div className="inline-alert warn">{error}</div> : null}

      <div className="grid2 devices-panels">
        <Panel title="로봇">
          <div className="form-grid compact">
            <Field label="robot_id">
              <input value={robotForm.robot_id} onChange={(e) => setRobotForm((f) => ({ ...f, robot_id: e.target.value }))} />
            </Field>
            <Field label="name">
              <input value={robotForm.display_name} onChange={(e) => setRobotForm((f) => ({ ...f, display_name: e.target.value }))} />
            </Field>
            <div className="action-row">
              <Button
                disabled={!robotForm.robot_id.trim() || saveRobot.isPending}
                onClick={() => run(async () => {
                  await saveRobot.mutateAsync({
                    robot_id: robotForm.robot_id.trim(),
                    display_name: robotForm.display_name.trim(),
                    status: robotForm.status.trim() || "IDLE",
                    enabled: robotForm.enabled,
                    battery: robotForm.battery ? Number(robotForm.battery) : null,
                  });
                  setRobotForm(EMPTY_ROBOT);
                })}
              >
                저장
              </Button>
            </div>
          </div>
          <div className="table-wrap clean-table">
            <table>
              <thead><tr><th>robot_id</th><th>이름</th><th>status</th><th>연결</th><th>운용</th><th></th></tr></thead>
              <tbody>
                {robots.length === 0 ? <tr><td colSpan={6} className="empty">로봇 없음</td></tr> :
                  robots.map((r) => (
                    <tr key={r.robot_id}>
                      <td className="mono">{r.robot_id}</td><td>{r.display_name}</td>
                      <td><Pill status={r.status} /></td>
                      <td>{!r.enabled ? "미운용" : data?.movement_health?.[r.robot_id]?.ok ? "온라인" : "오프라인"}</td>
                      <td>
                        <label className="operation-switch" title={r.enabled ? "작업 투입 대상" : "자동 배정·일반 이동 제외"}>
                          <input
                            type="checkbox"
                            aria-label={r.display_name + " 운용 사용"}
                            checked={r.enabled}
                            disabled={saveRobot.isPending}
                            onChange={(e) => run(() => saveRobot.mutateAsync({
                              robot_id: r.robot_id, display_name: r.display_name, status: r.status,
                              battery: r.battery ?? null, enabled: e.target.checked,
                            }))}
                          />
                          <span className="operation-switch-track" aria-hidden="true" />
                          <span>{r.enabled ? "사용" : "미운용"}</span>
                        </label>
                      </td>
                      <td>
                        <Button variant="row" onClick={() => editRobot(r)}>수정</Button>
                        {pendingDelete?.kind === "robot" && pendingDelete.id === r.robot_id ? (
                          <span className="delete-confirm">
                            <Button variant="danger" onClick={() => run(async () => {
                              await deleteRobot.mutateAsync(r.robot_id);
                              setPendingDelete(null);
                            })}>확인</Button>
                            <Button variant="secondary" onClick={() => setPendingDelete(null)}>취소</Button>
                          </span>
                        ) : (
                          <Button variant="row-danger" onClick={() => setPendingDelete({ kind: "robot", id: r.robot_id })}>삭제</Button>
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="카메라">
          <div className="form-grid compact">
            <Field label="source_id">
              <input value={cameraForm.source_id} onChange={(e) => setCameraForm((f) => ({ ...f, source_id: e.target.value }))} />
            </Field>
            <Field label="label">
              <input value={cameraForm.label} onChange={(e) => setCameraForm((f) => ({ ...f, label: e.target.value }))} />
            </Field>
            <div className="action-row">
              <Button
                disabled={!cameraForm.source_id.trim() || saveCamera.isPending}
                onClick={() => run(async () => {
                  await saveCamera.mutateAsync({
                    source_id: cameraForm.source_id.trim(),
                    label: cameraForm.label.trim(),
                    robot_id: cameraForm.robot_id.trim() || null,
                    status: cameraForm.status.trim() || "not_connected",
                    stream_url: cameraForm.stream_url.trim() || null,
                  });
                  setCameraForm(EMPTY_CAMERA);
                })}
              >
                저장
              </Button>
            </div>
          </div>
          <div className="table-wrap clean-table">
            <table>
              <thead><tr><th>source_id</th><th>label</th><th>robot</th><th></th></tr></thead>
              <tbody>
                {cameras.length === 0 ? <tr><td colSpan={4} className="empty">카메라 없음</td></tr> :
                  cameras.map((c) => (
                    <tr key={c.source_id}>
                      <td className="mono">{c.source_id}</td><td>{c.label}</td><td>{cell(c.robot_id)}</td>
                      <td>
                        <Button variant="row" onClick={() => editCamera(c)}>수정</Button>
                        {pendingDelete?.kind === "camera" && pendingDelete.id === c.source_id ? (
                          <span className="delete-confirm">
                            <Button variant="danger" onClick={() => run(async () => {
                              await deleteCamera.mutateAsync(c.source_id);
                              setPendingDelete(null);
                            })}>확인</Button>
                            <Button variant="secondary" onClick={() => setPendingDelete(null)}>취소</Button>
                          </span>
                        ) : (
                          <Button variant="row-danger" onClick={() => setPendingDelete({ kind: "camera", id: c.source_id })}>삭제</Button>
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <Panel title="통신 로그" className="devices-logs">
        <div className="toolbar">
          <input className="search" placeholder="service 필터" value={service} onChange={(e) => setService(e.target.value)} />
        </div>
        <DataTable columns={logColumns} rows={logs} getKey={(_, i) => i} emptyText="통신 로그 없음" />
      </Panel>


      <MapGoto robots={robots} />
    </div>
  );
}
