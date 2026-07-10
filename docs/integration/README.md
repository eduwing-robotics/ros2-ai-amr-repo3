# Main · Nav · AI 통합 문서

서비스 간 현재 동작과 검증 경계를 기록한다. 운영 절차는 [운영 문서](../operations/README.md), Nav 실행 절차는 [Nav 실행 가이드](../../nav-server/docs/runbook/NAV_SERVER_BEGINNER_GUIDE.md)가 소유한다.

## 문서

- [현재 상태 진단](current-state-diagnosis.md) — 구현 상태, 검증 결과, 미검증 항목
- [E2E 계약](e2e-contract.md) — 소유권, trust, capability, evidence, callback, recovery
- [ROS simulation 검증](ros-simulation-verification.md) — Gazebo/Nav2 결과와 한계
- [Source provenance](source-provenance.md) — import baseline commit

## 공통 검증

저장소 루트에서 실행한다.

```bash
./scripts/bootstrap-nohardware-envs.sh
./scripts/test-nohardware.sh
```

검증 범위와 결과 해석은 [현재 상태 진단](current-state-diagnosis.md) 및 [nohardware fixtures](../../tests/nohardware/README.md)를 따른다.
