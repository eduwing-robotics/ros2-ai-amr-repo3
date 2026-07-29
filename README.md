# E2E 물류 관제 시스템

운영자의 입·출고 요청을 로봇 배정, 자율주행, 정밀 도킹, 적재·하역, Vision 검증과 재고 반영까지 연결한 ROS 2 기반 물류 자동화 프로젝트입니다.

Main Server, Nav Server, AI Server와 두 대의 TurtleBot3가 역할을 나누되, 하나의 `task_id`를 기준으로 작업의 시작부터 완료까지 추적할 수 있도록 구성했습니다.

https://github.com/user-attachments/assets/155fc71c-53f5-4262-bbdc-710d7563c2a5

---

## 1. 팀 구성 및 역할

<table width="100%">
  <thead><tr><th width="5%" nowrap>순서</th><th width="15%" nowrap>팀원</th><th width="20%" nowrap>담당 영역</th><th width="60%" nowrap>주요 역할</th></tr></thead>
  <tbody>
    <tr><td align="center" nowrap>1</td><td align="center" nowrap>손영빈(팀장)</td><td nowrap>Nav·Hardware</td><td nowrap>ROS 2·Nav2, 도킹, Lift 연동과 실물 주행</td></tr>
    <tr><td align="center" nowrap>2</td><td align="center" nowrap>윤주찬</td><td nowrap>Hardware</td><td nowrap>포크리프트 구조, Lift 구동부와 실물 하드웨어 구성</td></tr>
    <tr><td align="center" nowrap>3</td><td align="center" nowrap>김현수</td><td nowrap>Main·UI·DB</td><td nowrap>작업·재고·관제 UI, PostgreSQL과 서버 오케스트레이션</td></tr>
    <tr><td align="center" nowrap>4</td><td align="center" nowrap>하샘</td><td nowrap>Vision·Localization</td><td nowrap>영상 pipeline, evidence, 안전 감지와 위치 복구</td></tr>
  </tbody>
</table>


## 2. 프로젝트 주제

<table width="100%">
  <thead><tr><th width="24%" nowrap>구분</th><th width="76%" nowrap>내용</th></tr></thead>
  <tbody>
    <tr><td nowrap>프로젝트 목표</td><td nowrap>입·출고 요청부터 재고 반영까지 이어지는 E2E 물류 작업 구현</td></tr>
    <tr><td nowrap>운영 대상</td><td nowrap>TurtleBot3 기반 포크리프트형 AMR 2대</td></tr>
    <tr><td nowrap>핵심 구성</td><td nowrap>Main Server, Nav Server, AI Server, PostgreSQL, Admin UI</td></tr>
    <tr><td nowrap>이동 방식</td><td nowrap>ROS 2, Nav2, AMCL, LiDAR 기반 자율주행</td></tr>
    <tr><td nowrap>정밀 작업</td><td nowrap>ArUco 정렬, 포크 삽입, Lift 적재·하역</td></tr>
    <tr><td nowrap>작업 검증</td><td nowrap>카메라 source, Zone ROI, marker와 수량 기반 Vision evidence</td></tr>
    <tr><td nowrap>안전 전략</td><td nowrap>사람 위험 감지, E-stop, 작업 보류와 운영자 복구</td></tr>
    <tr><td nowrap>상태 관리</td><td nowrap><code>task_id</code>와 <code>command_id</code> 기반 명령·결과·증거·재고 추적</td></tr>
  </tbody>
</table>

---

## 3. 주제 선정 이유

물류 자동화는 단순 이동뿐 아니라 작업 요청, 로봇 할당, 적재·하역, 영상 검증과 재고 반영을 하나의 흐름으로 연결해야 합니다. 이 프로젝트는 분산된 상태를 추적 가능한 E2E 작업으로 통합하고, 실제 로봇 환경에서 검증하기 위해 선정했습니다.

