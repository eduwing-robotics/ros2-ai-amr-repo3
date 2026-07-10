import { useMemo, useState } from "react";
import { useMaps } from "../../hooks/useScenarioData";
import {
  ALIGN_FINALS,
  buildRobotCommandRequest,
  defaultRobotCommandFormValues,
  DOCK_ACTIONS,
  ESTOP_OPS,
  getRobotCommand,
  MANUAL_COMMANDS,
  postRobotCommand,
  ROBOT_COMMAND_GATE_KINDS,
  ROBOT_COMMAND_KINDS,
  robotCommandGateHint,
  type AlignFinal,
  type DockAction,
  type EstopOp,
  type ManualCommand,
  type RobotCommandFormValues,
  type RobotCommandKind,
} from "../../lib/robotCommands";
import type { Robot } from "../../types";

function formatCommandError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (message.includes("movement_robot_commands_api_missing")) {
    return "Movement 서버가 POST /robot-commands 실행 API를 제공하지 않습니다. dock_transfer/aruco_align은 dry_run만 사용하고, Movement 서버 구현 후 실실행하세요.";
  }
  return message;
}

export function RobotCommandTestPanel({ robots }: { robots: Robot[] }) {
  const { data: maps = [] } = useMaps();
  const [robotId, setRobotId] = useState("");
  const [mapId, setMapId] = useState("");
  const [kind, setKind] = useState<RobotCommandKind>("move_to_point");
  const [dryRun, setDryRun] = useState(true);
  const [form, setForm] = useState<RobotCommandFormValues>(defaultRobotCommandFormValues);
  const [commandId, setCommandId] = useState("");
  const [result, setResult] = useState<string>("");
  const [pending, setPending] = useState(false);
  const [dockAdvanced, setDockAdvanced] = useState(false);

  const patchForm = (patch: Partial<RobotCommandFormValues>) => setForm((s) => ({ ...s, ...patch }));

  const activeMapId = mapId || maps[0]?.map_id || form.mapId;
  const selectedRobotId = robotId || robots[0]?.robot_id || "";
  const formWithMap = useMemo(() => ({ ...form, mapId: activeMapId }), [activeMapId, form]);

  const requestBody = useMemo(
    () => buildRobotCommandRequest(selectedRobotId, kind, dryRun, formWithMap),
    [dryRun, formWithMap, kind, selectedRobotId],
  );

  const runCommand = async () => {
    if (!selectedRobotId) {
      setResult("로봇을 선택하세요.");
      return;
    }
    setPending(true);
    try {
      if (!dryRun && !window.confirm(`${kind} 실실행을 전송합니다. 로봇 주변 안전과 Movement 서버 지원 상태를 확인했나요?`)) {
        setPending(false);
        return;
      }
      const r = await postRobotCommand(requestBody);
      setCommandId(r.command_id);
      setResult(JSON.stringify(r, null, 2));
    } catch (e) {
      setResult(`실패: ${formatCommandError(e)}`);
    } finally {
      setPending(false);
    }
  };

  const pollStatus = async () => {
    if (!selectedRobotId || !commandId) {
      setResult("robot과 command_id가 필요합니다.");
      return;
    }
    setPending(true);
    try {
      const r = await getRobotCommand(commandId, selectedRobotId);
      setResult(JSON.stringify(r, null, 2));
    } catch (e) {
      setResult(`조회 실패: ${(e as Error).message}`);
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="panel robot-command-test">
      <h2>명령 envelope 시험</h2>
      <p className="muted">`POST /robot-commands` 통합 명령 API. 공유 빌더(PHASE_49)로 JSON 본문을 조립하고, dry_run 기본으로 검증합니다.</p>
      <div className="fields compact-fields">
        <div className="field">
          <span className="chip">로봇</span>
          <select className="filter" value={selectedRobotId} onChange={(e) => setRobotId(e.target.value)}>
            <option value="">선택</option>
            {robots.map((r) => (
              <option key={r.robot_id} value={r.robot_id}>{r.robot_id}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <span className="chip">kind</span>
          <select className="filter" value={kind} onChange={(e) => setKind(e.target.value as RobotCommandKind)}>
            {ROBOT_COMMAND_KINDS.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <span className="chip">dry_run</span>
          <label className="switch-line">
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            검증만(실행 안 함)
          </label>
        </div>
        {kind === "move_to_point" ? (
          <>
            <div className="field">
              <span className="chip">map</span>
              <select className="filter" value={activeMapId} onChange={(e) => setMapId(e.target.value)}>
                {maps.map((m) => (
                  <option key={m.map_id} value={m.map_id}>{m.name}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <span className="chip">x,y,yaw</span>
              <input className="search mono" value={form.x} onChange={(e) => patchForm({ x: e.target.value })} placeholder="x" style={{ width: 72 }} />
              <input className="search mono" value={form.y} onChange={(e) => patchForm({ y: e.target.value })} placeholder="y" style={{ width: 72 }} />
              <input className="search mono" value={form.yaw} onChange={(e) => patchForm({ yaw: e.target.value })} placeholder="yaw" style={{ width: 72 }} />
            </div>
          </>
        ) : kind === "dock_transfer" ? (
          <>
            <div className="field">
              <span className="chip">aruco</span>
              <input className="search mono" type="number" min={1} value={form.arucoId} onChange={(e) => patchForm({ arucoId: e.target.value })} />
            </div>
            <div className="field">
              <span className="chip">action</span>
              <select className="filter" value={form.action} onChange={(e) => patchForm({ action: e.target.value as DockAction })}>
                {DOCK_ACTIONS.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <span className="chip">level</span>
              <input className="search mono" type="number" min={1} max={2} step={1} value={form.level} onChange={(e) => patchForm({ level: e.target.value })} />
            </div>
            <div className="field">
              <span className="chip">lift 고급</span>
              <label className="switch-line">
                <input type="checkbox" checked={dockAdvanced} onChange={(e) => setDockAdvanced(e.target.checked)} />
                override 필드
              </label>
            </div>
            {dockAdvanced ? (
              <>
                <div className="field">
                  <span className="chip">lift_height_mm</span>
                  <input className="search mono" type="number" min={0} step={1} placeholder="미지정" value={form.liftHeightMm} onChange={(e) => patchForm({ liftHeightMm: e.target.value })} />
                </div>
                <div className="field">
                  <span className="chip">lift_timeout_sec</span>
                  <input className="search mono" type="number" min={0} step={1} placeholder="미지정" value={form.liftTimeoutSec} onChange={(e) => patchForm({ liftTimeoutSec: e.target.value })} />
                </div>
                <div className="field">
                  <span className="chip">home_on_unload</span>
                  <label className="switch-line">
                    <input type="checkbox" checked={form.homeOnUnload} onChange={(e) => patchForm({ homeOnUnload: e.target.checked })} />
                    unload 시 홈 복귀
                  </label>
                </div>
              </>
            ) : null}
          </>
        ) : kind === "aruco_align" ? (
          <>
            <div className="field">
              <span className="chip">aruco</span>
              <input className="search mono" type="number" min={1} value={form.arucoId} onChange={(e) => patchForm({ arucoId: e.target.value })} />
            </div>
            <div className="field">
              <span className="chip">final</span>
              <select className="filter" value={form.final} onChange={(e) => patchForm({ final: e.target.value as AlignFinal })}>
                {ALIGN_FINALS.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <span className="chip">tolerance</span>
              <input className="search mono" type="number" step="0.01" min="0" value={form.xy} onChange={(e) => patchForm({ xy: e.target.value })} placeholder="xy_m" style={{ width: 90 }} />
              <input className="search mono" type="number" step="0.5" min="0" value={form.yawDeg} onChange={(e) => patchForm({ yawDeg: e.target.value })} placeholder="yaw_deg" style={{ width: 90 }} />
            </div>
          </>
        ) : kind === "manual_drive" ? (
          <>
            <div className="field">
              <span className="chip">command</span>
              <select className="filter" value={form.manualCommand} onChange={(e) => patchForm({ manualCommand: e.target.value as ManualCommand })}>
                {MANUAL_COMMANDS.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <span className="chip">hold</span>
              <label className="switch-line">
                <input type="checkbox" checked={form.hold} onChange={(e) => patchForm({ hold: e.target.checked })} />
                누르는 동안 유지
              </label>
            </div>
          </>
        ) : (
          <div className="field">
            <span className="chip">op</span>
            <select className="filter" value={form.estopOp} onChange={(e) => patchForm({ estopOp: e.target.value as EstopOp })}>
              {ESTOP_OPS.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </div>
        )}
        {ROBOT_COMMAND_GATE_KINDS.includes(kind) ? (
          <p className="muted" style={{ margin: "4px 0 0" }}>{robotCommandGateHint}</p>
        ) : null}
        {dryRun ? (
          <p className="muted" style={{ margin: "4px 0 0" }}>dry_run=true — 검증만 수행하며 로봇은 동작하지 않습니다.</p>
        ) : null}
        <div className="field">
          <span className="chip">command_id</span>
          <input className="search mono" value={commandId} onChange={(e) => setCommandId(e.target.value)} placeholder="응답 후 자동 채움" />
        </div>
      </div>
      <pre className="mono status-line" style={{ whiteSpace: "pre-wrap", maxHeight: 180, overflow: "auto" }}>
        {JSON.stringify(requestBody, null, 2)}
      </pre>
      <div className="btnbar">
        <button type="button" className="btn" disabled={pending} onClick={runCommand}>
          {pending ? "전송 중..." : dryRun ? "dry_run 검증" : "명령 전송"}
        </button>
        <button type="button" className="rowbtn" disabled={pending} onClick={pollStatus}>상태 조회</button>
      </div>
      {result ? <pre className="mono status-line" style={{ whiteSpace: "pre-wrap", maxHeight: 200, overflow: "auto" }}>{result}</pre> : null}
    </div>
  );
}
