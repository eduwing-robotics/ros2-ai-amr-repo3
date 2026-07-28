# ADR: Simulator config/ 프로파일·런타임 설정 분리

상태: Active
소유: Engineering
작성: 2026-06-29 10:30 KST
최종 갱신: 2026-06-29 10:30 KST
목적: 맵·spawn·Gazebo 브리지 파라미터를 코드 밖으로 빼고 타 레포에서 재사용할 구조를 고정한다.

## 맥락

- 맵마다 spawn pose·initial pose가 다르다.
- Gazebo Sim headless에서 `gpu_lidar`·AMCL이 동작하려면 서버 config·브리지 QoS가 필요하다.
- 환경 변수만으로는 맵별 설정 묶음을 공유·버전 관리하기 어렵다.

## 결정

1. **`config/profiles/*.json`** — 맵별 실행 프로파일 (spawn, initial pose, GUI 플래그).
2. **`config/*.config` / `*.yaml`** — Gazebo·ros_gz_bridge 정적 설정 (레포 단일 출처).
3. **`scripts/load_profile.sh`** — JSON → shell `export` (stdlib만 사용, 외부 의존성 없음).
4. **`launch/warehouse_demo.launch.py`** — `bridge_config`, `gz_server_config` launch 인자로 오버라이드 허용.

프로파일은 **실행 파라미터**만 담고, Nav2 `burger.yaml` 등 Nav2 본체 파라미터는 `turtlebot3_navigation2`·`nav2_REFECTOR`에 둔다.

## 대안

| 대안 | 기각 이유 |
| --- | --- |
| 맵 폴더에 `profile.yaml` | 맵 입력과 실행 설정 혼재; Docker·다른 레포 참조 경로 복잡 |
| 환경 변수만 | 맵별 묶음 재현·문서화 어려움 |
| `deps_ws` 패키지 내 params | Simulator 래퍼 변경이 TB3 upstream에 결합 |

## 결과

- 새 맵: `maps/<name>/` + `config/profiles/<name>.json` 추가.
- 타 프로젝트: `SIMULATOR_ROOT` + `load_profile.sh`로 동일 env 재현.
- 센서/브리지 튜닝: `config/` 파일만 수정, launch 인자로 실험 가능.

참조: [../reference/CONFIG.md](../reference/CONFIG.md)