<table width="100%">
  <thead><tr><th width="42%" nowrap>선정 배경</th><th width="58%" nowrap>프로젝트 방향</th></tr></thead>
  <tbody>
    <tr><td nowrap>반복적인 입·출고 운반 업무</td><td nowrap>요청부터 재고 반영까지 정형화된 작업 흐름 구성</td></tr>
    <tr><td nowrap>단순 자율주행만으로는 부족한 물류 동작</td><td nowrap>Nav2, ArUco 도킹과 Lift 적재·하역 통합</td></tr>
    <tr><td nowrap>여러 서버와 장치에 분산된 상태</td><td nowrap><code>task_id</code>와 <code>command_id</code> 기반 실행 결과 추적</td></tr>
    <tr><td nowrap>화물 불일치와 사람 접근 위험</td><td nowrap>Vision evidence, E-stop과 운영자 복구 적용</td></tr>
    <tr><td nowrap>ROS 2·Vision·관제·DB 통합 필요</td><td nowrap>Main·Nav·AI 책임을 분리한 E2E 시스템 구현</td></tr>
  </tbody>
</table>

---

## 4. 사용자 요구사항

<table width="100%">
  <thead><tr><th width="12%" nowrap>ID</th><th width="88%" nowrap>현재 구현된 사용자 요구사항</th></tr></thead>
  <tbody>
    <tr><td align="center" nowrap>UR-01</td><td nowrap>로봇은 물품을 운송할 수 있어야 한다.</td></tr>
    <tr><td align="center" nowrap>UR-02</td><td nowrap>로봇은 작업 구역에서 이동할 수 있어야 한다.</td></tr>
    <tr><td align="center" nowrap>UR-03</td><td nowrap>로봇은 장애물을 감지하고 회피하거나 정지할 수 있어야 한다.</td></tr>
    <tr><td align="center" nowrap>UR-04</td><td nowrap>로봇은 긴급 정지할 수 있어야 한다.</td></tr>
    <tr><td align="center" nowrap>UR-05</td><td nowrap>시스템은 사람 접근 등의 위험 요소를 감지하고 운영자에게 알릴 수 있어야 한다.</td></tr>
    <tr><td align="center" nowrap>UR-06</td><td nowrap>관리자는 로봇의 위치·주행·통신·작업 상태를 확인할 수 있어야 한다.</td></tr>
    <tr><td align="center" nowrap>UR-07</td><td nowrap>관리자는 품목·보관 위치별 재고 현황을 확인할 수 있어야 한다.</td></tr>
    <tr><td align="center" nowrap>UR-08</td><td nowrap>관리자는 작업 결과와 재고 변경 이력을 조회할 수 있어야 한다.</td></tr>
    <tr><td align="center" nowrap>UR-09</td><td nowrap>관리자는 작업 우선순위를 설정하고 변경할 수 있어야 한다.</td></tr>
  </tbody>
</table>

## 5. 시스템 요구사항

