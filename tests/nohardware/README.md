# nohardware regression fixtures

이 디렉터리는 camera, lift, ROS node, robot hardware 없이 실행하는 cross-service contract fixture와 helper를 둔다.

## 실행

저장소 루트에서 실행한다.

```bash
./scripts/bootstrap-nohardware-envs.sh
./scripts/test-nohardware.sh
```

## runner 순서와 범위

`test-nohardware.sh`는 실패 시 중단하며 다음을 실행한다.

1. field configuration consistency audit
2. AI, Main, Nav service-local nohardware contracts
3. signed localhost TCP smoke
4. disposable PostgreSQL seam

field audit은 declarative robot/bridge/domain/API port, map/image, route URL, waypoint/dock/ArUco, task seed, AI source 연결의 일관성을 검사한다. network reachability와 physical-coordinate accuracy는 검사하지 않는다.

TCP smoke는 실제 Nav·AI FastAPI app과 Main HTTP client를 동적 localhost port에서 연결한다. 실제 signed gateway frame ingress는 unsigned request를 거부하고 signed request를 수락한다. TCP seam은 `PRE_DROP_OFF` PASS와 AI person advisory→Main trusted stop→signed Nav E-stop/clear/recovery를 검증하며 두 enabled map profile을 기동한다. DB seam은 Docker `postgres:16-alpine` 컨테이너에 실제 Main schema/seed를 적용하고 PostgreSQL 7-way concurrency seam을 검증한 뒤 container를 제거한다.

DB seam은 AI 서비스를 기동하지 않는 persistence/concurrency 전용 subprocess이므로
`LMS_PERSON_HAZARD_ENABLED=false`를 **그 subprocess에만** 명시한다. 이는 AI 인증 없는
restart-dispatch가 person-monitor arm에서 fail-closed 하는 것을 우회하기 위한 범위 제한이다.
루트 TCP smoke는 이를 상속하지 않으며, signed AI monitor arm/advisory → Main trusted
E-stop/hold → signed Nav E-stop → clear/recovery command를 별도로 검증한다. DB persistence는
disposable PostgreSQL seam에서 계속 검증한다.

## 제외 범위

- physical camera, robot, lift
- 현장 ROS/Nav2 graph와 DDS connectivity
- operating PostgreSQL, production WebRTC
- 장시간 다중 로봇 운행

Docker가 없으면 DB seam 때문에 runner는 성공하지 않는다. 통합 계약의 의미는 [E2E 계약](../../docs/integration/e2e-contract.md)을 따른다.
