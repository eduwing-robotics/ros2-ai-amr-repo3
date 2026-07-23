# Runtime Output Policy

상태: Active
분류: Reference
작성: 2026-06-27 00:00 KST
최종 갱신: 2026-07-23 KST
목적: `.runtime/`, 선별 로그, cache와 가상환경의 재생성·보존 규칙을 정의한다.

## 기본 위치

| 산출물 | 기본 경로 | 재생성 |
| --- | --- | --- |
| 관리형 stack 로그/PID/state | `.runtime/sf-nav/` | `sf_nav.sh` 재실행 시 새로 생성 |
| 선별 실험 로그 | `logs/`, `worklog/` | 운영자가 보존 여부 결정 |
| Python cache | `__pycache__/` | import 시 자동 생성 |
| 가상환경 | `.venv/` | `scripts/setup_nav_server_env.sh` |

## 보존 규칙

- 단순 cache, `.venv/`, 관리형 stack `.runtime/`과 자동 camera snapshot은 Git에 포함하지 않는다.
- 운영 증거로 보존할 로그·이미지는 `logs/`, `worklog/` 또는 root `deliverables/`로 선별 복사한 뒤 문맥과 결과를 함께 기록한다.
- `.env`, `.secrets`, 선별 로그·데이터는 ignore로 숨기지 않으므로 stage 전에 직접 검토한다.

## 운영 스크립트 분류

| 분류 | 예시 |
| --- | --- |
| start | `scripts/sf_nav.sh`, `scripts/start_nav_servers.sh` |
| plan/check | `scripts/run_nav_servers.sh --print-plan`, `scripts/run_nav_servers.sh --check` |
| status | `scripts/nav_server_status.sh`, `scripts/nav_ops.sh status` |
| smoke | `scripts/smoke_*.sh` |
| bridge | `scripts/run_domain_bridges.sh`, `scripts/smoke_domain_bridge.sh` |
| camera | `scripts/run_pi_camera_aruco.sh`, `scripts/aruco_detector_node.py` |
| verify | `scripts/check_all.sh`, `scripts/validate_*.py` |

## 개발 환경 재현

```bash
export NAV_SERVER_ROOT="<repo-root>/nav-server"
cd "$NAV_SERVER_ROOT"
scripts/setup_nav_server_env.sh
source .venv/bin/activate
cp .env.example .env
scripts/check_all.sh
```

SIMULATION_MODE smoke:

```bash
SIMULATION_MODE=1 scripts/start_nav_servers.sh dry-run
scripts/smoke_nav_servers.sh
```
