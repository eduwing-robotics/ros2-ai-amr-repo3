# Runtime Output Policy

상태: Active
분류: Runbook
작성: 2026-06-27 00:00 KST
최종 갱신: 2026-06-27 14:43 KST
목적: `logs/`, `tmp/`, cache, PID 산출물의 위치와 보존 규칙을 정의한다.

## 기본 위치

| 산출물 | 기본 경로 | 재생성 |
| --- | --- | --- |
| Nav server 로그/PID | `logs/` | 서버 재시작 시 새로 생성 |
| 임시 프레임/검증 산출물 | `tmp/` | 재실행 가능 |
| Python cache | `__pycache__/` | import 시 자동 생성 |
| 가상환경 | `venv/` | `python3 -m venv venv` |

## 보존 규칙

- 단순 cache와 `venv/`는 Git에 포함하지 않는다 (`.gitignore` 참고).
- 운영 증거로 보존할 오래된 로그·이미지·pid는 `LEGACY/runtime/`로 이동하고 `LEGACY/README.md`에 기록한다.
- 보존 스냅샷: `LEGACY/runtime/` (`LEGACY/README.md` 이동 기록)
- 활성 `logs/`, `tmp/`는 서버·스크립트 재실행 시 재생성

## 운영 스크립트 분류

| 분류 | 예시 |
| --- | --- |
| start | `scripts/start_nav_servers.sh`, `scripts/run_nav_servers.sh` |
| status | `scripts/nav_server_status.sh`, `scripts/nav_ops.sh status` |
| smoke | `scripts/smoke_*.sh` |
| bridge | `scripts/run_domain_bridges.sh`, `scripts/smoke_domain_bridge.sh` |
| camera | `scripts/run_pi_camera_aruco.sh`, `scripts/aruco_detector_node.py` |
| verify | `scripts/check_all.sh`, `scripts/validate_*.py` |

## 개발 환경 재현

```bash
export NAV_SERVER_ROOT="<repo-root>/nav-server"
cd "$NAV_SERVER_ROOT"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt  # if present
cp .env.example .env
scripts/check_all.sh
```

SIMULATION_MODE smoke:

```bash
SIMULATION_MODE=1 scripts/start_nav_servers.sh dry-run
scripts/smoke_nav_servers.sh
```
