# nohardware regression fixtures

이 문서가 root nohardware suite의 실행 범위와 합격 경계의 단일 정본이다. Suite는 actual Main, Nav, AI app, disposable PostgreSQL, Main이 서빙하는 built UI를 robot hardware 없이 조립한다. 결과는 software merge proof다.

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
3. actual Main·Nav·AI·PostgreSQL·built UI full-stack smoke
4. staged failure/Ctrl-C/timeout cleanup proof
5. additional PostgreSQL persistence/concurrency seam

field audit은 declarative robot/bridge/domain/API port, map/image, route URL, waypoint/dock/ArUco, task seed, AI source 연결의 일관성을 검사한다. network reachability와 physical-coordinate accuracy는 검사하지 않는다.

`nav-server/config/robots.nohardware.json`은 TCP runner 전용 simulation fixture다. Production profile을 재정의하지 않으며 production map ID를 유지하되 `robot2_map` field 좌표를 commissioned로 취급하지 않는다.

Full-stack smoke는 실제 Main·Nav·AI process와 Docker `postgres:16-alpine`을 매 실행마다 동적 `127.0.0.1` port에 띄우고, 현재 frontend를 build해 Main static serving 경로로 확인한다.

상태 검증 항목:

- production reference sync와 Main/Nav map·location·scenario 정합
- release-managed route/waypoint write 거부, robot enable/disable과 assignment 제외
- public work-order stop의 command ID 보존, signed Nav cancel/callback, idempotent recovery event와 `manual_abort`
- signed gateway frame, Main↔Nav와 Main↔AI HMAC, `PRE_DROP_OFF` evidence
- person advisory→Main trusted stop→Nav E-stop/clear→`safe_move`; terminal 뒤 `AWAITING_OPERATOR` 유지
- PostgreSQL reservation·orchestration·recovery state와 built UI static serving

각 실행은 Movement, Main↔AI, frame gateway, PostgreSQL용 test credential을 process-local로 생성한다. 이 값은 production credential이 아니며 production pair를 생성하거나 변경하지 않는다. Runner는 값을 출력하지 않고 로그 유출을 검사한다.

Lifecycle proof는 Nav ready 뒤 `TERM`, AI ready 뒤 `TERM`, Main ready 뒤 `SIGINT`, Main ready 뒤 의도적인 AI request timeout의 네 case를 실행한다. Runner는 성공·실패·interrupt 모두에서 소유한 process group, PostgreSQL container, 임시 로그와 동적 listener를 정리한다. 별도 DB seam은 PostgreSQL reservation·orchestration·recovery concurrency를 추가로 검증한다.

DB seam은 AI 서비스를 기동하지 않는 persistence/concurrency 전용 subprocess이므로
`LMS_PERSON_HAZARD_ENABLED=false`를 **그 subprocess에만** 명시한다. 이는 AI 인증 없는
restart-dispatch가 person-monitor arm에서 fail-closed 하는 것을 우회하기 위한 범위 제한이다.
루트 TCP smoke는 이를 상속하지 않으며, signed AI monitor arm/advisory → Main trusted
E-stop/hold → signed Nav E-stop → clear/recovery command를 별도로 검증한다. DB persistence는
disposable PostgreSQL seam에서 계속 검증한다.

## 제외 범위

- physical DDS와 현장 ROS graph
- physical localization과 robot motion
- physical ArUco와 docking
- real imagery와 camera calibration/quality
- physical lift/fork/load
- 운영 PostgreSQL, production WebRTC, 장시간 다중 로봇 운행

Docker, ROS 2, npm 또는 세 service virtualenv가 없으면 runner는 성공하지 않는다. 이 proof를 위 physical 항목의 합격 근거로 사용하지 않는다. 통합 계약의 의미는 [E2E 계약](../../docs/integration/e2e-contract.md)을 따른다.