<table width="100%">
  <thead><tr><th width="10%" nowrap>ID</th><th width="24%" nowrap>기능</th><th width="66%" nowrap>요구사항</th></tr></thead>
  <tbody>
    <tr><td align="center" nowrap>SR-01</td><td nowrap>재고 확인</td><td nowrap>관리자가 품목·보관 위치·층별 현재 재고를<br>조회할 수 있다.</td></tr>
    <tr><td align="center" nowrap>SR-02</td><td nowrap>입고 관리</td><td nowrap>관리자가 품목·수량·보관 위치를 지정해<br>입고 작업을 요청할 수 있다.</td></tr>
    <tr><td align="center" nowrap>SR-03</td><td nowrap>출고 관리</td><td nowrap>관리자가 품목·수량을 지정해<br>출고 작업을 요청할 수 있다.</td></tr>
    <tr><td align="center" nowrap>SR-04</td><td nowrap>작업 우선순위 관리</td><td nowrap>관리자는 작업 우선순위를 설정·변경할 수 있으며,<br>시스템은 우선순위가 높은 작업부터 배정한다.</td></tr>
    <tr><td align="center" nowrap>SR-05</td><td nowrap>로봇 자동 할당</td><td nowrap>시스템은 작업을 수행할 수 있는 준비된 로봇을<br>자동으로 배정한다.</td></tr>
    <tr><td align="center" nowrap>SR-06</td><td nowrap>서버·로봇 통신</td><td nowrap>각 서버와 로봇은 명령, 상태, 결과와<br>검증 정보를 주고받는다.</td></tr>
    <tr><td align="center" nowrap>SR-07</td><td nowrap>로봇 상태 확인</td><td nowrap>관리자는 로봇의 연결 상태, 준비 여부, 현재 위치와<br>작업 상태, 긴급 정지 여부를 확인할 수 있다.</td></tr>
    <tr><td align="center" nowrap>SR-08</td><td nowrap>실시간 위치 확인</td><td nowrap>관리자는 지도에서 로봇의 현재 위치와 이동 상태를<br>실시간으로 확인할 수 있다.</td></tr>
    <tr><td align="center" nowrap>SR-09</td><td nowrap>작업 구역 이동</td><td nowrap>로봇은 입고·출고·보관·대기 구역 사이를<br>자율적으로 이동한다.</td></tr>
    <tr><td align="center" nowrap>SR-10</td><td nowrap>장애물 대응</td><td nowrap>로봇은 장애물을 회피하며,<br>사람 접근 등 위험 상황이 감지되면 정지한다.</td></tr>
    <tr><td align="center" nowrap>SR-11</td><td nowrap>물품 적재·하역</td><td nowrap>로봇은 물품에 맞춰 위치를 정렬하고 적재·하역한 뒤<br>작업 결과를 전달한다.</td></tr>
    <tr><td align="center" nowrap>SR-12</td><td nowrap>위험 감지·알림</td><td nowrap>시스템은 사람 접근이나 화물 불일치를 감지하면<br>작업을 중단하고 관리자에게 알린다.</td></tr>
    <tr><td align="center" nowrap>SR-13</td><td nowrap>긴급 정지·복구</td><td nowrap>위험 상황이나 관리자 요청이 발생하면 로봇을 정지하고,<br>안전이 확인된 후 작업을 재개한다.</td></tr>
    <tr><td align="center" nowrap>SR-14</td><td nowrap>재고 자동 갱신</td><td nowrap>입·출고 작업이 완료되면 현재 재고와<br>변경 이력을 자동으로 갱신한다.</td></tr>
    <tr><td align="center" nowrap>SR-15</td><td nowrap>작업 이력 조회</td><td nowrap>관리자는 작업 결과, 진행 상태와<br>재고 변경 이력을 확인할 수 있다.</td></tr>
    <tr><td align="center" nowrap>SR-16</td><td nowrap>오류·안전 이력 관리</td><td nowrap>시스템은 작업 실패, 통신 오류와 안전 정지 내용을<br>표시하고 이력으로 저장한다.</td></tr>
  </tbody>
</table>

---

## 6. 하드웨어·소프트웨어 아키텍처

### 하드웨어 아키텍처

![하드웨어 아키텍처](<assets/Images/HW Architecture (2).png>)

![하드웨어 구성](<assets/Images/Screenshot from 2026-07-27 18-52-57.png>)

자세한 CAD, 3D 출력과 배선 자료는 [Hardware 문서](hardware/README.md)를 참고합니다.

### 소프트웨어 아키텍처

![소프트웨어 아키텍처](<assets/Images/SW Architecture (1)(1)(1).png>)

---

## 7. 운영 시나리오

### 7.1 입고 시나리오

1. 운영자가 품목, 수량과 입고 위치를 입력합니다.
2. Main Server가 요청을 검증하고 현재 재고·보관 위치를 조회합니다.
3. 작업 생성 조건을 다시 확인한 뒤 가용 로봇을 할당합니다.
4. Nav Server가 입고 지점까지 Nav2 이동을 실행합니다.
5. 로봇이 ArUco marker를 이용해 팔레트와 정렬하고 포크를 삽입합니다.
6. Lift가 화물을 들어 올리고 AI Server가 적재 evidence를 생성합니다.
7. Main Server가 evidence의 대상·시각·결과를 확인한 뒤 보관 위치 이동을 지시합니다.
8. 로봇이 보관 위치에서 하역 단계를 수행하고 결과를 반환합니다.
9. 최종 검증이 끝나면 로봇은 대기 위치로 복귀합니다.
10. Main Server가 작업 완료, 입고 이력과 재고를 PostgreSQL에 반영합니다.

### 7.2 출고 시나리오

