# ros2-ai-amr-repo3

ROS 2 AMR 통합 작업 공간의 저장소 지도다. 현재 서비스 간 동작은 [E2E 계약](docs/integration/e2e-contract.md)이 소유한다.
문서 유형과 정본 위치는 [문서 거버넌스](docs/DOCUMENTATION_GUIDE.md)가 소유한다.

## 저장소 구조

| 경로 | 역할 |
| --- | --- |
| `ai-server/` | vision stream, lift/load evidence, person-hazard advisory |
| `main-server/` | task·DB 정본, RBAC, dispatch, evidence/safety/recovery 결정 |
| `nav-server/` | Movement API, ROS/Nav2, localization, docking/lift 실행 경계 |
| `scripts/` | root preflight와 nohardware runner |
| `tests/nohardware/` | cross-service nohardware suite와 helper |
| `docs/integration/` | 현재 cross-service 계약 링크 |
| `docs/operations/` | 운영 절차 링크 |
| `docs/history/` | import와 검증의 과거 기록 |

## 문서

- [통합 계약](docs/integration/e2e-contract.md)
- [nohardware suite 범위](tests/nohardware/README.md)
- [운영 문서 색인](docs/operations/README.md)
- [AI Server 문서](ai-server/README.md)
- [Nav 실행 가이드](nav-server/docs/runbook/NAV_SERVER_BEGINNER_GUIDE.md)
- [문서 이력](docs/history/README.md)
