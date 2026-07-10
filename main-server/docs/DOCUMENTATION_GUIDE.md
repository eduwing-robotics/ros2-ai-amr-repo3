# Documentation Guide

상태: Active
소유: Docs
작성: 2026-06-22 23:59 KST
최종 갱신: 2026-07-10 10:00 KST
목적: 문서 위치(주제축), 길이, 시각자료, 템플릿, 검사 규칙을 통일한다.

## 1. 핵심 원칙

- 루트에는 `README.md`와 `AGENTS.md` 외 Markdown 문서를 만들지 않는다.
- 오래 유지될 기준 문서는 `docs/`에 둔다. 세션·phase 계획·handoff는 `worklog/`에 둔다.
- **문서는 주제(subject) 영역을 먼저 정한다**: `ui-ux`·`api`·`interfaces`·`architecture`(+`db`)·`operations`·`decisions`·`contributing` 중 하나.
- **성숙도(사실/목표/Draft)는 폴더가 아니라 `상태:` 메타로 표시한다.** 같은 폴더 안에서 구현된 사실은 `상태: Active`, 미구현 목표는 `상태: Draft`로 구분한다.
- 한 문서는 하나의 목적만 가진다. 길어지면 새 문서로 나누고 링크한다.
- 기능 설명과 작업 계획을 같은 문서에 섞지 않는다.
- 설계 글을 그대로 복제하지 않는다. **주제는 두 곳에 둘 수 있지만, 같은 문장은 한 곳에만 둔다** — 정본을 링크한다.
- 현재 기준이 아닌 문서는 `worklog/`로 정리하거나 삭제한다.
- `ref/`와 `database/legacy/`는 기준 문서가 아니라 외부 참고 영역이다. `check_docs.sh`가 검사에서 제외한다.
- 런타임 DB, 캐시, 빌드 산출물은 문서 기준이 아니며 git 추적 대상도 아니다.

## 2. 위치 규칙 (주제축)

| 위치 | 역할 |
| --- | --- |
| `README.md` | 프로젝트 설명, 빠른 실행법, 핵심 링크 |
| `docs/README.md` | 청중 라우팅 landing |
| `docs/ui-ux/` | UX 파운데이션·IA·노출 정책. 화면별 문서는 `ui-ux/pages/`(라우트 1개 = 페이지 1개), 자산은 `wireframes/`·`screens/` |
| `docs/api/` | Main REST API 인덱스·명세·계약·규칙 (도메인별) |
| `docs/interfaces/` | **Main 기준** 외부 HTTP 계약(호출·콜백·proxy). Movement는 `interfaces/movement/` |
| `docs/architecture/` | 시스템 개요·오케스트레이션·백엔드/프론트 구조. DB는 `architecture/db/`(단일 진입 + 심화) |
| `docs/operations/` | 실행·운영·장애 대응·배포·마이그레이션·CI |
| `docs/decisions/` | 중요한 결정과 이유(ADR) |
| `docs/contributing/` | 코드 품질·네이밍·문서 가이드. 템플릿은 `contributing/templates/` |
| `docs/assets/` | 문서 이미지 |
| `slides/` | 발표 최종 시각(d2/drawio/svg/png). **기준 문서 아님.** preview/chrome은 gitignore |
| `worklog/phases,sessions,handoff/` | 작업 계획·세션 요약·인수인계 (공개 스냅샷 제외) |

`docs/reference/`는 사용하지 않는다. 발표 산출물은 `slides/`, 빠른 API 참조는 `docs/api/`.

각 영역 `README.md`가 그 안의 개요→심화로 안내한다(2단 점진 공개).

## 3. 헤더 규칙

`README.md`와 `AGENTS.md`를 제외한 모든 문서는 아래 헤더를 사용한다.

- **필수 4개: `상태`·`소유`·`최종 갱신`·`목적`.** `check_docs.sh`가 존재와 `최종 갱신` 형식을 검사한다.
- **`최종 갱신`은 `YYYY-MM-DD HH:MM KST`로 시·분까지 표기한다.** 날짜만은 금지(같은 날 순서 구분). 사유는 본문/`비고:`로 뺀다.
- **손댈 때 시·분으로 보정한다(normalize-on-touch).**
- **선택: `작성`**(최초 생성 시각). 있으면 바꾸지 않는다. 모르면 지어내지 말고 생략한다.

```markdown
# Title

상태: Draft | Active | Superseded | Legacy | External
소유: Backend | Frontend | DB | Ops | Docs | Integration
작성: YYYY-MM-DD HH:MM KST   # 선택 — 알 때만
최종 갱신: YYYY-MM-DD HH:MM KST
목적: 한 문장
```

worklog phase 문서는 위에 더해 `목표: YYYY-MM-DD HH:MM KST | 미정`을 둔다.

## 4. 길이 제한

