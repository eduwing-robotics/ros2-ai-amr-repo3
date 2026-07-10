# 용어집 (Glossary)

상태: Active
소유: Docs
최종 갱신: 2026-07-09 18:05 KST
목적: 업무어·시스템어·코드 식별자를 15개 이내로 맞춰 문서·코드 가독성을 맞춘다.

도표·상단 스토리는 **업무어**를 쓰고, 필요 시 `(코드명)`을 병기한다.

## 서버

| 업무어 | 코드·문서 | 설명 |
| --- | --- | --- |
| 관제 서버 | Main / LMS | FastAPI + PostgreSQL. 브라우저·외부 서버의 허브 |
| 이동 서버 | Movement | 로봇별 Nav2·도킹·리프트 |
| 인식 서버 | Vision | 영상·아루코·위험 advisory |

## 업무 → 실행

| 업무어 | 코드 | 설명 |
| --- | --- | --- |
| 입출고 요청 | work order | 품목+수량 상위 요청 |
| 작업 | task | work order에서 분해된 실행 단위 |
| 작업 단계 | `steps[]` | 한 번의 이동/도킹 명령 단위 |
| 단계 번호 | `step_index` | 현재 진행 중인 step 인덱스 |
| 접근 대기 → 도킹 | gate | approach 도착(ARRIVED) 후 `dock_transfer` |
| 대기점 / 작업점 | approach / dock | stand-off vs 마커 작업점 |

## 진행·복구

| 업무어 | 코드 | 설명 |
| --- | --- | --- |
| 진행 폴러 | `task_progress_poller` | ~5s 주기: 누락 콜백 폴링·배정 |
| 명령 이벤트 전진 | `advance_on_command_event` | 콜백/폴러가 다음 step으로 진행 |
| 단계 계획 | `plan_command_steps` | 시나리오 → steps[] 동결 |
| 운영자 개입 대기 | `AWAITING_OPERATOR` | ESTOP 등 후 자동 재개 금지 |
| 복구 진행 중 | `RECOVERY_RUNNING` | 운영자 복구 이동 실행 중 |

## 공개 계약 (이름 동결)

| 이름 | 설명 |
| --- | --- |
| `move_to_point` / `dock_transfer` / `estop` 등 | Movement command `kind` — 변경 금지 |
| `/api/v1/work-orders`, `/robot-commands` | 공개 HTTP path — 변경 금지 |

## 관련

- 네이밍 규칙·rename 등급: [NAMING_CONVENTION](../contributing/NAMING_CONVENTION.md)
- 시스템 개요: [OVERVIEW](OVERVIEW.md)
