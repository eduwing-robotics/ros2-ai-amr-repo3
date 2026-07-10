import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Panel } from "../../components/Panel";
import { Button } from "../../components/Button";
import { SchemaForm } from "../../components/SchemaForm";
import { SmartParamInput, smartParamKind } from "../../components/SmartParamInput";
import { apiRoot } from "../../lib/api";
import { presetsFor } from "../../lib/apiPresets";
import {
  loadApiHistory,
  loadAutoGetExecute,
  pushApiHistory,
  recentCommandIds,
  saveAutoGetExecute,
  toCurl,
  toFetchSnippet,
  type ApiHistoryEntry,
} from "../../lib/apiConsoleHistory";
import {
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  CHANNEL_LABEL,
  DANGER_RE,
  exampleFor,
  parseApiOps,
  type ApiCategory,
  type ApiOp,
} from "../../lib/apiConsoleMeta";
import { validateRequired, type OpenApiDoc } from "../../lib/openApiForm";
import {
  ALIGN_FINALS,
  buildRobotCommandRequest,
  defaultRobotCommandFormValues,
  DOCK_ACTIONS,
  ESTOP_OPS,
  MANUAL_COMMANDS,
  ROBOT_COMMAND_GATE_KINDS,
  ROBOT_COMMAND_KINDS,
  robotCommandGateHint,
  type AlignFinal,
  type RobotCommandFormValues,
  type RobotCommandKind,
} from "../../lib/robotCommands";
import { useMaps, useRobots } from "../../hooks/useScenarioData";

type BodyMode = "form" | "raw";
interface RespState { status: number; ok: boolean; ms: number; body: string }

