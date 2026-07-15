#!/usr/bin/env bash
# Profile-first Nav runtime operator surface.
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
# shellcheck source=/dev/null
source "$REPO_ROOT/scripts/lib/site_credentials.sh"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PROFILE_HELPER="${SF_NAV_PROFILE_HELPER:-$ROOT/nav_app/config/runtime_profiles.py}"
MANIFEST="${SF_NAV_MANIFEST:-$ROOT/config/runtime_profiles/manifest.json}"
ROBOTS_CONFIG_PATH="${ROBOTS_CONFIG_PATH:-$ROOT/config/robots.json}"
STATE_ROOT="${SF_NAV_STATE_DIR:-$ROOT/.runtime/sf-nav}"
RUN_SCRIPT="${SF_NAV_RUN_SCRIPT:-$SCRIPT_DIR/run_nav_servers.sh}"
profile="" command=""
STARTUP_COMMITTED=1
STARTUP_STATE=""
STARTUP_PID=""
STARTUP_PGID=""
STARTUP_TOKEN=""
STARTUP_TICKS=""
STARTUP_LOCKED=0
FOREGROUND_REQUESTED=0

usage() { cat <<'TXT'
Usage: scripts/sf_nav.sh [--profile PROFILE] COMMAND
Commands: profiles, print-config, check, up, foreground, status, smoke, logs, down
Selection precedence: --profile > SF_NAV_PROFILE > manifest default (tb1-live).
TXT
}
while (($#)); do
  case "$1" in
    --profile) profile="${2:?--profile requires a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) [[ -z "$command" ]] || { echo "[sf_nav] unexpected argument: $1" >&2; exit 2; }; command="$1"; shift ;;
  esac
done
[[ -n "$command" ]] || { usage >&2; exit 2; }
resolver_args=(--manifest "$MANIFEST" --robots "$ROBOTS_CONFIG_PATH")
[[ -z "$profile" ]] || resolver_args+=(--profile "$profile")
resolve_stdout() { "$PYTHON_BIN" "$PROFILE_HELPER" "${resolver_args[@]}"; }
json_field() { "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }
selected_profile() { resolve_stdout | json_field profile_id; }
latest_file() { echo "$STATE_ROOT/$1/latest"; }
latest_run_dir() { local f; f="$(latest_file "$1")"; [[ -f "$f" ]] || return 1; cat "$f"; }
state_value() { "$PYTHON_BIN" - "$1" "$2" <<'PY'
import json,sys
v=json.load(open(sys.argv[1],encoding='utf-8'))
for k in sys.argv[2].split('.'): v=v[k]
print(v)
PY
}
boot_id() { cat /proc/sys/kernel/random/boot_id; }
process_start_ticks() { awk '{print $22}' "/proc/$1/stat" 2>/dev/null; }
process_alive() { [[ -r "/proc/$1/stat" ]] && [[ "$(awk '{print $3}' "/proc/$1/stat" 2>/dev/null)" != Z ]] && kill -0 "$1" 2>/dev/null; }
process_token_matches() { tr '\0' '\n' <"/proc/$1/environ" 2>/dev/null | grep -Fqx "SF_NAV_OWNERSHIP_TOKEN=$2"; }

atomic_write_text() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
import os,sys,tempfile
from pathlib import Path
path=Path(sys.argv[1]); path.parent.mkdir(parents=True,exist_ok=True)
fd,name=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
try:
    with os.fdopen(fd,'w',encoding='utf-8') as stream:
        stream.write(sys.argv[2]); stream.flush(); os.fsync(stream.fileno())
    os.replace(name,path)
    directory=os.open(path.parent,os.O_RDONLY)
    try: os.fsync(directory)
    finally: os.close(directory)
finally:
    try: os.unlink(name)
    except FileNotFoundError: pass
PY
}

write_initial_state() {
  "$PYTHON_BIN" - "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" <<'PY'
import json,sys,os,tempfile
path,config_path,run_id,token,started,pid,pgid,ticks=sys.argv[1:]
cfg=json.load(open(config_path,encoding='utf-8'))
components={}
for name,spec in cfg['components'].items():
    item={"ownership":spec['ownership'],"required":spec['required'],"readiness_probe":spec['readiness_probe'],"status":"external-observe-only" if spec['ownership']=='external' else "starting"}
    if name=='movement_api' and spec['ownership']=='managed-script':
        item.update(pid=int(pid),process_group=int(pgid),process_start_ticks=ticks,identity="run_nav_servers.sh",status="starting")
    components[name]=item
data={"schema_version":1,"run_id":run_id,"profile_id":cfg['profile_id'],"ownership_token":token,"status":"starting","started_at":started,"boot_id":open('/proc/sys/kernel/random/boot_id').read().strip(),"selected_resources":cfg['selected_resources'],"components":components}
directory=os.path.dirname(path); fd,tmp=tempfile.mkstemp(prefix='.runtime-state.',dir=directory)
with os.fdopen(fd,'w',encoding='utf-8') as stream:
    json.dump(data,stream,indent=2,sort_keys=True); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
os.replace(tmp,path)
PY
}
update_state() {
  "$PYTHON_BIN" - "$1" "$2" "${3:-}" <<'PY'
import json,sys,datetime,os,tempfile
path,status,detail=sys.argv[1:]
d=json.load(open(path,encoding='utf-8')); d['status']=status
for component in d['components'].values():
    if component['ownership']=='managed-script': component['status']=status
if status in {'stopped','failed'}: d['stopped_at']=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
if detail: d['detail']=detail
fd,tmp=tempfile.mkstemp(prefix='.runtime-state.',dir=os.path.dirname(path))
with os.fdopen(fd,'w',encoding='utf-8') as stream:
    json.dump(d,stream,indent=2,sort_keys=True); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
os.replace(tmp,path)
PY
}
record_stop_result() {
  "$PYTHON_BIN" - "$1" "$2" "$3" "$4" "$5" <<'PY'
import json,sys,datetime,os,tempfile
path,status,term_sent,kill_sent,exited=sys.argv[1:]
d=json.load(open(path,encoding='utf-8')); d['status']=status
for component in d['components'].values():
    if component['ownership']=='managed-script': component['status']=status
d['stop_result']={"term_sent":term_sent=='1',"kill_sent":kill_sent=='1',"exited":exited=='1'}
if exited=='1': d['stopped_at']=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
fd,tmp=tempfile.mkstemp(prefix='.runtime-state.',dir=os.path.dirname(path))
with os.fdopen(fd,'w',encoding='utf-8') as stream:
    json.dump(d,stream,indent=2,sort_keys=True); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
os.replace(tmp,path)
PY
}
record_service_identities() {
  "$PYTHON_BIN" - "$1" "$2" "$3" <<'PY'
import json,sys,os,tempfile
state_path,service_path,child_path=sys.argv[1:]
data=json.load(open(state_path,encoding='utf-8'))
data['components']['movement_api']['service_identities']=json.load(open(service_path,encoding='utf-8'))['services']
if os.path.isfile(child_path): data['components']['movement_api']['managed_children']=json.load(open(child_path,encoding='utf-8'))['children']
fd,tmp=tempfile.mkstemp(prefix='.runtime-state.',dir=os.path.dirname(state_path))
with os.fdopen(fd,'w',encoding='utf-8') as stream:
    json.dump(data,stream,indent=2,sort_keys=True); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
os.replace(tmp,state_path)
PY
}
verify_identity() {
  local state="$1" pid pgid expected_pgid expected_boot expected_ticks token
  pid="$(state_value "$state" components.movement_api.pid)"; pgid="$(state_value "$state" components.movement_api.process_group)"
  expected_boot="$(state_value "$state" boot_id)"; expected_ticks="$(state_value "$state" components.movement_api.process_start_ticks)"; token="$(state_value "$state" ownership_token)"
  process_alive "$pid" || return 2
  expected_pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
  [[ -n "$token" && "$expected_boot" == "$(boot_id)" && "$expected_ticks" == "$(process_start_ticks "$pid")" && "$expected_pgid" == "$pgid" ]] || return 1
  process_token_matches "$pid" "$token" || return 1
}
stop_owned_process() {
  local state="$1" pid pgid term=0 killed=0 exited=0
  pid="$(state_value "$state" components.movement_api.pid)"; pgid="$(state_value "$state" components.movement_api.process_group)"
  if verify_identity "$state"; then
    if kill -TERM -- "-$pgid" 2>/dev/null; then term=1; fi
    for _ in $(seq 1 "${SF_NAV_STOP_TERM_POLLS:-50}"); do process_alive "$pid" || break; sleep 0.1; done
    if process_alive "$pid"; then if kill -KILL -- "-$pgid" 2>/dev/null; then killed=1; fi; fi
    for _ in $(seq 1 20); do process_alive "$pid" || break; sleep 0.05; done
    process_alive "$pid" || exited=1
  else
    local rc=$?; [[ "$rc" == 2 ]] && exited=1 || return 3
  fi
  if [[ "$exited" == 1 ]]; then record_stop_result "$state" stopped "$term" "$killed" 1; return 0; fi
  record_stop_result "$state" stop_failed "$term" "$killed" 0; return 1
}

refuse_if_resource_conflict() {
  local config="$1" state overlap
  for state in "$STATE_ROOT"/*/*/runtime-state.json; do
    [[ -f "$state" ]] || continue
    verify_identity "$state" || continue
    overlap="$($PYTHON_BIN - "$config" "$state" <<'PY'
import json,sys
requested=json.load(open(sys.argv[1],encoding='utf-8'))['selected_resources']
active=json.load(open(sys.argv[2],encoding='utf-8')).get('selected_resources',{})
labels=[]
for key in ('robot_ids','api_ports','hardware_ros_domain_ids','nav_local_ros_domain_ids'):
    shared=set(requested.get(key,())) & set(active.get(key,()))
    if shared: labels.append(f"{key}={','.join(map(str,sorted(shared,key=str)))}")
print(';'.join(labels))
PY
)"
    if [[ -n "$overlap" ]]; then
      echo "[sf_nav] refusing up: resources overlap active profile=$(state_value "$state" profile_id) ($overlap)" >&2
      return 1
    fi
  done
}
wait_external_readiness() {
  local config="$1" base_info base_node_pattern expected_bridge_node
  "$PYTHON_BIN" - "$config" <<'PY' | while IFS=$'\t' read -r component probe domain port bridge_robot_id; do
import json,sys
cfg=json.load(open(sys.argv[1],encoding='utf-8'))
for name,spec in cfg['components'].items():
    if spec['enabled'] and spec['required'] and spec['ownership']=='external':
        selected=set(spec.get('robot_ids') or [robot['robot_id'] for robot in cfg['robots']])
        for robot in cfg['robots']:
            if robot['robot_id'] in selected:
                print(f"{name}\t{spec['readiness_probe']}\t{robot['nav_local_domain_id']}\t{robot['api_port']}\t{robot.get('bridge_robot_id', '')}")
PY
    case "$probe" in
      base-heartbeat)
        base_info="$(ROS_DOMAIN_ID="$domain" timeout 3 ros2 topic info /cmd_vel --verbose 2>/dev/null)"
        base_node_pattern="${SF_NAV_BASE_NODE_PATTERN:-turtlebot3_node|diff_drive_controller|base_controller}"
        expected_bridge_node="${bridge_robot_id}_hardware_nav_${domain}"
        grep -Eq 'Subscription count: [1-9][0-9]*' <<<"$base_info" &&
          grep -Eiq "Node name: (${base_node_pattern}|${expected_bridge_node})[[:space:]]*$" <<<"$base_info"
        ;;
      ros-domain-route) ROS_DOMAIN_ID="$domain" timeout 2 ros2 topic list 2>/dev/null | grep -Eq '^/(scan|odom)$' ;;
      lifecycle-active) ROS_DOMAIN_ID="$domain" timeout 3 ros2 lifecycle get /bt_navigator 2>/dev/null | grep -qi active ;;
      lift-topics)
        "$PYTHON_BIN" - "$port" <<'PY'