1. 운영자가 출고할 품목과 수량을 요청합니다.
2. Main Server가 재고와 해당 품목의 보관 위치를 확인합니다.
3. 가용 로봇을 할당하고 보관 위치까지 이동하도록 명령합니다.
4. Nav Server가 approach pose 도착 후 ArUco 정렬과 적재를 실행합니다.
5. AI Server의 evidence를 통해 예상 화물이 적재되었는지 확인합니다.
6. 로봇이 출고 위치로 이동하고 하역 전 상태를 다시 확인합니다.
7. 하역 완료 후 로봇은 대기 위치로 복귀합니다.
8. Main Server가 출고 이력, 작업 완료와 감소한 재고를 함께 반영합니다.

### 7.3 위험 감지와 복구 시나리오

1. 주행 중 사람 접근, 적재 불량 또는 운영자 E-stop 요청이 발생합니다.
2. AI Server 또는 운영자가 위험 신호를 Main Server에 전달합니다.
3. Main Server가 작업을 보류하고 Nav Server에 정지를 요청합니다.
4. Nav Server가 현재 동작을 취소하고 물리 정지 결과를 보고합니다.
5. 정지 여부가 확인되지 않으면 작업은 자동으로 진행되지 않습니다.
6. 운영자가 현장, 로봇 위치, 화물과 이전 명령 상태를 확인합니다.
7. 안전 상태에 따라 현재 단계 재개, 안전 위치 이동 또는 작업 취소를 선택합니다.
8. 복구 결과와 운영자 결정은 기존 `task_id`의 이력으로 남습니다.

---

## 8. 시퀀스 다이어그램

> **Sequence Diagram  — 입고 작업**

![입고 작업 시퀀스 다이어그램](assets/Images/InBound.png)

> **Sequence Diagram  — 출고 작업**

![출고 작업 시퀀스 다이어그램](assets/Images/OutBound.png)

> **Sequence Diagram — 위험 감지, E-stop과 작업 복구**

![위험 감지와 E-stop 복구 시퀀스 다이어그램](assets/Images/estop.png)

## 9. 상태 다이어그램

> **State Diagram — 입출고 작업 상태**

![입출고 작업 상태 다이어그램](assets/Images/입출고.png)

> **State Diagram — 안전정지와 운영자 복구**

![안전정지와 운영자 복구 다이어그램](assets/Images/복구.png)

> **State Diagram — 로봇 상태**

![로봇 상태 다이어그램](assets/Images/로봇.png)

## 10. 물류센터 맵, 요소 지점
<p align="center">
  <img src="assets/smartfactory_map_creation_rviz.png" width="800" alt="스마트팩토리 Navigation 맵 제작 화면">
</p>

## 11. 소스 구성

```text
.
├── main-server/   # 작업·재고·안전 상태와 Admin UI
├── nav-server/    # 이동·도킹·Lift와 로봇별 runtime
├── ai-server/     # 영상·탐지·stream과 evidence
├── config/        # 네트워크와 통합 runtime profile
├── scripts/       # 전체 환경 준비, 실행, 종료와 점검
├── tests/         # 서버 간 계약과 no-hardware 검증
├── docs/          # 통합 계약, 운영, 검증과 이력
└── assets/        # README와 발표용 이미지
```

세 서버는 각자 구현과 실행을 설명하는 README와 책임 경계 문서를 가집니다. 최상단 문서는 프로젝트 배경, E2E 시나리오와 통합 결과를 설명하고, 세부 API·설정·운영 절차는 서버별 문서에서 관리합니다.

---

## 12. 프로젝트 목표와 범위

<table width="100%">
  <thead><tr><th width="34%" nowrap>핵심 목표</th><th width="66%" nowrap>구현 범위</th></tr></thead>
  <tbody>
    <tr><td nowrap>입·출고 작업과 재고 관리</td><td nowrap>작업 생성·상태 전이와 PostgreSQL 기반 재고·이력 반영</td></tr>
    <tr><td nowrap>가용 로봇 할당</td><td nowrap>TurtleBot3 두 대의 준비 상태·지원 기능 확인과 중복 할당 방지</td></tr>
    <tr><td nowrap>자율주행과 정밀 작업</td><td nowrap>Nav2 waypoint 이동, ArUco 도킹과 Lift 적재·하역</td></tr>
    <tr><td nowrap>작업 결과 검증</td><td nowrap>Vision evidence를 업무 진행의 검증 근거로 사용</td></tr>
    <tr><td nowrap>위험 대응</td><td nowrap>사람 감지, E-stop, 작업 보류와 운영자 복구</td></tr>
    <tr><td nowrap>E2E 상태 정합성</td><td nowrap><code>task_id</code>·<code>command_id</code> 기반 결과 추적과 검증 후 재고 반영</td></tr>
  </tbody>
