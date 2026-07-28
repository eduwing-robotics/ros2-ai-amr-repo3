# Scripts Reference

상태: Active
소유: Engineering
작성: 2026-06-29 11:00 KST
최종 갱신: 2026-07-28 13:10 KST
목적: `scripts/` 진입점·입력·의존성을 빠르게 찾기 위한 카탈로그.

## 실행·오케스트레이션

| 스크립트 | 용도 | 주요 입력 |
| --- | --- | --- |
| `start_demo.sh` | Gazebo + Nav2 + Nav API | `MAP_NAME`, `WAREHOUSE_WORLD`, 프로파일 env |
| `launch_gazebo_rviz.sh` | Gazebo + Nav2 + RViz (+GUI) | `SIM_PROFILE` 또는 `MAP_NAME`, `INITIAL_*` |
| `load_profile.sh` | JSON 프로파일 → shell export | 인자: 프로파일명 (`sample`) |
| `load_profile.py` | 위와 동일 (stdout export) | `--root` 선택 |
| `pub_initialpose.sh` | sim time `/initialpose` | `x y yaw`, `INITIALPOSE_*_VARIANCE` |
| `start_dual_robot_standby.sh` | 2대 Gazebo/Nav2/API prepare·start·reset·status·stop | `GAZEBO_USE_XVFB`, `GAZEBO_GUI` |
| `run_dual_robot_safety_test.sh` | 20 cm 리셋 후 전체 안전 E2E | scenario timeout 인자 전달 |

## 생성·검증

| 스크립트 | 용도 | ROS 필요 |
| --- | --- | --- |
| `generate_warehouse_world.py` | map → world + zone model | 아니오 |
| `check_host_deps.sh` | 호스트 의존성 점검 | 아니오 |
| `check_docs.sh` | 문서 레이아웃 점검 | 아니오 |
| `check_ros_topics.sh` | `/scan`, `/odom`, `/tf` 등 | 예 |
| `check_api.sh` | Nav API health | 예 (API 기동 시) |
| `check_multi_api.sh` | 다중 API | 예 |
| `send_nav2_pose.sh` | Nav2 goal 전송 | 예 |
| `smoke_demo.sh` | 데모 스모크 | 예 |
| `smoke_lms_integration.sh` | LMS 연동 스모크 | 예 |
| `validate_phase3_config.py` | phase3 설정 검증 | 아니오 |
| `dual_robot_geometry.py` | 20/40 cm pose 계산·free-space 검증 | 아니오 |
| `generate_dual_robot_assets.py` | robot별 SDF/bridge/world line 생성 | 아니오 |
| `sim_standby_marker_oracle.py` | odom 기반 marker 20→40 cm 발행 | 예 |
| `run_dual_robot_safety_scenarios.py` | 트래픽·후진·충돌 assertion/JSON 증거 | API + ROS |
| `sim_collision_stop_probe.py` | collision monitor velocity gate 측정 | 예 |

## 권장 조합

**RViz 시각 확인**

```bash
SIM_PROFILE=sample bash scripts/launch_gazebo_rviz.sh
```

**Nav API E2E**

```bash
eval "$(bash scripts/load_profile.sh sample)"
bash scripts/start_demo.sh
bash scripts/check_ros_topics.sh && bash scripts/check_api.sh
```

**새 맵 world만 확인**

```bash
python3 scripts/generate_warehouse_world.py \
  --map-yaml maps/<name>/map.yaml \
  --out-world worlds/_scratch_<name>.world
```

## 환경 변수 (공통)

스크립트가 읽는 대표 env는 [CONFIG.md](CONFIG.md) 및 `.env.example` 참고.

| 변수 | 영향 받는 스크립트 |
| --- | --- |
| `SIMULATOR_ROOT` | 대부분 (자동 설정) |
| `NAV2_REFECTOR_ROOT` | `start_demo.sh` |
| `SIM_PROFILE` | `launch_gazebo_rviz.sh` |
| `MAP_NAME` / `MAP_YAML` | `start_demo`, `launch_gazebo_rviz` |
| `ROS_DOMAIN_ID` | 전체 ROS 스택 |

## 관련 문서

- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) — 시나리오별 사용법
- [RUN_HOST_NATIVE.md](../runbook/RUN_HOST_NATIVE.md) — 상세 실행 절차