import json,sys,urllib.request
with urllib.request.urlopen(f"http://127.0.0.1:{int(sys.argv[1])}/movement-api/v1/health",timeout=2) as response:
    health=json.load(response)
lift=health.get('lift')
if not isinstance(lift,dict) or lift.get('ready') is not True:
    raise SystemExit(f"lift health is not ready: {lift}")
PY
        ;;
      *) echo "[sf_nav] no required external readiness implementation for component=$component probe=$probe" >&2; return 1 ;;
    esac || { echo "[sf_nav] required readiness failed: component=$component domain=$domain" >&2; return 1; }
  done
}
wait_readiness() {
  local config="$1" pid="$2" pgid="$3" identities="$4" timeout="${SF_NAV_READINESS_TIMEOUT_SEC:-20}" mode="${SF_NAV_READINESS_MODE:-full}"
  [[ "$mode" == process-only ]] && { process_alive "$pid"; return; }
  if [[ "$mode" != external-only ]]; then
    "$PYTHON_BIN" - "$config" "$timeout" "$pgid" "$identities" <<'PY' || return 1
import json,os,sys,tempfile,time,urllib.request
from pathlib import Path
cfg=json.load(open(sys.argv[1],encoding='utf-8')); deadline=time.monotonic()+float(sys.argv[2]); expected_pgid=int(sys.argv[3]); output=Path(sys.argv[4]); pending=list(cfg['robots']); services={}

def owners(port):
    inodes=set()
    for table in ('/proc/net/tcp','/proc/net/tcp6'):
        try: lines=open(table,encoding='utf-8').read().splitlines()[1:]
        except OSError: continue
        for line in lines:
            parts=line.split()
            if parts[3]=='0A' and int(parts[1].rsplit(':',1)[1],16)==port: inodes.add(parts[9])
    result=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit(): continue
        try:
            if os.getpgid(int(proc.name)) != expected_pgid: continue
            for fd in (proc/'fd').iterdir():
                if os.readlink(fd).removeprefix('socket:[').removesuffix(']') in inodes:
                    result.append(int(proc.name)); break
        except (FileNotFoundError,PermissionError,ProcessLookupError,OSError): continue
    return sorted(set(result))

while pending and time.monotonic()<deadline:
    rest=[]
    for robot in pending:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{robot['api_port']}/movement-api/v1/health",timeout=.3) as r:
                body=json.load(r)
                active=body.get('active_robot_id',body.get('robot_id'))
                owned=owners(int(robot['api_port']))
                if r.status != 200 or active != robot['robot_id'] or not owned: rest.append(robot)
                else: services[robot['robot_id']]={'api_port':int(robot['api_port']),'pids':owned,'process_group':expected_pgid}
        except Exception: rest.append(robot)
    pending=rest
    if pending: time.sleep(.1)
if pending: raise SystemExit('required movement_api readiness failed: '+','.join(r['robot_id'] for r in pending))
output.parent.mkdir(parents=True,exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix=f'.{output.name}.',dir=output.parent)
with os.fdopen(fd,'w',encoding='utf-8') as stream:
    json.dump({'schema_version':1,'services':services},stream,indent=2,sort_keys=True); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
os.replace(tmp,output)
PY
  fi
  if [[ "$mode" =~ ^(full|external-only)$ ]]; then
    wait_external_readiness "$config" || return 1
  fi
  return 0
}

