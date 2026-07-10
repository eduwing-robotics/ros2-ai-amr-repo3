# 시스템 아키텍처 개요

상태: Active
소유: Docs
작성: 2026-06-23 00:00 KST
최종 갱신: 2026-07-09 17:20 KST
목적: 관제·이동·인식 서버의 경계·흐름·책임을 한눈에 보이게 한다. 용어는 [GLOSSARY](GLOSSARY.md).

## 토폴로지

```mermaid
flowchart LR
  UI[운영자_화면] -->|입출고_요청| Main[관제_서버]
  Main --> PG[(PostgreSQL)]
  Main -->|이동_명령| Mov[이동_서버]
  Mov -->|상태_콜백| Main
  Main -->|영상_중계| Vis[인식_서버]
  Mov <-->|ROS2| ROS[로봇]
  Vis <-->|인식| ROS
```

## 요청 흐름

```mermaid
sequenceDiagram
  participant Op as 운영자
  participant Main as 관제서버
  participant Mov as 이동서버
  Op->>Main: 입출고 요청 생성
  Main->>Main: 작업 단계 계획
  Main->>Mov: 이동/도킹 명령
  Mov-->>Main: 도착/완료 콜백
  Main->>Mov: 다음 단계 또는 복귀
  Main-->>Op: 작업 상태 갱신
```

## 디자인 철학

- **브라우저 → 관제만.** 외부 서버 직접 호출 금지(인식 WebRTC 미디어만 예외).
- **외부 서버 → DB 직접 접근 금지.** API/콜백만.
- **관제 = 무엇을** (좌표·마커·동작·층). **이동 = 어떻게**. **인식 = 무엇이 보이나**.
- 콜백은 누락될 수 있다 → 멱등 + 명령 조회 폴백.
- 비상정지는 전 로봇 일괄·자동 재개 금지 → **운영자 개입 대기**. 상세: [작업 실행 흐름](TASK_ORCHESTRATION.md).

## 책임 한눈에

```mermaid
flowchart TB
  subgraph MainOwn [관제_소유]
    WO[입출고_재고]
    Orch[작업_단계_실행]
    DB[(PostgreSQL)]
  end
  subgraph MovOwn [이동_소유]
    Nav[주행_계획_실행]
    Dock[정밀_도킹_리프트]
    Estop[비상정지_선점]
  end
  subgraph VisOwn [인식_소유]
    Stream[영상_아루코_증거]
  end
  MainOwn -->|명령| MovOwn
  MovOwn -->|이벤트| MainOwn
  MainOwn -->|중계| VisOwn
```

| 책임 | 소유 | 정본 |
| --- | --- | --- |
| 입출고·재고·슬롯 | 관제 | [입출고 흐름](INBOUND_OUTBOUND.md) |
| 작업 단계 실행 | 관제 | [작업 실행 흐름](TASK_ORCHESTRATION.md) |
| 주행·도킹·비상정지 선점 | 이동 | [Nav Server contract](../../../nav-server/docs/reference/MAIN_SERVER_CONTRACT.md) |
| 영상·아루코 | 인식 | [interfaces README](../interfaces/README.md) |
| DB SoT | 관제 | [db/](db/README.md) |

## 시스템 대응 (구현)

코드·계약 식별자. 상단 스토리와 같은 의미다.

| 업무 | 코드 |
| --- | --- |
| 이동 명령 종류 | `move_to_point` · `dock_transfer` · `aruco_align` · `leave_dock` · `manual_drive` · `estop` |
| 명령 API | `POST/GET /robot-commands` (`services/robot_commands.py`) |
| Movement 미구현 | `501 movement_robot_commands_api_missing` |

Movement 필드·callback 스키마 → [Nav Server contract](../../../nav-server/docs/reference/MAIN_SERVER_CONTRACT.md).

## 정본 지도

| 영역 | 링크 |
| --- | --- |
| 용어 | [GLOSSARY](GLOSSARY.md) |
| 백엔드 레이어 | [BACKEND](BACKEND.md) |
| API | [api/](../api/README.md) |
| 연동 | [interfaces/README](../interfaces/README.md) |
| UX | [IA](../ui-ux/IA.md) |
