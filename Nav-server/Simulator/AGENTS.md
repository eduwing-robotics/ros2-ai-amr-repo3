# Agent Rules

상태: Active
소유: Engineering
작성: 2026-06-29 09:10 KST
최종 갱신: 2026-06-29 11:00 KST
목적: Simulator 레포에서 에이전트가 따라야 할 규칙과 source of truth 링크를 고정한다.

**작업 전 필독:** [docs/reference/AGENT_GUIDE.md](docs/reference/AGENT_GUIDE.md) (작업 유형별 문서·갱신 체크리스트)

## 문서 정책

- `../WS/nav2_REFECTOR/Policy/01_REPOSITORY_DOCUMENTATION_POLICY.md` 준수
- 루트 Markdown: `README.md`, `AGENTS.md` 만
- 구현 사실 `docs/as-built/` · 설계 `docs/design/` · 결정 `docs/adr/`
- 실행 `docs/runbook/` · 참조·온보딩 `docs/reference/` · 작업 `worklog/`

## Source of truth

| 주제 | 문서 |
| --- | --- |
| **에이전트 작업 가이드** | `docs/reference/AGENT_GUIDE.md` |
| **개발자 온보딩** | `docs/reference/DEVELOPER_GUIDE.md` |
| 스크립트 카탈로그 | `docs/reference/SCRIPTS.md` |
| config·프로파일 | `docs/reference/CONFIG.md` |
| 경로 해석 | `docs/reference/PATHS.md` |
| 현재 시뮬 구현 | `docs/as-built/SIMULATOR.md` |
| 호스트 실행 | `docs/runbook/RUN_HOST_NATIVE.md` |
| Docker custom map | `docs/runbook/RUN_WITH_CUSTOM_MAP.md` |
| config 구조 ADR | `docs/adr/2026-06-29-simulator-config-layout.md` |
| 임의 맵 목표/갭 | `docs/design/CUSTOM_MAP.md` |
| Nav API·Nav2 본체 | `../WS/nav2_REFECTOR/slam_nav_ws/docs/as-built/` |

전체 인덱스: `docs/README.md`

## 코드 변경 원칙

- `MAP_NAME` 미지정 시 `robot1_map` 하위호환 유지
- 맵별 spawn/initial pose → `config/profiles/<name>.json`
- Gazebo·bridge 설정 → `config/` (launch 인자 오버라이드 유지)
- `nav2_REFECTOR` 원본 수정 금지; `maps/` 복사본 사용
- 구현 변경 → `docs/as-built/SIMULATOR.md` 먼저 갱신
- 실행·env 변경 → `docs/runbook/`, `.env.example`, 필요 시 `docs/reference/`

## 검증

```bash
bash scripts/check_docs.sh
python3 scripts/load_profile.py sample
python3 scripts/generate_warehouse_world.py --map-yaml maps/sample/map.yaml --out-world worlds/_scratch_test.world
```
