# 운영 문서

이 문서는 현재 운영 절차를 역할별로 나눈다. 서비스별 상세 명령은 링크한 runbook이 소유한다.

[operator-preflight.sh](../../scripts/operator-preflight.sh)는 service를 시작하거나 ROS message·motion command를 보내지 않는 read-only 점검이다. 실행 전에 Movement HMAC(`NAV_MAIN_HMAC_SECRET` 또는 `LMS_MOVEMENT_HMAC_SECRET`), Vision HMAC(`MAIN_HMAC_SECRET` 또는 `LMS_VISION_HMAC_SECRET`), 그리고 전용 frame gateway HMAC(`VISION_GATEWAY_HMAC_SECRET`)이 있어야 한다. 값은 존재 여부만 보고되고 출력되지 않는다.

Main control-plane mutation은 preflight와 별도로 `LMS_OPERATOR_TOKEN` 또는 작업에 필요한 `LMS_ADMIN_TOKEN` Bearer credential을 요구한다.

| mode | 역할 |
| --- | --- |
| `--software` | venv, ROS/Nav config, secret, Docker, map/config, port 점검 |
| `--nohardware` | software 점검 후 공통 nohardware suite 실행 |
| `--hardware-checklist` | software 점검 후 제한된 ROS topic·HTTP health 확인 |

## 권장 읽기 순서

1. [운영 역할과 준비](operator-overview.md)
2. [시작과 종료](startup-shutdown.md)
3. [기능 체크리스트](feature-checklists.md)
4. [장애 격리와 복구](troubleshooting.md)

## 권장 실행 순서

1. software 검증: `./scripts/operator-preflight.sh --software`
2. root E2E 검증: `./scripts/operator-preflight.sh --nohardware`
3. Gazebo 검증: [ROS simulation 검증](../integration/ros-simulation-verification.md)
4. 현장 운영: Nav API, AI, Main을 [시작과 종료](startup-shutdown.md) 순서로 시작하고 `--hardware-checklist`와 [기능 체크리스트](feature-checklists.md)를 완료

서비스 계약은 [E2E 계약](../integration/e2e-contract.md)을 따른다.
