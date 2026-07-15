# Operations Dashboard Redesign Plan

브랜치: `frontend/operations-dashboard-redesign`

기준점: `6a068f5 checkpoint: preserve runtime operations updates`

## 목표

시안의 정보 계층을 실제 React 화면에 적용하되 기존 API, 작업 실행, 복구, E-STOP, 카메라 fallback 동작을 유지한다.

## 단계

### 0. 기준점 보존 — 완료

- 현재 백엔드·프런트 변경 전체 커밋
- 프런트 개편용 로컬 브랜치 생성

### 1. 정책과 토큰 — 진행

- 디자인 정책, 정보 계층, 반응형 규칙 문서화
- 색상·간격·반경·테두리·타이포 토큰 정리
- 구현 완료 조건을 체크리스트로 고정

### 2. 지속 관제 셸

- 좌측 목적지 내비게이션을 텍스트 중심으로 확장
- 전역 헤더를 중립 표면으로 변경
- 운영 제목·새로고침·입출고 기본 행동 추가
- 중요 알람을 지도 위에 유지

완료 조건:

- 내비게이션 선택 영역과 결과 영역이 예측 가능함
- 서버·Movement·Camera·로봇·시간·E-STOP이 상시 노출됨

### 3. 지도와 우측 문맥

- 지도는 중앙 주 작업 영역을 유지
- 우측 상단은 로봇/입출고/조작 문맥만 교체
- 우측 하단 전역 카메라를 독립 고정
- 입출고 폼 내부만 스크롤

완료 조건:

- 입출고 작성 중 지도와 전역 카메라가 함께 보임
- 로봇 카메라와 전역 카메라의 역할이 구분됨
- 데스크톱 Drawer는 비모달, 1200px 이하는 모달

### 4. 작업·재고·기록 워크스페이스

- 활성 작업 요약은 접힌 상태에도 유지
- 작업 필터·자동 배정·배정 시작·우선순위·복구 기능 보존
- 재고 품목/슬롯/층 조회와 기록 탭 보존
- 표·툴바·상태 배지 규격 통일

완료 조건:

- 실행 결과가 작업 워크스페이스에 즉시 이어짐
- 조회 화면이 지도를 예고 없이 대체하지 않음

### 5. 관리 화면 정렬

- 관리 내비게이션·페이지 제목·패널·폼·표에 동일 토큰 적용
- 맵/구역, 창고, 장치, 시스템, 기록 정보 구조는 유지

완료 조건:

- 운영과 관리의 강조색은 다르지만 컴포넌트 규격은 동일함

### 6. 검증과 마감

- `npm run typecheck`
- `npm run lint`
- `npm run build`
- 핵심 Playwright UX 테스트
- 1920×1080, 1440×900, 1000×800 스크린샷 확인
- 접근성 이름, focus 복귀, 모달 차단 검증

## 커밋 전략

1. `docs(frontend): define operations UI policy and rollout plan`
2. `feat(frontend): restructure persistent operations cockpit`
3. `style(frontend): apply dashboard design tokens and responsive rules`
4. `test(frontend): lock redesigned operations UX`