release_startup_lock() {
  if [[ "$STARTUP_LOCKED" == 1 ]]; then
    flock -u 9 2>/dev/null || true
    exec 9>&-
    STARTUP_LOCKED=0
  fi
}

stop_raw_startup_process() {
  [[ -n "$STARTUP_PID" && -n "$STARTUP_PGID" && -n "$STARTUP_TOKEN" && -n "$STARTUP_TICKS" ]] || return 0
  process_alive "$STARTUP_PID" || return 0
  [[ "$(process_start_ticks "$STARTUP_PID")" == "$STARTUP_TICKS" ]] || return 1
  [[ "$(ps -o pgid= -p "$STARTUP_PID" 2>/dev/null | tr -d ' ')" == "$STARTUP_PGID" ]] || return 1
  process_token_matches "$STARTUP_PID" "$STARTUP_TOKEN" || return 1
  kill -TERM -- "-$STARTUP_PGID" 2>/dev/null || true
  for _ in $(seq 1 "${SF_NAV_STOP_TERM_POLLS:-50}"); do process_alive "$STARTUP_PID" || return 0; sleep 0.1; done
  kill -KILL -- "-$STARTUP_PGID" 2>/dev/null || true
  for _ in $(seq 1 20); do process_alive "$STARTUP_PID" || return 0; sleep 0.05; done
  return 1
}

