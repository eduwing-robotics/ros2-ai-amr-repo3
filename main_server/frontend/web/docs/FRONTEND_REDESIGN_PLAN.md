# Operations Dashboard Redesign Plan

상태: Implemented baseline
주 독자: Frontend 유지보수 개발자
보조 독자: 기술 검토자
난이도: 개발
소유: Frontend
최종 갱신: 2026-07-16 16:00 KST
구현 기준: main-server 브랜치의 현재 운영·관리 UI
목적: 완료된 화면 개편의 기준선과 검증 결과를 기록한다.
적용 브랜치: `main-server`

## 목표

시안의 정보 계층을 실제 React 화면에 적용하되 기존 API, 작업 실행, 복구, E-STOP, 카메라 fallback 동작을 유지한다.

## 단계

### 0. 기준점 보존 — 완료

- 현재 백엔드·프런트 변경 전체 커밋
- 프런트 개편용 로컬 브랜치 생성

### 1. 정책과 토큰 — 완료

- 디자인 정책, 정보 계층, 반응형 규칙 문서화
- 색상·간격·반경·테두리·타이포 토큰 정리
- 구현 완료 조건을 체크리스트로 고정

### 2. 지속 관제 셸 — 완료

- 좌측 목적지 내비게이션을 텍스트 중심으로 확장
- 전역 헤더를 중립 표면으로 변경
- 운영 제목·새로고침·입출고 기본 행동 추가
- 중요 알람을 지도 위에 유지

완료 조건:

- 내비게이션 선택 영역과 결과 영역이 예측 가능함
- 서버·Movement·Camera·로봇·시간·E-STOP이 상시 노출됨

### 3. 지도와 로봇 문맥 — 완료

- 지도는 중앙 주 작업 영역을 유지
- 우측 로봇 카드 전체 클릭으로 해당 로봇 카메라 문맥 열기
- 입출고는 데스크톱에서 폼+참조 맵, 좁은 화면에서 모달 드로어
- 입출고 존·슬롯과 슬롯별 재고 선택을 맵 마커 강조와 연동

완료 조건:

- 입출고 작성 중 지도와 전역 카메라가 함께 보임
- 로봇 카메라와 전역 카메라의 역할이 구분됨
- 데스크톱 입출고 작업면에서 맵 하단이 잘리지 않음, 좁은 화면는 모달

### 4. 작업·재고·기록 워크스페이스 — 완료

- 관제 하단 실시간 작업 큐와 작업 기록 타임라인 유지
- 작업 필터·자동 배정·배정 시작·우선순위·복구 기능 보존
- 재고 품목/슬롯/층 조회와 기록 탭 보존
- 표·툴바·상태 배지 규격 통일

완료 조건:

- 실행 결과가 작업 워크스페이스에 즉시 이어짐
- 작업·재고·이벤트는 예측 가능한 중앙 목적지로 전환

### 5. 관리 화면 정렬 — 완료

- 관리 내비게이션·페이지 제목·패널·폼·표에 동일 토큰 적용
- 맵/구역, 창고, 장치, 시스템, 기록 정보 구조는 유지

완료 조건:

- 운영과 관리의 강조색은 다르지만 컴포넌트 규격은 동일함

### 6. 검증과 마감 — 완료

- `npm run typecheck`
- `npm run lint`
- `npm run build`
- 핵심 Playwright UX 테스트
- 데스크톱·좁은 화면·모바일 스크린샷 확인
- 접근성 이름, focus 복귀, 모달 차단 검증

## 커밋 전략

1. `docs(frontend): define operations UI policy and rollout plan`
2. `feat(frontend): restructure persistent operations cockpit`
3. `style(frontend): apply dashboard design tokens and responsive rules`
4. `test(frontend): lock redesigned operations UX`

## 검증 결과

- `npm run typecheck`: 통과
- `npm run lint`: 통과
- `npm run build`: 통과
- 현재 검증 정본과 해상도별 인수 조건은 [공개 TEST_CASES](../../../docs/TEST_CASES.md)를 따른다.
- 문서 캡처는 Main 서버·Chrome·데스크톱 기준이며 실제 로봇 명령 없이 촬영한다.
