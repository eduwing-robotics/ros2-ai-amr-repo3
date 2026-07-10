# 장애 격리와 복구

## 즉시 중지

다음은 physical command 중지 조건이다.

- `is_emergency=true` 또는 person safety stop
- `localized=false`, `nav2_ready=false`, `command_accepting=false`
- required capability/lift readiness 없음
- LiDAR, TF, ArUco, odom, camera source가 stale 또는 없음
- HMAC signature/replay/callback identity 오류
- evidence binding/freshness 오류 또는 `PASS`와 `command_satisfying=true`가 아닌 결과

새 dispatch를 중지하고 Main의 task/safety state와 Nav health를 기록한다. active motion과 E-stop은 현장 safety 절차를 따른다.

## 격리 순서

1. **Nav**: profile, `localized`, `nav2_ready`, `command_accepting`, `is_emergency`, capability, lift, sensor freshness를 health에서 확인한다. Nav 실행/상태 명령은 [Nav 실행 가이드](../../nav-server/docs/runbook/NAV_SERVER_BEGINNER_GUIDE.md)를 따른다.
2. **AI**: `/api/v1/health`와 대상 stream/source를 확인한다. source 또는 monitor가 실패하면 movement를 재개하지 않는다.
3. **Main**: `/health`, PostgreSQL 연결, Movement/AI URL, task/evidence/safety/recovery DB state를 확인한다.
4. **network**: Main↔Nav, Main↔AI HTTP와 ROS/DDS 연결을 분리해 확인한다. nohardware TCP success는 현장 reachability를 보장하지 않는다.

## 복구

1. 원인 service/hardware를 정상 상태로 복구한다.
2. Nav health가 physical health 기대값을 모두 만족하는지 확인한다.
3. person safety stop이면 operator가 E-stop을 clear한다.
4. Main의 DB recovery state와 live Movement health가 안전 조건을 만족하는지 확인한다.
5. Main `safe_replan`이 terminal success가 된 뒤 interrupted step 재-dispatch를 허용한다.

E-stop clear, stale evidence, callback 재전송만으로 task를 재개하지 않는다. callback은 HMAC, identity, atomic terminal claim을 다시 통과해야 한다.

## 종료 후 재시작

service process를 종료한 경우 [시작과 종료](startup-shutdown.md)의 순서로 재시작한다. nohardware 검증은 service 경계 회귀를 확인하지만 hardware/network 복구의 증거는 아니다.