rollback_startup() {
  local rc=$?
  trap - EXIT INT TERM
  if [[ "$STARTUP_COMMITTED" != 1 ]]; then
    if [[ -n "$STARTUP_STATE" && -f "$STARTUP_STATE" ]]; then
      if stop_owned_process "$STARTUP_STATE" >/dev/null 2>&1; then
        if [[ "$FOREGROUND_REQUESTED" == 1 ]]; then
          update_state "$STARTUP_STATE" stopped "foreground interrupted during attach (exit=$rc)" || true
        else
          update_state "$STARTUP_STATE" failed "startup rollback (exit=$rc)" || true
        fi
      fi
    else
      stop_raw_startup_process >/dev/null 2>&1 || true
    fi
  fi
  release_startup_lock
  return "$rc"
}

do_up() {
  local config profile_id execution_class run_id run_dir config_path state_path log_path token pid pgid started ticks identities_path child_path
  local simulation_mode="${SIMULATION_MODE:-0}" dry_run_mission="${DRY_RUN_MISSION:-0}"
  if [[ "$RUN_SCRIPT" == "$SCRIPT_DIR/run_nav_servers.sh" ]]; then
    sf_load_site_credentials "$REPO_ROOT"
  fi
  config="$(resolve_stdout)"; profile_id="$(printf '%s' "$config"|json_field profile_id)"; execution_class="$(printf '%s' "$config"|json_field execution_class)"
  [[ "$execution_class" != synthetic_hil || "${SF_NAV_ALLOW_SYNTHETIC_HIL:-}" == 1 ]] || { echo "[sf_nav] refusing synthetic HIL without explicit SF_NAV_ALLOW_SYNTHETIC_HIL=1" >&2; return 1; }
  [[ "$execution_class" != synthetic_hil ]] || { simulation_mode=0; dry_run_mission=0; }
  mkdir -p "$STATE_ROOT"
  exec 9>"$STATE_ROOT/.startup.lock"
  flock -n 9 || { echo "[sf_nav] refusing up: another profile startup is in progress" >&2; return 1; }
  STARTUP_LOCKED=1
  run_id="${SF_NAV_RUN_ID_OVERRIDE:-$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM}"
  [[ "$run_id" =~ ^[A-Za-z0-9_.-]+$ && "$run_id" != .* ]] || { echo "[sf_nav] invalid run id" >&2; return 1; }
  run_dir="$STATE_ROOT/$profile_id/$run_id"; config_path="$run_dir/resolved-profile.json"; state_path="$run_dir/runtime-state.json"; log_path="$run_dir/runtime.log"
  identities_path="$run_dir/service-identities.json"; child_path="$run_dir/managed-children.json"
  token="$($PYTHON_BIN -c 'import secrets;print(secrets.token_hex(16))')"; started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$run_dir"; atomic_write_text "$config_path" "$config"$'\n'
  refuse_if_resource_conflict "$config_path"
  STARTUP_COMMITTED=0; STARTUP_STATE="$state_path"
  trap rollback_startup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  setsid env SIMULATION_MODE="$simulation_mode" DRY_RUN_MISSION="$dry_run_mission" SF_NAV_RESOLVED_PROFILE_PATH="$config_path" SF_NAV_MANIFEST_PATH="$MANIFEST" SF_NAV_ROBOTS_PATH="$ROBOTS_CONFIG_PATH" SF_NAV_RUNTIME_STATE_PATH="$state_path" SF_NAV_CHILD_STATE_PATH="$child_path" SF_NAV_RUN_ID="$run_id" SF_NAV_OWNERSHIP_TOKEN="$token" RUN_SCRIPT="$RUN_SCRIPT" bash -c 'source "$RUN_SCRIPT"; sf_nav_supervise' >"$log_path" 2>&1 </dev/null 9>&- &
  pid=$!; pgid=$pid; STARTUP_PID="$pid"; STARTUP_PGID="$pgid"; STARTUP_TOKEN="$token"
  sleep 0.01; ticks="$(process_start_ticks "$pid" || true)"; STARTUP_TICKS="$ticks"
  [[ "${SF_NAV_FAIL_AFTER_SPAWN:-0}" != 1 ]] || { echo "[sf_nav] injected failure after spawn" >&2; return 1; }
  write_initial_state "$state_path" "$config_path" "$run_id" "$token" "$started" "$pid" "$pgid" "$ticks"
  atomic_write_text "$(latest_file "$profile_id")" "$run_dir"$'\n'
  sleep "${SF_NAV_START_SETTLE_SEC:-0.2}"; process_alive "$pid" || { tail -80 "$log_path" >&2||true; return 1; }
  if ! wait_readiness "$config_path" "$pid" "$pgid" "$identities_path" 2>>"$log_path"; then tail -20 "$log_path" >&2||true; return 1; fi
  [[ ! -f "$identities_path" ]] || record_service_identities "$state_path" "$identities_path" "$child_path"
  if [[ "$FOREGROUND_REQUESTED" == 1 ]]; then
    update_state "$state_path" running
    release_startup_lock
    echo "[sf_nav] started profile=$profile_id run_id=$run_id pid=$pid"
    return
  else
    STARTUP_COMMITTED=1
    trap - EXIT INT TERM
  fi
  update_state "$state_path" running
  release_startup_lock
  echo "[sf_nav] started profile=$profile_id run_id=$run_id pid=$pid"
}

