# AI Server 문서

이 디렉터리는 AI Server의 실행·검증·책임·외부 계약을 목적별로 안내합니다. 처음 시작할 때는 상위 [AI Server README](../README.md)에서 실행 방식을 먼저 선택합니다.

## 시작과 운영

| 문서 | 언제 읽는가 |
| --- | --- |
| [Deployment](deployment.md) | API-only native 또는 Docker 배포를 준비할 때 |
| [Low-load runtime](low-load-mode.md) | 카메라·ROS gateway·WebRTC를 포함한 현장 기본 실행을 시작할 때 |
| [Troubleshooting](troubleshooting.md) | API, source, model, hostname 또는 stream 상태가 비정상일 때 |

## 검증

| 문서 | 검증 범위 |
| --- | --- |
| [Quality gates](quality-gates.md) | pytest, contract, deployment asset와 정적 검사 |
| [Live API smoke tests](live-api-smoke-tests.md) | GoPro/PiCam이 연결된 현장 수동 검증 |

자동 테스트와 synthetic fixture는 실제 카메라·조명·가림 조건의 합격 근거가 아닙니다.

## 책임과 계약

| 문서 | 기준 내용 |
| --- | --- |
| [Responsibility](responsibility.md) | AI·Main·Nav 사이의 결정과 상태 소유권 |
| [AI Server API](contracts/ai-server-api.md) | endpoint, HMAC, 오류와 OpenAPI artifact |
| [Lift/load evidence](contracts/lift-load-evidence.md) | ArUco·ZoneROI 기반 적재·하역 evidence |
| [Evidence evaluation v1](contracts/evidence-evaluation.v1.md) | connector-facing evidence 평가 결과 |

JSON schema와 generated OpenAPI는 [`contracts/`](contracts/) 아래에 있으며 Markdown 계약 문서가 사용 목적과 해석 경계를 설명합니다.

## ROS companion

[smartfactory_perception_ros README](../ros2/smartfactory_perception_ros/README.md)는 frame gateway, overlay stream bridge, snapshot client와 passive ArUco monitor의 선택 기준과 실행법을 설명합니다.