| 문서 | 최대 줄 수 |
| --- | ---: |
| `docs/ui-ux/*.md` (파운데이션) | 300 |
| `docs/ui-ux/pages/*.md` (화면별) | 180 |
| `docs/api/*.md` | 280 |
| `docs/interfaces/*.md`, `interfaces/movement/*.md` | 300 |
| `docs/architecture/*.md`, `architecture/db/*.md` | 300 |
| `docs/operations/*.md` | 180 |
| `docs/decisions/*.md` | 140 |
| `docs/contributing/*.md`, `contributing/templates/*.md` | 220 |
| `docs/assets/*.md` | 120 |
| `worklog/phases,handoff/*.md` | 180 · `sessions/*.md` 120 |

넘기면 문서를 분리하고 원본엔 목차·링크만 남긴다. 스키마 덤프 등 비-산문 대용량은 정본(`ref/`)을 링크하고 복제하지 않는다.

## 5. 시각자료 (가독성)

- 기준 문서, 특히 **영역 landing `README.md`는 다이어그램 1개**를 상단 근처에 둔다(`check_docs.sh` 비차단 WARN).
- 흐름·시퀀스·관계·구조는 **mermaid**(GitHub 네이티브 렌더·diff 가능)를 기본으로 쓴다.
- 복잡한 계층 다이어그램은 **draw.io**: `.drawio` 소스와 export `.svg`를 함께 커밋한다.
- 실제 UI 캡처만 PNG(`ui-ux/screens/`). 원시 HTML은 GitHub md에서 렌더되지 않으니 쓰지 않는다.

### 5.1 diagram-first (설계·아키텍처)

설계/아키텍처 정본(`architecture/*`, `interfaces/README`, `ui-ux` 파운데이션·IA, `operations/DEVELOPMENT_GUIDE` 등)은 **도표 → 철학 불릿 → 짧은 표 → 세부 링크** 순으로 쓴다.

- 상단에 mermaid 1~3개(토폴로지 / 요청 흐름 / 경계).
- 디자인 철학은 불릿 5~8개. 로컬 변경점·히스토리 산문은 넣지 않는다(ADR·worklog로).
- 사실과 목표는 섞지 않는다. 미구현은 `상태: Draft` 또는 `목표(Draft)` 섹션.
- **예외(리스트 OK):** `api/*` 엔드포인트 명세, `interfaces/movement/*` 계약 표, DBML/DDL 필드 나열.

## 6. 파일명 규칙

- 기준 문서: `UPPER_SNAKE_CASE.md` (폴더가 맥락을 주므로 접두어는 줄인다 — 예: `interfaces/README.md`)
- 결정 기록(`decisions/`): `YYYY-MM-DD-kebab-topic.md`
- phase: `PHASE_00_SHORT_NAME.md` · session: `YYYY-MM-DD-session.md` · handoff: `YYYY-MM-DD-source-target-topic.md`
- `(1)`, `(2)` 같은 복사본 이름은 금지한다.

## 7. 템플릿

새 문서는 빈 파일에서 시작하지 않는다. `docs/contributing/templates/`의 템플릿을 복사한다.

- `ARCHITECTURE_TEMPLATE.md` · `FEATURE_TEMPLATE.md` · `API_TEMPLATE.md` · `OPERATION_TEMPLATE.md` · `DECISION_TEMPLATE.md`
- worklog: `../worklog/templates/PHASE_TEMPLATE.md` 등

## 8. 갱신 책임

- API 변경: `api/API_MAIN.md`와 관련 `api/`·`interfaces/` 문서
- 구현 변경: 관련 `architecture/`·`ui-ux/` 문서(구현 사실 = `상태: Active`)
- 실행 방법 변경: `operations/` 문서
- 폴더 구조 변경: `architecture/REPOSITORY.md`
- DB 변경: `architecture/db/README.md`, `operations/DB_MIGRATION.md`, migration
- 리팩토링 계획/진행: `worklog/phases/`
- legacy/superseded 정리: `worklog/`로 이동하거나 삭제, `docs/README.md`·깨진 링크 갱신

## 9. 검사

문서 변경 후 아래를 실행한다.

```bash
cd <repo-root>
./scripts/tests/check_docs.sh
```

- **ERROR(exit 1)면 커밋하지 않는다.** 위반은 그 변경 안에서 해결한다.
- pre-commit 훅 또는 CI에 연결해 강제한다.
- **코드-문서 드리프트:** 구현이 바뀌면 같은 변경에서 관련 문서(구현 사실)를 최신화한다.

### 커플링 drift 리포터 (비차단 WARN)

`check_docs.sh`는 문서가 설명하는 코드가 문서보다 최근에 바뀌면 WARN으로 넛지한다(달력 나이가 아니라 대상 코드 변경 기준).

| 문서 | 대상 코드 |
| --- | --- |
| `ui-ux/FRONTEND.md` | `frontend/web/src` |
| `api/API_MAIN.md` | `backend/app/api` |
| `architecture/db/README.md` | `database`, `backend/app/db` |
| `architecture/BACKEND.md` | `backend/app/services`, `backend/app/core` |

- WARN은 exit code에 영향이 없다. 내용이 맞으면 `최종 갱신`만 보정해 넛지를 해소한다.
- 새 문서↔코드 쌍은 `check_docs.sh`의 `check_drift` 호출로 추가한다.

코드 변경까지 포함한 전체 확인:

```bash
./scripts/tests/check_all.sh
```