</table>

---

## 13. 통합 결과와 검증

### 13.1 E2E 시나리오 결과

기록된 통합 시나리오에서는 작업 266을 기준으로 작업 생성부터 완료와 재고 반영까지 동일한 `task_id`로 대조했습니다.

<table width="100%">
  <thead><tr><th width="15%" nowrap>시나리오</th><th width="65%" nowrap>검증 내용</th><th width="20%" nowrap>결과</th></tr></thead>
  <tbody>
    <tr><td align="center" nowrap>S01</td><td nowrap>작업 생성과 로봇 배정</td><td align="center" nowrap>PASS</td></tr>
    <tr><td align="center" nowrap>S02</td><td nowrap>자율주행 이동과 도착</td><td align="center" nowrap>PASS</td></tr>
    <tr><td align="center" nowrap>S03</td><td nowrap>적재 evidence</td><td align="center" nowrap>PASS</td></tr>
    <tr><td align="center" nowrap>S04</td><td nowrap>안전 정지와 복구</td><td align="center" nowrap>PASS</td></tr>
    <tr><td align="center" nowrap>S05</td><td nowrap>적재 주행 중 사람 감시</td><td align="center" nowrap>PASS</td></tr>
    <tr><td align="center" nowrap>S06</td><td nowrap>최종 복귀</td><td align="center" nowrap>PASS</td></tr>
    <tr><td align="center" nowrap>S07</td><td nowrap>작업 완료와 재고 반영</td><td align="center" nowrap>PASS</td></tr>
  </tbody>
</table>

<table width="100%">
  <thead><tr><th width="42%" nowrap>통합 지표</th><th width="58%" nowrap>결과</th></tr></thead>
  <tbody>
    <tr><td nowrap>전체 시나리오</td><td nowrap>7/7</td></tr>
    <tr><td nowrap>Evidence gate</td><td nowrap>2/2</td></tr>
    <tr><td nowrap>안전 정지·복구</td><td nowrap>2/2</td></tr>
    <tr><td nowrap>E2E 실행 시간</td><td nowrap>5분 25초</td></tr>
    <tr><td nowrap>작업 완료와 재고 반영</td><td nowrap>동일 시각 확인</td></tr>
  </tbody>
</table>

### 13.2 검증 계층

<table width="100%">
  <thead><tr><th width="25%" nowrap>검증 구분</th><th width="45%" nowrap>확인 범위</th><th width="30%" nowrap>증명하지 않는 범위</th></tr></thead>
  <tbody>
    <tr><td nowrap>자동 테스트</td><td nowrap>API, schema, 인증, 상태 전이, DB와 설정</td><td nowrap>실제 로봇의 물리 동작</td></tr>
    <tr><td nowrap>no-hardware 통합</td><td nowrap>Main·Nav·AI 계약과 기본 E2E 경로</td><td nowrap>실제 Nav2 주행과 Lift 하중</td></tr>
    <tr><td nowrap>시뮬레이션</td><td nowrap>ROS graph, Nav2 goal과 가상 이동</td><td nowrap>실물 센서 오차와 마찰·하중</td></tr>
    <tr><td nowrap>실물 기능 검증</td><td nowrap>camera, localization, 주행, ArUco와 Lift</td><td nowrap>장시간·대규모 운영 안정성</td></tr>
    <tr><td nowrap>실물 E2E</td><td nowrap>요청부터 재고 반영까지 전체 작업</td><td nowrap>모든 조명·배치·장애물 조건</td></tr>
  </tbody>
</table>

no-hardware와 시뮬레이션 성공을 실물 주행이나 물리 적재·하역의 합격으로 사용하지 않습니다. 수치 결과는 사용한 지도, 장비, profile과 측정 조건을 함께 보존해야 합니다.

---

## 14. 빠른 시작

### 14.1 No-hardware 검증

```bash
./scripts/bootstrap-nohardware-envs.sh
./scripts/test-nohardware.sh
```

API, 인증, DB와 Main·Nav·AI 계약을 확인하며 실제 주행과 Lift는 포함하지 않습니다.

