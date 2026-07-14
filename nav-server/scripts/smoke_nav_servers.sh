#!/usr/bin/env bash
# Non-moving smoke checks scoped to robots selected by a resolved profile.
set -euo pipefail
RESOLVED_PROFILE_PATH="${SF_NAV_RESOLVED_PROFILE_PATH:-}"
if (($#)); then
  case "$1" in
    -h|--help) echo "Usage: SF_NAV_RESOLVED_PROFILE_PATH=... $0"; exit 0 ;;
    *) echo "[smoke_nav_servers] unknown argument: $1" >&2; exit 2 ;;
  esac
fi
[[ -f "$RESOLVED_PROFILE_PATH" ]] || { echo "[smoke_nav_servers] resolved runtime profile is required" >&2; exit 2; }
python3 - "$RESOLVED_PROFILE_PATH" <<'PY'
import json,sys,urllib.error,urllib.request
cfg=json.load(open(sys.argv[1],encoding='utf-8'))

def request(method,url,payload=None,expected=200):
    data=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'} if data else {},method=method)
    try:
        with urllib.request.urlopen(req,timeout=4) as response: status=response.status; body=response.read().decode()
    except urllib.error.HTTPError as exc: status=exc.code; body=exc.read().decode()
    if status!=expected: raise SystemExit(f'[smoke_nav_servers] FAIL {method} {url}: expected {expected}, got {status}, body={body}')
    return json.loads(body) if body else {}

for robot in cfg['robots']:
    rid=robot['robot_id']; domain=int(robot['nav_local_domain_id']); base=f"http://127.0.0.1:{robot['api_port']}"
    health=request('GET',f'{base}/movement-api/v1/health')
    active=health.get('active_robot_id',health.get('robot_id'))
    if active!=rid: raise SystemExit(f'[smoke_nav_servers] FAIL {base}: active robot={active}')
    if health.get('ros_domain_id') != int(robot['ros_domain_id']):
        raise SystemExit(f"[smoke_nav_servers] FAIL {base}: hardware domain={health.get('ros_domain_id')}")
    if health.get('process_ros_domain_id') != domain:
        raise SystemExit(f"[smoke_nav_servers] FAIL {base}: process domain={health.get('process_ros_domain_id')}")
    endpoints=request('GET',f'{base}/movement-api/v1/endpoints')
    advertised=endpoints.get('nav_api_url') or health.get('advertised_nav_api_url')
    if not advertised: raise SystemExit(f'[smoke_nav_servers] FAIL {base}: missing advertised endpoint contract')
    print(f'[smoke_nav_servers] PASS {rid}: {base}, domain={domain}')
PY
