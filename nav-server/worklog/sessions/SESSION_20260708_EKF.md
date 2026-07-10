# 세션 정리 2026-07-08 (tb3_2 / EKF 실험)

## 스냅샷 (복원 지점)

| 이름 | 용도 | 복원 |
|------|------|------|
| `baseline_pre_ekf_20260708` | EKF 적용 **전** | `scripts/restore_nav_stack_snapshot.sh baseline_pre_ekf_20260708` |
| `post_ekf_20260708` | 오늘 작업 **후** (EKF+reverse 수정 포함) | `scripts/restore_nav_stack_snapshot.sh post_ekf_20260708` |

EKF 끄고 예전처럼: `WITH_EKF=0 scripts/start_all_tb3_2.sh restart`

---

## 오늘 적용한 것

### 1. robot_localization EKF
- `config/robot_localization/ekf_tb3_burger.yaml`
- `launch/ekf_odom.launch.py`
- `config/nav2/burger_smartfactory_ekf.yaml` (velocity_smoother → `/odometry/filtered`)
- `config/robot_sbc/tb3_ekf_bringup_overlay.yaml`
- `WITH_EKF=1 scripts/start_all_tb3_2.sh` 로 기동

### 2. 리프트
- `config/robots.json` tb3_2 `command_scale: 1.282` (logical 50mm → cmd ~64.1)
- `lift_client.py`: firmware/logical position 둘 다 인정 (`_at_target_mm`)

### 3. insert 후진 버그 수정 (중요)
- **문제**: `reverse_out`이 `leave_dock` no-op → 슬롯 안에서 후진 없이 Nav2만 회전
- **수정**: `reverse_out` → `slot_reverse_out` (dock_transfer와 동일 거리 후진)
- 시나리오: insert 구역이면 `reverse_out` + `aruco_marker_id` 선행

### 4. 스크립트
- `scripts/save_nav_stack_snapshot.sh` / `restore_nav_stack_snapshot.sh`
- `scripts/run_inbound2_b_lv2_scenario.sh` — nav 재시도, reverse_out, lift HOME preflight
- `scripts/run_ekf_zone_approach_insert_test.sh` — 구역별 approach+insert (신규)

---

## vision insert 픽셀 (zones.json, 변경 없음)

| 구역 | 마커 | stop_px | cap_m |
|------|------|---------|-------|
| 입고2 | #1 | 135 | 0.40 |
| 입고1 | #0 | 135 | 0.40 |
| A | #7 | 180 | 0.385 |
| B | #8 | 180 | 0.375 |
| C | #10 | 160 | 0.395 |
| D | #9 | 148 | 0.385 |
| 대기1 | #3 | 142 | 0.30 |
| 대기2 | #4 | 132 | 0.32 |

실측: stop 시 보통 **+1~5px** 과전진. B는 vision 실패 시 cap까지 전진(박음).

---

## EKF 구역 테스트 (중단 시점) — ` /tmp/ekf_zone_insert_live.log `

| 구역 | 결과 |
|------|------|
| inbound2 | **OK** (reverse_out ~8s 후 dock 완료) |
| inbound1 | **OK** |
| outbound1 | FAIL (dock) |
| outbound2 | FAIL (dock) |
| warehouse A | FAIL (nav) |
| warehouse B | 진행 중 중단 |

---

## 내일 이어서

1. **nav_server 재시작** (코드 반영 후 필수):
   ```bash
   pkill -f "uvicorn nav_server:app --host 0.0.0.0 --port 8002"
   cd ~/slam_nav_ws/scripts && ROBOT_ID=tb3_burger_02 ROS_DOMAIN_ID=5 \
     ACTIVE_MAP_YAML=../map/robot2_map.yaml \
     python3 -m uvicorn nav_server:app --host 0.0.0.0 --port 8002
   ```
2. 스택: `WITH_EKF=1 scripts/start_all_tb3_2.sh restart` (또는 이미 떠 있으면 status)
3. 구역 테스트 재개:
   ```bash
   ZONES="outbound1,outbound2,a,b,c,d,wait1,wait2" \
     bash scripts/run_ekf_zone_approach_insert_test.sh
   ```
4. 전체 시나리오: `bash scripts/run_inbound2_b_lv2_scenario.sh`
5. **선택**: B `insert_stop_width_px` 180→175 (과전진 완화)
6. lift_bridge SBC 재시작 if position 피드백 이상

---

## 로그 위치

- `/tmp/ekf_zone_insert_live.log` — 구역 테스트
- `/tmp/in2b2_*.log` — 시나리오 run들
- `worklog/insert_snapshots/` — insert vision 스냅샷 (txt/jpg)
- `/tmp/nav_server_8002.log` — movement API