### 14.2 통합 Profile 실행

<table width="100%">
  <thead><tr><th width="24%" nowrap>실행 환경</th><th width="38%" nowrap>Profile</th><th width="38%" nowrap>실행 범위</th></tr></thead>
  <tbody>
    <tr><td nowrap>단일 로봇 통합 PC</td><td nowrap><code>tb1-local-e2e</code><br><code>tb2-local-e2e</code></td><td nowrap>Main·UI와 선택 Nav</td></tr>
    <tr><td nowrap>두 로봇 통합 PC</td><td nowrap><code>all-local-e2e</code></td><td nowrap>Main·UI와 TB1·TB2 Nav</td></tr>
    <tr><td nowrap>Main 전용 PC</td><td nowrap><code>main-field</code></td><td nowrap>PostgreSQL·Main·UI</td></tr>
    <tr><td nowrap>Nav 전용 PC</td><td nowrap><code>nav-field-tb1</code><br><code>nav-field-tb2</code></td><td nowrap>선택 로봇 Nav</td></tr>
    <tr><td nowrap>두 로봇 Nav PC</td><td nowrap><code>nav-field-all</code></td><td nowrap>TB1·TB2 Nav</td></tr>
  </tbody>
</table>

```bash
./scripts/sf_stack.sh profiles
./scripts/sf_stack.sh --profile PROFILE_NAME check
./scripts/sf_stack.sh --profile PROFILE_NAME foreground
```

### 14.3 실물 통합 시작

실물 운용은 Robot SBC → AI → Nav → Main 순서로 시작합니다. 최초 설치 시에는 각 서버의 setup과 공통 hostname·credential 점검을 먼저 완료해야 합니다.

```bash
# Robot SBC
ROS_DOMAIN_ID=HARDWARE_DOMAIN WS_SETUP=/path/to/tb3-overlay/install/setup.bash \
  nav-server/scripts/robot_sbc/start_bringup.sh
ROS_DOMAIN_ID=HARDWARE_DOMAIN LIFT_WS_SETUP=/path/to/lift-overlay/install/setup.bash \
  nav-server/scripts/robot_sbc/start_lift_bridge.sh
ROS_DOMAIN_ID=HARDWARE_DOMAIN WS_SETUP=/path/to/tb3-overlay/install/setup.bash \
  nav-server/scripts/robot_sbc/start_camera.sh

# AI PC
cd ai-server
./scripts/vision/sf_lab.sh check low-load
./scripts/vision/sf_lab.sh low-load

# Nav PC — repository root
./scripts/sf_stack.sh --profile nav-field-all check
./scripts/sf_stack.sh --profile nav-field-all foreground

# Main PC — repository root
./scripts/sf_stack.sh --profile main-field check
./scripts/sf_stack.sh --profile main-field foreground
```

실물 명령 전 상태를 확인합니다.

```bash
./scripts/sf_stack.sh status
./scripts/sf_stack.sh smoke

# AI PC
cd ai-server && ./scripts/vision/sf_lab.sh status
```

`localized`, `nav2_ready`, `command_accepting`, Lift `ready`, AI source freshness가 모두 정상일 때만 실물 명령을 보냅니다. 종료 전에는 새 작업을 중지하고 로봇의 물리 정지를 먼저 확인합니다.

```bash
# Main·Nav PC
./scripts/sf_stack.sh down

# AI PC
cd ai-server && ./scripts/vision/sf_lab.sh down

# Robot SBC
nav-server/scripts/robot_sbc/stop_stack.sh
```

---

## 15. 현재 한계와 확장 목표

<table width="100%">
  <thead><tr><th width="46%" nowrap>현재 확보한 기반</th><th width="54%" nowrap>다음 목표</th></tr></thead>
  <tbody>
    <tr><td nowrap>한 대의 로봇으로 Full E2E 검증</td><td nowrap>두 대 이상 동시 배정과 traffic·zone 경합 검증</td></tr>
    <tr><td nowrap>Lift step 제어와 1층 적재·하역</td><td nowrap>2층 승강 정착 시간과 반복 위치 오차 검증</td></tr>
    <tr><td nowrap><code>task_id</code> 기반 보류·복구 추적</td><td nowrap>실패 유형별 복구 단계 자동화</td></tr>
    <tr><td nowrap>전역 Localization과 AMCL 인계</td><td nowrap>fine 단계 연산·대기 병목과 손실 함수 고도화</td></tr>
    <tr><td nowrap>관찰 가능한 checkpoint evidence</td><td nowrap>조명·가림·카메라 위치 변화에 대한 반복 검증</td></tr>
    <tr><td nowrap>no-hardware와 실물 검증 분리</td><td nowrap>장시간 반복 운용과 장애 주입 시험</td></tr>
  </tbody>
