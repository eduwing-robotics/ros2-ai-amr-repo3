# Path Resolution Reference

상태: Active
소유: Engineering
작성: 2026-06-29 11:30 KST
최종 갱신: 2026-06-29 11:30 KST
목적: Simulator 레포 기준 경로·외부 의존 경로·Docker 컨테이너 경로 매핑을 단일 출처로 고정한다.

## 레포 내부 (상대 경로)

레포 루트를 `.` 또는 `SIMULATOR_ROOT`로 둔다.

| 경로 | 용도 |
| --- | --- |
| `maps/<name>/` | Nav2 맵 입력 |
| `config/profiles/` | 실행 프로파일 JSON |
| `config/` | Gazebo·bridge 설정 |
| `launch/` | ROS launch |
| `scripts/` | 실행·검증 스크립트 |
| `worlds/` | 생성 world (`generated_<map>.world`) |
| `deps_ws/` | (선택) `turtlebot3_gazebo` 소스 빌드 |

## 형제 레포 (Simulator 기준 상대)

| 상대 경로 | 용도 |
| --- | --- |
| `../WS/nav2_REFECTOR` | Nav2·Nav API 본체 (기본 탐색) |
| `../turtlebot3_ws` | `turtlebot3_navigation2` overlay (선택) |

탐색 순서는 `scripts/sim_paths.sh` · `scripts/sim_paths.py`에 정의.
명시 override: `NAV2_REFECTOR_ROOT`, `EXTRA_ROS_SETUP`, `SIMULATOR_ROOT`.

## 시스템 경로 (레포 밖, env로 override)

| 경로 | 용도 |
| --- | --- |
| `/opt/ros/${ROS_DISTRO}/setup.bash` | ROS distro (`ROS_SETUP`) |
| `$HOME/WS/nav2_REFECTOR` | nav2 폴백 (상대 경로 없을 때) |

## Docker 컨테이너 매핑

`docker-compose.yml` 볼륨 (호스트 → 컨테이너):

| 호스트 (compose 기준) | 컨테이너 |
| --- | --- |
| `.` | `/workspace/Simulator` (`SIMULATOR_ROOT`) |
| `../WS/nav2_REFECTOR` | `/workspace/nav2_REFECTOR` (`NAV2_REFECTOR_ROOT`) |

컨테이너 내 스크립트 호출:

```bash
docker compose exec sim bash "$SIMULATOR_ROOT/scripts/check_ros_topics.sh"
```

## 구현 위치

- Bash: `scripts/sim_paths.sh` — `sim_paths_init`, `resolve_nav2_refector_root`, `source_ros_stack`
- Python: `scripts/sim_paths.py` — `resolve_nav2_refector_root`, `default_robot1_map_yaml`

## 관련 문서

- [CONFIG.md](CONFIG.md) — 프로파일·파라미터
- [SCRIPTS.md](SCRIPTS.md) — 스크립트 카탈로그
- [../adr/2026-06-29-simulator-mount-strategy.md](../adr/2026-06-29-simulator-mount-strategy.md) — Docker 볼륨 결정
