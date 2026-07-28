# Agent Guide

상태: Active
소유: Engineering
작성: 2026-06-29 11:00 KST
최종 갱신: 2026-06-29 11:00 KST
목적: 코딩 에이전트가 Simulator 작업 시 읽을 문서·수정 범위·갱신 책임을 한곳에 고정한다.

## 필수 선독 (작업 전)

1. [AGENTS.md](../../AGENTS.md) — 레포 규칙·source of truth
2. [SIMULATOR.md](../as-built/SIMULATOR.md) — 현재 구현 사실
3. 작업 유형에 맞는 문서 (아래 표)

문서 정책: `nav2_REFECTOR/Policy/01_REPOSITORY_DOCUMENTATION_POLICY.md`
- 루트에 Markdown 추가 금지 (`README.md`, `AGENTS.md`만)
- 구현 사실 → `docs/as-built/` · 실행 절차 → `docs/runbook/` · 참조 → `docs/reference/`

## 작업 유형 → 문서·파일

| 사용자 요청 | 먼저 읽기 | 주로 수정 |
| --- | --- | --- |
| 시뮬 실행·RViz·AMCL | [RUN_HOST_NATIVE.md](../runbook/RUN_HOST_NATIVE.md), [CONFIG.md](CONFIG.md) | `scripts/`, `launch/`, `config/` |
| 새 맵·spawn pose | [CONFIG.md](CONFIG.md), [RUN_WITH_CUSTOM_MAP.md](../runbook/RUN_WITH_CUSTOM_MAP.md) | `maps/`, `config/profiles/` |
| world 생성·벽 | [SIMULATOR.md](../as-built/SIMULATOR.md), ADR world | `scripts/generate_warehouse_world.py` |
| Gazebo·lidar·bridge | [CONFIG.md](CONFIG.md), [PATHS.md](PATHS.md) | `config/`, `launch/warehouse_demo.launch.py` |
| Docker | [RUN_WITH_CUSTOM_MAP.md](../runbook/RUN_WITH_CUSTOM_MAP.md) | `docker-compose.yml`, `docker/` |
| Nav2·API 본체 | `nav2_REFECTOR` as-built | **Simulator 밖** — 원본 수정 금지 |
| 설계·로드맵 | [CUSTOM_MAP.md](../design/CUSTOM_MAP.md) | `docs/design/` only |

## 수정 금지·주의

- `nav2_REFECTOR` 원본 맵/코드 직접 수정 금지 → `maps/` 복사본 사용
- `MAP_NAME` 미지정 시 `robot1_map` 하위호환 유지
- `deps_ws/src/turtlebot3_simulations` — 가능하면 `config/`·launch로 해결; upstream 패치는 최소화
- 루트에 plan/handoff MD 생성 금지 → `worklog/`

## 표준 실행 (검증용)

호스트 RViz 스모크:

```bash
source /opt/ros/jazzy/setup.bash
SIM_PROFILE=sample bash scripts/launch_gazebo_rviz.sh
```

ROS 불필요 world 생성:

```bash
python3 scripts/generate_warehouse_world.py \
  --map-yaml maps/sample/map.yaml \
  --out-world worlds/_scratch_test.world
```

프로파일 로더:

```bash
python3 scripts/load_profile.py sample
```

문서 레이아웃:

```bash
bash scripts/check_docs.sh
```

## 구현 변경 후 갱신 체크리스트

| 변경 | 갱신 문서 |
| --- | --- |
| 프로세스·진입점·아키텍처 | `docs/as-built/SIMULATOR.md` |
| 실행 명령·장애 대응 | `docs/runbook/RUN_HOST_NATIVE.md` (또는 CUSTOM_MAP) |
| config·프로파일·env | `docs/reference/CONFIG.md`, `.env.example` |
| 새 스크립트 | `docs/reference/SCRIPTS.md` |
| 구조적 결정 | `docs/adr/YYYY-MM-DD-*.md` |
| 사용자 빠른 시작 | `README.md` (100줄 이내, 링크 위주) |
| 에이전트 규칙·SoT | `AGENTS.md` (링크만, 본문 비대화 금지) |

`design/`에 구현 완료 내용을 현재 사실처럼 남기지 말고 `as-built/`로 승격한다.

## 사용자에게 안내할 때

- **실행만** 원하면: README Quickstart + `SIM_PROFILE=sample bash scripts/launch_gazebo_rviz.sh`
- **새 맵**이면: `maps/<name>/` + `config/profiles/<name>.json` + [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) 시나리오 B
- **2D Pose 안 됨**이면: `/scan` 발행 여부 먼저 확인 → [CONFIG.md](CONFIG.md) headless lidar 절
- **Nav2 튜닝**이면: Simulator가 아니라 `turtlebot3_navigation2` / `nav2_REFECTOR` 안내

## 관련 링크

- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) — 사람 개발자 온보딩
- [SCRIPTS.md](SCRIPTS.md) — 스크립트 카탈로그
- [CONFIG.md](CONFIG.md) — 파라미터 참조
- [PATHS.md](PATHS.md) — 경로 해석 (`sim_paths.sh` / `sim_paths.py`)