export function ApiConsole() {
  const { data: doc, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["openapi"],
    queryFn: async () => {
      const res = await fetch(`${apiRoot()}/openapi.json`);
      if (!res.ok) throw new Error(`openapi.json HTTP ${res.status}`);
      return (await res.json()) as OpenApiDoc;
    },
    staleTime: 5 * 60_000,
  });

  const { data: robots = [] } = useRobots();
  const { data: maps = [] } = useMaps();
  const robotIds = useMemo(() => robots.map((r) => r.robot_id), [robots]);
  const mapIds = useMemo(() => maps.map((m) => m.map_id), [maps]);

  const ops = useMemo(() => (doc ? parseApiOps(doc) : []), [doc]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<ApiCategory>("all");
  const [selId, setSelId] = useState<string | null>(null);
  const sel = useMemo(() => ops.find((o) => o.id === selId) ?? null, [ops, selId]);

  const filtered = useMemo(() => {
    const n = query.trim().toLowerCase();
    return ops.filter((o) => {
      if (category !== "all" && o.category !== category) return false;
      if (!n) return true;
      return (
        o.path.toLowerCase().includes(n) ||
        o.summary.toLowerCase().includes(n) ||
        o.description.toLowerCase().includes(n) ||
        o.tag.toLowerCase().includes(n) ||
        CATEGORY_LABEL[o.category].toLowerCase().includes(n) ||
        o.method.includes(n)
      );
    });
  }, [category, ops, query]);

  const categoryCounts = useMemo(() => {
    const counts = new Map<ApiCategory, number>([["all", ops.length]]);
    for (const c of CATEGORY_ORDER) counts.set(c, 0);
    for (const o of ops) counts.set(o.category, (counts.get(o.category) ?? 0) + 1);
    return counts;
  }, [ops]);

  const grouped = useMemo(() => {
    const m = new Map<Exclude<ApiCategory, "all">, ApiOp[]>();
    for (const o of filtered) {
      const arr = m.get(o.category) ?? [];
      arr.push(o);
      m.set(o.category, arr);
    }
    return CATEGORY_ORDER.flatMap((c) => {
      const list = m.get(c);
      return list?.length ? [[c, list] as const] : [];
    });
  }, [filtered]);

  const [pathVals, setPathVals] = useState<Record<string, string>>({});
  const [queryVals, setQueryVals] = useState<Record<string, string>>({});
  const [bodyText, setBodyText] = useState("");
  const [bodyMode, setBodyMode] = useState<BodyMode>("form");
  const [formBody, setFormBody] = useState<unknown>({});
  const [rcForm, setRcForm] = useState<RobotCommandFormValues>(defaultRobotCommandFormValues);
  const [rcRobotId, setRcRobotId] = useState("tb3_1");
  const [rcKind, setRcKind] = useState<RobotCommandKind>("aruco_align");
  const [rcDryRun, setRcDryRun] = useState(true);
  const [rcDockAdvanced, setRcDockAdvanced] = useState(false);
  const [resp, setResp] = useState<RespState | null>(null);
  const [sending, setSending] = useState(false);
  const [armed, setArmed] = useState(false);
  const [history, setHistory] = useState<ApiHistoryEntry[]>(() => loadApiHistory());
  const [autoGetExecute, setAutoGetExecute] = useState(() => loadAutoGetExecute());
  const [lastRequest, setLastRequest] = useState<{ method: string; url: string; body?: string } | null>(null);
  const armTimer = useRef<number | null>(null);
  const commandIdOptions = useMemo(() => recentCommandIds(history), [history]);

  const patchRcForm = (patch: Partial<RobotCommandFormValues>) => setRcForm((s) => ({ ...s, ...patch }));

  useEffect(() => {
    if (!sel || !doc) return;
    setPathVals(Object.fromEntries(sel.params.filter((p) => p.in === "path").map((p) => [p.name, ""])));
    setQueryVals(Object.fromEntries(sel.params.filter((p) => p.in === "query").map((p) => [p.name, ""])));
    const example = sel.bodySchema ? exampleFor(sel.bodySchema, doc) : null;
    setFormBody(example ?? {});
    setBodyText(example != null ? JSON.stringify(example, null, 2) : "");
    setBodyMode(sel.bodySchema ? "form" : "raw");
    setResp(null);
    setArmed(false);
    if (DANGER_RE.test(sel.path)) setRcDryRun(true);
  }, [sel, doc]);

  const pathParams = useMemo(
    () => sel?.params.filter((param) => param.in === "path") ?? [],
    [sel],
  );
  const queryParams = sel?.params.filter((p) => p.in === "query") ?? [];
  const isWrite = sel ? sel.method !== "get" : false;
  const isDanger = sel ? DANGER_RE.test(sel.path) : false;
  const isRobotCommandsBody = sel?.method === "post" && sel.path === "/api/v1/robot-commands";
  const endpointPresets = sel ? presetsFor(sel.method, sel.path) : [];

  const robotCommandBody = useMemo(
    () => buildRobotCommandRequest(rcRobotId, rcKind, rcDryRun, rcForm),
    [rcDryRun, rcForm, rcKind, rcRobotId],
  );

  const livePreview = useMemo(() => {
    if (isRobotCommandsBody) return robotCommandBody;
    if (bodyMode === "form" && sel?.bodySchema) return formBody;
    try {
      return bodyText.trim() ? JSON.parse(bodyText) : null;
    } catch {
      return null;
    }
  }, [bodyMode, bodyText, formBody, isRobotCommandsBody, robotCommandBody, sel?.bodySchema]);

  const applyFormToText = useCallback(() => {
    const payload = isRobotCommandsBody ? robotCommandBody : formBody;
    setBodyText(JSON.stringify(payload, null, 2));
  }, [formBody, isRobotCommandsBody, robotCommandBody]);

  const applyPreset = (presetId: string) => {
    const preset = endpointPresets.find((p) => p.id === presetId);
    if (!preset || !doc) return;
    if (preset.dangerous && !window.confirm(`"${preset.label}" 예시를 채웁니다. 위험 API일 수 있습니다. 계속할까요?`)) return;
    if (preset.pathParams) setPathVals((s) => ({ ...s, ...preset.pathParams }));
    if (preset.queryParams) setQueryVals((s) => ({ ...s, ...preset.queryParams }));
    setFormBody(preset.body);
    setBodyText(JSON.stringify(preset.body, null, 2));
    setBodyMode("form");
  };

  const buildUrl = useCallback((op: ApiOp): string => {
    let p = op.path;
    for (const [k, v] of Object.entries(pathVals)) p = p.replace(`{${k}}`, encodeURIComponent(v));
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(queryVals)) if (v !== "") qs.append(k, v);
    const q = qs.toString();
    return `${apiRoot()}${p}${q ? `?${q}` : ""}`;
  }, [pathVals, queryVals]);

  const doSend = useCallback(async (op: ApiOp, skipValidation = false) => {
    for (const p of op.params.filter((x) => x.in === "path")) {
      if (!pathVals[p.name]) {
        alert(`경로 파라미터 "${p.name}" 를 입력하세요.`);
        return;
      }
    }

    let body: string | undefined;
    if (op.bodySchema) {
      if (bodyMode === "form" || (op.method === "post" && op.path === "/api/v1/robot-commands")) {
        const payload = op.path === "/api/v1/robot-commands" ? robotCommandBody : formBody;
        if (!skipValidation && op.bodySchema) {
          const errs = validateRequired(op.bodySchema, payload, doc!);
          if (errs.length) {
            alert(`본문 검증:\n${errs.slice(0, 6).join("\n")}`);
            return;
          }
        }
        body = JSON.stringify(payload);
      } else if (bodyText.trim()) {
        try {
          JSON.parse(bodyText);
          body = bodyText;
        } catch {
          setResp({ status: 0, ok: false, ms: 0, body: "요청 본문 JSON 파싱 오류 — 형식을 확인하세요." });
          return;
        }
      }
    }

    const url = buildUrl(op);
    setSending(true);
    setResp(null);
    setLastRequest({ method: op.method, url, body });
    const t0 = performance.now();
    try {
      const res = await fetch(url, {
        method: op.method.toUpperCase(),
        headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
        body,
      });
      const text = await res.text();
      let pretty = text;
      try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch { /* 비 JSON */ }
      const ms = Math.round(performance.now() - t0);
      setResp({ status: res.status, ok: res.ok, ms, body: pretty || "(빈 응답)" });
      setHistory(pushApiHistory({
        method: op.method.toUpperCase(),
        path: op.path,
        url,
        status: res.status,
        ms,
        at: new Date().toISOString(),
        body,
      }));
    } catch (e) {
      const ms = Math.round(performance.now() - t0);
      setResp({ status: 0, ok: false, ms, body: `네트워크 오류: ${(e as Error).message}` });
    } finally {
      setSending(false);
      setArmed(false);
    }
  }, [bodyMode, bodyText, buildUrl, doc, formBody, pathVals, robotCommandBody]);

  const onSendClick = (op: ApiOp) => {
    if (isWrite && !armed) {
      setArmed(true);
      if (armTimer.current) window.clearTimeout(armTimer.current);
      armTimer.current = window.setTimeout(() => setArmed(false), 4000);
      return;
    }
    void doSend(op);
  };

  const replayHistory = (entry: ApiHistoryEntry) => {
    const op = ops.find((o) => o.method === entry.method.toLowerCase() && o.path === entry.path);
    if (!op) {
      alert("현재 OpenAPI 목록에 해당 엔드포인트가 없습니다.");
      return;
    }
    setSelId(op.id);
    setTimeout(() => {
      if (entry.body) {
        setBodyText(entry.body);
        try { setFormBody(JSON.parse(entry.body)); } catch { /* raw only */ }
        setBodyMode("raw");
      }
      void doSend(op, true);
    }, 0);
  };

  useEffect(() => {
    if (!sel || !autoGetExecute || sel.method !== "get") return;
    const ready = pathParams.every((p) => !p.required || pathVals[p.name]);
    if (!ready) return;
    const t = window.setTimeout(() => void doSend(sel, true), 120);
    return () => window.clearTimeout(t);
  }, [autoGetExecute, doSend, pathParams, pathVals, sel]);

  const paramOptions = (name: string): string[] => {
    const kind = smartParamKind(name);
    if (kind === "robot") return robotIds;
    if (kind === "map") return mapIds;
    if (kind === "command") return commandIdOptions;
    return [];
  };

  const renderParamInput = (p: { name: string; schema?: { type?: string } }, value: string, onChange: (v: string) => void) => {
    const opts = paramOptions(p.name);
    if (smartParamKind(p.name) && opts.length) {
      return <SmartParamInput name={p.name} value={value} onChange={onChange} options={opts} placeholder={p.schema?.type || "string"} />;
    }
    return (
      <input
        className="search mono"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={p.schema?.type || "string"}
      />
    );
  };

  return (
    <Panel title="개발자 · API 콘솔" className="api-console-panel">
      <div className="inline-alert warn" style={{ marginBottom: 10 }}>
        실제 백엔드로 송신됩니다. 쓰기(POST·DELETE 등) 호출은 확인 단계를 거치며, 미션·ESTOP·로봇 커맨드는 실장비를 움직일 수 있습니다.
        {isDanger ? " 위험 엔드포인트는 dry_run 기본·확인 가드를 권장합니다." : ""}
      </div>
      <div className="api-console-toolbar">
        <label className="api-toolbar-check">
          <input
            type="checkbox"
            checked={autoGetExecute}
            onChange={(e) => {
              setAutoGetExecute(e.target.checked);
              saveAutoGetExecute(e.target.checked);
            }}
          />
          GET 선택 시 자동 실행
        </label>
      </div>
      {isLoading ? <p className="muted">OpenAPI 스키마 불러오는 중…</p> : null}
      {isError ? (
        <div className="inline-alert err">
          스키마 로드 실패: {(error as Error)?.message}. dev에서는 vite 프록시(/openapi.json)가 필요합니다.
          <div className="action-row" style={{ marginTop: 8 }}><Button variant="secondary" onClick={() => refetch()}>재시도</Button></div>
        </div>
      ) : null}

      {doc ? (
        <div className="api-console">
          <aside className="api-list">
            <input className="search" placeholder={`검색 (${ops.length}개)`} value={query} onChange={(e) => setQuery(e.target.value)} />
            <div className="api-category-tabs" role="tablist" aria-label="API 카테고리">
              {["all", ...CATEGORY_ORDER].map((c) => (
                <button
                  key={c}
                  type="button"
                  className={category === c ? "active" : ""}
                  onClick={() => setCategory(c as ApiCategory)}
                >
                  {CATEGORY_LABEL[c as ApiCategory]} <span>{categoryCounts.get(c as ApiCategory) ?? 0}</span>
                </button>
              ))}
            </div>
            <div className="api-list-scroll">
              {grouped.length === 0 ? <p className="muted">결과 없음</p> : grouped.map(([cat, list]) => (
                <div key={cat} className="api-group">
                  <div className="api-group-head">{CATEGORY_LABEL[cat]} <span className="muted">({list.length})</span></div>
                  {list.map((o) => (
                    <button key={o.id} type="button" className={`api-item${o.id === selId ? " active" : ""}`} onClick={() => setSelId(o.id)} title={o.description || o.summary}>
                      <span className="api-item-top">
                        <span className={`api-method m-${o.method}`}>{o.method.toUpperCase()}</span>
                        <span className="api-item-path mono">{o.path}</span>
                        <span className={`api-category c-${o.category}`}>{CATEGORY_LABEL[o.category]}</span>
                        {o.channel ? <span className={`api-channel ${o.channel}`}>{o.channel === "proxy" ? "프록시" : "콜백"}</span> : null}
                      </span>
                      {o.description ? <span className="api-item-desc">{o.description}</span> : null}
                    </button>
                  ))}
                </div>
              ))}
            </div>
            {history.length > 0 ? (
              <div className="api-history">
                <div className="section-kicker">최근 요청</div>
                <div className="api-history-scroll">
                  {history.slice(0, 8).map((h) => (
                    <button key={h.id} type="button" className="api-history-item" onClick={() => replayHistory(h)}>
                      <span className={`pill ${h.status >= 200 && h.status < 300 ? "ok" : "err"}`}>{h.status || "ERR"}</span>
                      <span className="mono">{h.method} {h.path}</span>
                      <span className="muted">{h.ms}ms</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </aside>

          <section className="api-detail">
            {!sel ? <p className="muted">좌측에서 엔드포인트를 선택하세요.</p> : (
              <>
                <div className="api-detail-head">
                  <span className={`api-method m-${sel.method}`}>{sel.method.toUpperCase()}</span>
                  <code className="mono api-detail-path">{sel.path}</code>
                  <span className={`api-category c-${sel.category}`}>{CATEGORY_LABEL[sel.category]}</span>
                  {sel.channel ? <span className={`api-channel ${sel.channel}`}>{sel.channel === "proxy" ? "프록시" : "콜백"}</span> : null}
                </div>
                {sel.channel ? <p className="muted" style={{ marginTop: 6 }}>{CHANNEL_LABEL[sel.channel]}</p> : null}
                {sel.description || sel.summary ? <p className="api-detail-desc">{sel.description || sel.summary}</p> : null}
                {isDanger ? <div className="inline-alert err" style={{ marginTop: 8 }}>⚠ 실장비·운영에 영향을 줄 수 있는 엔드포인트입니다.</div> : null}

                {endpointPresets.length > 0 ? (
                  <div className="api-presets">
                    <div className="section-kicker">예시 프리셋</div>
                    <div className="api-preset-row">
                      {endpointPresets.map((p) => (
                        <Button key={p.id} variant="secondary" onClick={() => applyPreset(p.id)}>{p.label}</Button>
                      ))}
                    </div>
                  </div>
                ) : null}

                {pathParams.length > 0 ? (
                  <div className="api-params">
                    <div className="section-kicker">경로 파라미터</div>
                    {pathParams.map((p) => (
                      <label key={p.name} className="api-param-row">
                        <span className="mono">{p.name}{p.required ? " *" : ""}</span>
                        {renderParamInput(p, pathVals[p.name] ?? "", (v) => setPathVals((s) => ({ ...s, [p.name]: v })))}
                      </label>
                    ))}
                  </div>
                ) : null}

                {queryParams.length > 0 ? (
                  <div className="api-params">
                    <div className="section-kicker">쿼리 파라미터</div>
                    {queryParams.map((p) => (
                      <label key={p.name} className="api-param-row">
                        <span className="mono">{p.name}{p.required ? " *" : ""}</span>
                        {renderParamInput(p, queryVals[p.name] ?? "", (v) => setQueryVals((s) => ({ ...s, [p.name]: v })))}
                      </label>
                    ))}
                  </div>
                ) : null}

                {sel.bodySchema ? (
                  <div className="api-params">
                    <div className="api-body-mode">
                      <div className="section-kicker">요청 본문</div>
                      <div className="api-mode-tabs">
                        <button type="button" className={bodyMode === "form" ? "active" : ""} onClick={() => setBodyMode("form")}>폼</button>
                        <button type="button" className={bodyMode === "raw" ? "active" : ""} onClick={() => setBodyMode("raw")}>raw JSON</button>
                      </div>
                    </div>

                    {bodyMode === "form" ? (
                      <>
                        {isRobotCommandsBody ? (
                          <div className="api-body-helper">
                            <div className="api-helper-head">
                              <strong>robot-commands 프리셋</strong>
                            </div>
                            <div className="api-helper-grid">
                              <label><span>robot_id</span>
                                {robotIds.length ? (
                                  <select className="filter" value={rcRobotId} onChange={(e) => setRcRobotId(e.target.value)}>
                                    {robotIds.map((id) => <option key={id} value={id}>{id}</option>)}
                                  </select>
                                ) : (
                                  <input className="search mono" value={rcRobotId} onChange={(e) => setRcRobotId(e.target.value)} />
                                )}
                              </label>
                              <label><span>kind</span>
                                <select className="filter" value={rcKind} onChange={(e) => setRcKind(e.target.value as RobotCommandKind)}>
                                  {ROBOT_COMMAND_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
                                </select>
                              </label>
                              <label className="api-helper-check"><span>dry_run</span><input type="checkbox" checked={rcDryRun} onChange={(e) => setRcDryRun(e.target.checked)} /></label>
                              {rcKind === "move_to_point" ? (
                                <>
                                  <label><span>map_id</span>
                                    {mapIds.length ? (
                                      <select className="filter" value={rcForm.mapId} onChange={(e) => patchRcForm({ mapId: e.target.value })}>
                                        {mapIds.map((id) => <option key={id} value={id}>{id}</option>)}
                                      </select>
                                    ) : (
                                      <input className="search mono" value={rcForm.mapId} onChange={(e) => patchRcForm({ mapId: e.target.value })} />
                                    )}
                                  </label>
                                  <label><span>x</span><input className="search mono" value={rcForm.x} onChange={(e) => patchRcForm({ x: e.target.value })} /></label>
                                  <label><span>y</span><input className="search mono" value={rcForm.y} onChange={(e) => patchRcForm({ y: e.target.value })} /></label>
                                  <label><span>yaw</span><input className="search mono" value={rcForm.yaw} onChange={(e) => patchRcForm({ yaw: e.target.value })} /></label>
                                </>
                              ) : null}
                              {rcKind === "dock_transfer" ? (
                                <>
                                  <label><span>aruco</span><input className="search mono" type="number" min="1" value={rcForm.arucoId} onChange={(e) => patchRcForm({ arucoId: e.target.value })} /></label>
                                  <label><span>action</span>
                                    <select className="filter" value={rcForm.action} onChange={(e) => patchRcForm({ action: e.target.value })}>
                                      {DOCK_ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
                                    </select>
                                  </label>
                                  <label><span>level</span><input className="search mono" type="number" min="1" max="2" value={rcForm.level} onChange={(e) => patchRcForm({ level: e.target.value })} /></label>
                                  <label className="api-helper-check">
                                    <span>lift 고급</span>
                                    <input type="checkbox" checked={rcDockAdvanced} onChange={(e) => setRcDockAdvanced(e.target.checked)} />
                                  </label>
                                  {rcDockAdvanced ? (
                                    <>
                                      <label><span>lift_height_mm</span><input className="search mono" type="number" min="0" step="1" placeholder="미지정" value={rcForm.liftHeightMm} onChange={(e) => patchRcForm({ liftHeightMm: e.target.value })} /></label>
                                      <label><span>lift_timeout_sec</span><input className="search mono" type="number" min="0" step="1" placeholder="미지정" value={rcForm.liftTimeoutSec} onChange={(e) => patchRcForm({ liftTimeoutSec: e.target.value })} /></label>
                                      <label className="api-helper-check"><span>home_on_unload</span><input type="checkbox" checked={rcForm.homeOnUnload} onChange={(e) => patchRcForm({ homeOnUnload: e.target.checked })} /></label>
                                    </>
                                  ) : null}
                                </>
                              ) : null}
                              {ROBOT_COMMAND_GATE_KINDS.includes(rcKind) ? (
                                <p className="muted" style={{ gridColumn: "1 / -1", margin: 0 }}>{robotCommandGateHint}</p>
                              ) : null}
                              {rcDryRun ? (
                                <p className="muted" style={{ gridColumn: "1 / -1", margin: 0 }}>dry_run=true — 검증만 수행하며 로봇은 동작하지 않습니다.</p>
                              ) : null}
                              {rcKind === "aruco_align" ? (
                                <>
                                  <label><span>aruco</span><input className="search mono" type="number" min="1" value={rcForm.arucoId} onChange={(e) => patchRcForm({ arucoId: e.target.value })} /></label>
                                  <label><span>final</span>
                                    <select className="filter" value={rcForm.final} onChange={(e) => patchRcForm({ final: e.target.value as AlignFinal })}>
                                      {ALIGN_FINALS.map((f) => <option key={f} value={f}>{f}</option>)}
                                    </select>
                                  </label>
                                  <label><span>xy_m</span><input className="search mono" type="number" step="0.01" min="0" value={rcForm.xy} onChange={(e) => patchRcForm({ xy: e.target.value })} /></label>
                                  <label><span>yaw_deg</span><input className="search mono" type="number" step="0.5" min="0" value={rcForm.yawDeg} onChange={(e) => patchRcForm({ yawDeg: e.target.value })} /></label>
                                </>
                              ) : null}
                              {rcKind === "manual_drive" ? (
                                <>
                                  <label><span>command</span>
                                    <select className="filter" value={rcForm.manualCommand} onChange={(e) => patchRcForm({ manualCommand: e.target.value })}>
                                      {MANUAL_COMMANDS.map((c) => <option key={c} value={c}>{c}</option>)}
                                    </select>
                                  </label>
                                  <label className="api-helper-check"><span>hold</span><input type="checkbox" checked={rcForm.hold} onChange={(e) => patchRcForm({ hold: e.target.checked })} /></label>
                                </>
                              ) : null}
                              {rcKind === "estop" ? (
                                <label><span>op</span>
                                  <select className="filter" value={rcForm.estopOp} onChange={(e) => patchRcForm({ estopOp: e.target.value })}>
                                    {ESTOP_OPS.map((o) => <option key={o} value={o}>{o}</option>)}
                                  </select>
                                </label>
                              ) : null}
                            </div>
                          </div>
                        ) : (
                          <SchemaForm schema={sel.bodySchema} doc={doc} value={formBody} onChange={setFormBody} />
                        )}
                      </>
                    ) : (
                      <textarea className="mono api-body" spellCheck={false} value={bodyText} onChange={(e) => setBodyText(e.target.value)} rows={12} />
                    )}

                    <div className="api-preview-row">
                      <Button variant="secondary" onClick={applyFormToText}>JSON에 반영</Button>
                      <pre className="mono api-helper-preview">{JSON.stringify(livePreview, null, 2)}</pre>
                    </div>
                  </div>
                ) : null}

                <div className="action-row" style={{ marginTop: 10 }}>
                  <Button variant={armed ? "danger" : "primary"} onClick={() => onSendClick(sel)} disabled={sending}>
                    {sending ? "전송 중…" : armed ? "확인: 전송" : "전송"}
                  </Button>
                  {armed ? <Button variant="secondary" onClick={() => setArmed(false)}>취소</Button> : null}
                  <span className="muted mono">{buildUrl(sel)}</span>
                </div>

                {resp ? (
                  <div className="api-resp">
                    <div className="api-resp-head">
                      <span className={`pill ${resp.ok ? "ok" : "err"}`}>{resp.status || "ERR"}</span>
                      <span className="muted">{resp.ms} ms</span>
                      <button type="button" className="rowbtn" onClick={() => navigator.clipboard?.writeText(resp.body)}>응답 복사</button>
                      {lastRequest ? (
                        <>
                          <button type="button" className="rowbtn" onClick={() => navigator.clipboard?.writeText(toCurl(lastRequest.method, lastRequest.url, lastRequest.body))}>curl</button>
                          <button type="button" className="rowbtn" onClick={() => navigator.clipboard?.writeText(toFetchSnippet(lastRequest.method, lastRequest.url, lastRequest.body))}>fetch</button>
                        </>
                      ) : null}
                    </div>
                    <pre className="api-resp-body mono">{resp.body}</pre>
                  </div>
                ) : null}
              </>
            )}
          </section>
        </div>
      ) : null}
    </Panel>
  );
}
