# 동작 정의 (/admin/actions)

상태: Draft
소유: Frontend
최종 갱신: 2026-07-09 15:06 KST
목적: `/admin/actions` 동작 정의 화면의 목표를 기록한다(미구현 placeholder).

## 현황

- 라우트 `/admin/actions`는 **placeholder**다. 메뉴에는 노출하지 않는다.
- 목표: `action_type` + 파라미터(`ActionDefinitions.tsx`, `action_definitions` API)를 관리자가 정의해 시나리오·명령에 사용.
- 현재 `action_type`은 프론트 `constants.ts`에 하드코딩돼 있고, DB 승격은 목표 DB 범위 밖이다([architecture/db](../../architecture/db/README.md)).

## Backlog

구현 계획은 [FRONTEND § Backlog](../FRONTEND.md#backlog)(동작 정의 화면)를 본다.
