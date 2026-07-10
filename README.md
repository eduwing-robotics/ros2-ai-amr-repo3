# ros2-ai-amr-repo3

Main, Nav, AI 서비스를 함께 검증하는 ROS 2 AMR 작업 공간이다.

## 구조

| 경로 | 역할 |
| --- | --- |
| `ai-server/` | 비전 스트림, lift/load evidence, person hazard advisory |
| `main-server/` | 작업·DB 정본, Bearer RBAC, 배정, evidence/safety/recovery 결정 |
| `nav-server/` | Movement API, ROS/Nav2, localization, docking/lift 실행 경계 |
| `scripts/` | 운영 preflight와 root E2E 검증 |
| `tests/nohardware/` | signed TCP·PostgreSQL 통합 검증 helper |
| `docs/integration/` | 현재 상태, E2E 계약, simulation 검증 |
| `docs/operations/` | 운영 순서와 기능 checklist |

## 준비

각 서비스는 자체 venv를 사용한다.

```bash
./scripts/bootstrap-nohardware-envs.sh
```

운영 전 read-only 점검은 [운영 문서](docs/operations/README.md)를 따른다.

## Root E2E 검증

```bash
./scripts/test-nohardware.sh
```

현재 root E2E는 PASS다. field binding audit, 실제 signed gateway frame ingress, `PRE_DROP_OFF` PASS, AI person advisory→Main trusted stop→Nav E-stop/clear/recovery, 두 enabled map profile, disposable PostgreSQL 7-way concurrency seam을 포함한다.

| 서비스 검증 | 결과 |
| --- | --- |
| AI root pytest | `480 passed`; Ruff 통과 |
| Main backend | `188 passed, 56 skipped`; Ruff 통과 |
| Nav `check_all.sh` | `142 passed, 1 skipped` |

## 문서

- [운영 문서](docs/operations/README.md)
- [현재 상태](docs/integration/current-state-diagnosis.md)
- [E2E 계약](docs/integration/e2e-contract.md)
- [ROS simulation 검증](docs/integration/ros-simulation-verification.md)
- [Source provenance](docs/integration/source-provenance.md)
- [Nav 실행 가이드](nav-server/docs/runbook/NAV_SERVER_BEGINNER_GUIDE.md)
