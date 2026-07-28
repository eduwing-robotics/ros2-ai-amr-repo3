# 설계 결정

Main Server의 현재 구조에 영향을 준 주요 결정과 적용 상태를 기록합니다. 실행 방법과 현재 동작은 Main Server의 세부 문서를 기준으로 확인하고, 이 폴더의 문서는 결정 배경과 유지해야 할 설계 원칙을 설명합니다.

| 날짜 | 결정 | 상태 | 현재 의미 |
| --- | --- | --- | --- |
| 2026-06-30 | [PostgreSQL과 DBML 관리 기준](2026-06-30-postgresql-dbml-source-of-truth.md) | Active | PostgreSQL과 DBML을 업무 데이터 모델의 정본으로 사용 |
| 2026-06-30 | [DBML 호환 테이블 정책](2026-06-30-dbml-compat-table-policy.md) | Active | 업무 테이블과 독립 인프라 테이블의 경계 유지 |
| 2026-06-24 | [Nav 지도 ID 일치 규칙](2026-06-24-movement-map-id-alignment.md) | Superseded | 과거 동기화 정책 기록이며 현재는 exact-match 계약 사용 |
| 2026-06-22 | [운영자·관리자 UI 구분](2026-06-22-operator-admin-two-tier-ui.md) | Implemented | 운영·관리 모드와 고수준 작업 요청 구조에 반영 |
| 2026-06-22 | [도킹과 이동 경로 모델](2026-06-22-docking-and-path-model.md) | Active | scan·dock 페어와 Main·Nav 책임 경계의 현재 기준 |
| 2026-06-22 | [백엔드 구조 변경 규칙](2026-06-22-backend-refactor-rules.md) | Implemented | 도메인별 router·service·repository와 회귀 검증 구조에 반영 |

| 상태 | 의미 |
| --- | --- |
| Active | 현재 구현과 신규 변경에 계속 적용하는 결정 |
| Implemented | 결정한 구조가 구현됐으며 결과와 유지 규칙을 보존하는 기록 |
| Superseded | 다른 계약으로 대체되어 당시 배경 확인에만 사용하는 기록 |