do_down() {
  local profile_id run_dir state status
  profile_id="$(selected_profile)"; run_dir="$(latest_run_dir "$profile_id")" || { echo "[sf_nav] no recorded run for profile=$profile_id"; return; }
  state="$run_dir/runtime-state.json"; status="$(state_value "$state" status)"
  [[ "$status" != stopped ]] || { echo "[sf_nav] profile=$profile_id already stopped"; return; }
  if stop_owned_process "$state"; then
    :
  else
    local rc=$?
    [[ "$rc" != 3 ]] || { echo "[sf_nav] refusing stop: ownership identity mismatch" >&2; return 1; }
    echo "[sf_nav] failed to stop owned process" >&2; return 1
  fi
  echo "[sf_nav] stopped profile=$profile_id run_id=$(state_value "$state" run_id)"
}

do_foreground() {
  local profile_id run_dir state pid rc
  FOREGROUND_REQUESTED=1
  do_up
  trap 'foreground_signal INT' INT
  trap 'foreground_signal TERM' TERM
  STARTUP_COMMITTED=1
  trap - EXIT
  profile_id="$(selected_profile)"
  run_dir="$(latest_run_dir "$profile_id")"
  state="$run_dir/runtime-state.json"
  pid="$(state_value "$state" components.movement_api.pid)"
  echo "[sf_nav] foreground attached profile=$profile_id; Ctrl+C stops the owned process group"
  if wait "$pid"; then rc=0; else rc=$?; fi
  trap - INT TERM
  stop_owned_process "$state" >/dev/null 2>&1 || true
  return "$rc"
}

