# Movement Server (Main consumer boundary)

상태: Active
소유: Integration
최종 갱신: 2026-07-10 16:01 KST
목적: Main이 Movement를 소비하는 책임과 정본 계약의 위치를 안내한다.

Main은 작업 순서를 소유하고, 설정된 Movement 대상에 명령을 전달한 뒤 callback과 상태 조회로 실행 결과를 반영한다. Main의 공개 API와 오류 해석은 [API_MAIN](../../api/API_MAIN.md), 운영 진단은 [MOVEMENT_SYNC_DIAGNOSTICS](../../operations/MOVEMENT_SYNC_DIAGNOSTICS.md)를 따른다.

Movement endpoint, payload, 상태값, 호환 경로의 유일한 정본은 Nav Server의 [MAIN_SERVER_CONTRACT](../../../../nav-server/docs/reference/MAIN_SERVER_CONTRACT.md)다. 이 문서는 endpoint를 복제하지 않는다.