</table>

현재 결과는 제한된 물류 공간과 지정된 장비에서 확보한 프로젝트 검증 결과입니다. 산업 현장 적용을 주장하기보다, E2E 물류 자동화에 필요한 책임 분리, 상태 추적, 물리 실행과 검증 구조를 구현하고 확인한 범위로 정의합니다.

---

## 16. 프로젝트 타임라인

### Jira 작업 이력

![Jira 작업 이력](assets/Images/jira-task-history-2026-07-28.png)
프로젝트 기간 [ 5월 25일 ~ 7월 24일 ]
## 17. 프로젝트 기술 스택

### Robot & Middleware

![ROS 2 Jazzy](https://img.shields.io/badge/ROS%202-Jazzy-22314E?style=for-the-badge&logo=ros&logoColor=white)
![TurtleBot3 Burger](https://img.shields.io/badge/TurtleBot3-Burger-0085CA?style=for-the-badge)
![Raspberry Pi 4](https://img.shields.io/badge/Raspberry%20Pi-4-A22846?style=for-the-badge&logo=raspberrypi&logoColor=white)
![OpenCR](https://img.shields.io/badge/OpenCR-Robot%20Controller-00A6A6?style=for-the-badge)
![Arduino](https://img.shields.io/badge/Arduino-Lift%20Control-00878F?style=for-the-badge&logo=arduino&logoColor=white)

### Navigation & Perception

![Nav2](https://img.shields.io/badge/Nav2-Navigation-22314E?style=for-the-badge&logo=ros&logoColor=white)
![AMCL](https://img.shields.io/badge/AMCL-Localization-5A45FF?style=for-the-badge)
![OpenCV](https://img.shields.io/badge/OpenCV-Vision-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white)
![YOLO](https://img.shields.io/badge/YOLO-Object%20Detection-111F68?style=for-the-badge)
![ArUco](https://img.shields.io/badge/ArUco-Precision%20Docking-EF6C00?style=for-the-badge)

### Backend & Data

![Python](https://img.shields.io/badge/Python-Backend-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-REST%20API-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Uvicorn](https://img.shields.io/badge/Uvicorn-ASGI-499848?style=for-the-badge)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)

### Frontend & Streaming

![React](https://img.shields.io/badge/React-Admin%20UI-61DAFB?style=for-the-badge&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-Frontend-3178C6?style=for-the-badge&logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-Build-646CFF?style=for-the-badge&logo=vite&logoColor=white)
![TanStack Query](https://img.shields.io/badge/TanStack%20Query-Server%20State-FF4154?style=for-the-badge&logo=reactquery&logoColor=white)
![WebRTC](https://img.shields.io/badge/WebRTC-Streaming-333333?style=for-the-badge&logo=webrtc&logoColor=white)
![MediaMTX](https://img.shields.io/badge/MediaMTX-Media%20Router-1F6FEB?style=for-the-badge)

### Integration & Validation

![HTTP](https://img.shields.io/badge/HTTP-Server%20Integration-005571?style=for-the-badge)
![HMAC](https://img.shields.io/badge/HMAC-SHA256-6A1B9A?style=for-the-badge)
![Pytest](https://img.shields.io/badge/Pytest-Testing-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-Linting-D7FF64?style=for-the-badge&logo=ruff&logoColor=black)

---

## 18. 보안 및 제외 항목

실제 환경에서는 사용하지만 보안상 GitHub 저장소에는 포함하지 않는 항목입니다.

- PostgreSQL 계정·비밀번호와 실제 데이터베이스 접속 문자열
- Main·Nav·AI·Frame Gateway 간 통신에 사용하는 HMAC 비밀키 (`.secrets/service-hmac.env`)
- SSH 개인 키와 장비별 로그인 정보
- 현장 장비·카메라·스트림의 인증 정보