foreground_signal() {
  local signal_name="$1" exit_code=143
  [[ "$signal_name" != INT ]] || exit_code=130
  trap - INT TERM
  do_down
  exit "$exit_code"
}

do_status() {
  local profile_id run_dir state observed=stopped stored
  profile_id="$(selected_profile)"; run_dir="$(latest_run_dir "$profile_id")" || { echo "[sf_nav] profile=$profile_id has no recorded run"; return; }; state="$run_dir/runtime-state.json"
  stored="$(state_value "$state" status)"
  if verify_identity "$state"; then
    [[ "$stored" =~ ^(starting|running)$ ]] && observed=running || observed=degraded
  fi
  "$PYTHON_BIN" - "$state" "$observed" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8')); d['observed_status']=sys.argv[2]; print(json.dumps(d,indent=2,sort_keys=True))
PY
}
case "$command" in
  profiles) "$PYTHON_BIN" "$PROFILE_HELPER" --manifest "$MANIFEST" --list ;;
  print-config) resolve_stdout ;;
  check) sf_load_site_credentials "$REPO_ROOT"; tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT; resolve_stdout>"$tmp"; SF_NAV_RESOLVED_PROFILE_PATH="$tmp" "$RUN_SCRIPT" --resolved-profile "$tmp" --check ;;
  up) do_up ;;
  foreground) do_foreground ;;
  status) do_status ;;
  smoke)
    profile_id="$(selected_profile)"; run_dir="$(latest_run_dir "$profile_id")" || { echo "[sf_nav] no recorded run for profile=$profile_id" >&2; exit 1; }
    state="$run_dir/runtime-state.json"
    if [[ "$(state_value "$state" status)" != running ]] || ! verify_identity "$state"; then
      echo "[sf_nav] smoke requires a running owned profile" >&2
      exit 1
    fi
    pid="$(state_value "$state" components.movement_api.pid)"; pgid="$(state_value "$state" components.movement_api.process_group)"
    smoke_identities="$run_dir/smoke-identities.json"
    SF_NAV_READINESS_MODE=http wait_readiness "$run_dir/resolved-profile.json" "$pid" "$pgid" "$smoke_identities"
    rm -f "$smoke_identities"
    SF_NAV_RESOLVED_PROFILE_PATH="$run_dir/resolved-profile.json" "$SCRIPT_DIR/smoke_nav_servers.sh"
    ;;
  logs) profile_id="$(selected_profile)"; run_dir="$(latest_run_dir "$profile_id")" || { echo "[sf_nav] no recorded run for profile=$profile_id" >&2; exit 1; }; cat "$run_dir/runtime.log" ;;
  down) do_down ;;
  *) echo "[sf_nav] unknown command: $command" >&2; usage >&2; exit 2 ;;
esac
