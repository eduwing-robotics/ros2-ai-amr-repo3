# Documentation Index

상태: Active
소유: Docs
작성: 2026-06-22 23:59 KST
최종 갱신: 2026-07-09 17:55 KST
목적: 권장 읽기 순서로 정본에 들어가게 한다. 폴더 분리 없이 같은 트리에서 상세·명세로 이어진다.

공통 규칙: [repository documentation governance](../../docs/DOCUMENTATION_GUIDE.md).
Main 추가 안내: [DOCUMENTATION_GUIDE](DOCUMENTATION_GUIDE.md). 용어: [architecture/GLOSSARY](architecture/GLOSSARY.md).

## 권장 읽기 순서 (먼저)

```mermaid
flowchart LR
  G[용어집] --> O[시스템_개요]
  O --> I[입출고_흐름]
  I --> N[외부_연동]
```

1. [용어집](architecture/GLOSSARY.md) — 업무어 ↔ 코드어
2. [시스템 개요](architecture/OVERVIEW.md) — 누가 무엇을 소유하나
3. [입출고 업무 흐름](architecture/INBOUND_OUTBOUND.md) — 요청 한 건이 어떻게 도나
4. [외부 연동](interfaces/README.md) — Movement / Vision 경계 · [Integration Quickstart](interfaces/README.md#integration-quickstart)

## 상세·명세 (같은 트리)

| 문서 | 내용 |
| --- | --- |
| [작업 실행 흐름](architecture/TASK_ORCHESTRATION.md) | step·콜백·폴러·ESTOP 복구 |
| [ESTOP 복구 Playbook](operations/ESTOP_RECOVERY_PLAYBOOK.md) | 현장 비상정지 후 운영자 절차 |
| [백엔드 레이어](architecture/BACKEND.md) | 서비스 허브 (기여자) |
| [DB](architecture/db/README.md) | PostgreSQL SoT · 12테이블 ERD |
| [api/API_MAIN](api/API_MAIN.md) | REST 목록·as-built |
| [ui-ux/FRONTEND](ui-ux/FRONTEND.md) | 프론트 as-built·레이아웃 |
| [ui-ux/IA](ui-ux/IA.md) | 화면 네비게이션 |
| [contributing/DEVELOPMENT_GUIDE](contributing/DEVELOPMENT_GUIDE.md) | 기여 진입 |
| [operations/QUALITY_GATE](operations/QUALITY_GATE.md) | 검증 명령 |

## 영역

| 영역 | 청중 |
| --- | --- |
| [architecture/](architecture/README.md) | 시스템·DB |
| [interfaces/](interfaces/README.md) | Movement/Vision 계약 |
| [api/](api/README.md) | REST 소비자 |
| [ui-ux/](ui-ux/README.md) | 화면·IA |
| [operations/](operations/README.md) | 실행·게이트 |
| [decisions/](decisions/README.md) | ADR |
| [contributing/](contributing/README.md) | 규약 |

이미지: [assets/](assets/README.md).
