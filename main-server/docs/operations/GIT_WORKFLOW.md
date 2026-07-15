# Git Workflow

상태: Active
소유: Ops
최종 갱신: 2026-06-30 14:35 KST
목적: 브랜치 모델, 브랜치/커밋 명명 규칙, 머지 방식을 고정한다.

## 1. 브랜치 모델

경량 trunk-based를 따른다. GitFlow(develop/release/hotfix)는 솔로 개발에 과하므로
쓰지 않는다.

- `main`: 항상 동작하는 trunk. 직접 커밋하지 않고 작업 브랜치를 머지한다.
- 작업 브랜치: `main`에서 분기, 짧게 유지, 머지 후 삭제한다.

> 현재 레포는 기본 브랜치가 `master`이고 `main`이 없다. 토대 적용 시 `master`를
> `main`으로 개명하고 이후 본 문서 기준을 따른다.

## 2. 브랜치 명명

```text
<type>/<짧은-주제-kebab>
```

| type | 용도 | 예시 |
| --- | --- | --- |
| `feat` | 새 기능 | `feat/work-order-ui` |
| `fix` | 버그 수정 | `fix/map-marker-drift` |
| `docs` | 문서만 | `docs/git-workflow` |
| `refactor` | 동작 불변 구조 개선 | `refactor/split-routers` |
| `chore` | 빌드/설정/잡일 | `chore/gitignore-db` |

- 한 브랜치는 한 주제만 담는다. 범위가 커지면 분리한다.
- 주제는 영문 kebab-case로 짧게. 이슈 번호가 있으면 `feat/12-work-order-ui`.

## 3. 커밋 메시지

Conventional Commits 형식 + 한국어 요약을 쓴다. 기존 `docs:` 패턴을 표준화한 것이다.

```text
<type>: <한국어 요약 50자 이내>

<본문: 무엇이 아니라 왜 바꿨는지 (선택)>
```

- type은 브랜치 type과 동일 집합(`feat|fix|docs|refactor|chore|test|style`).
- 요약은 마침표 없이, 명령형/요약형으로.
- 한 커밋은 논리적으로 하나의 변경만 담는다. backend/frontend/docs를 한 커밋에
 뭉치지 않는다.
- 본문이 필요하면 요약과 빈 줄로 구분하고 줄당 72자 이내.

좋은 예:

```text
feat: 입출고 요청 화면 추가

운영자가 품목+수량만 입력하면 POST /work-orders를 호출하도록 TaskCreate를 개편.
```

커밋 템플릿은 `.gitmessage`를 사용한다.

```bash
git config commit.template .gitmessage
```

## 4. 머지 방식

- 작업 브랜치 → `main`은 `--no-ff` 머지를 기본으로 한다. 기능 단위가 그래프에
 묶여 보여 이력 가독성과 포트폴리오 설명에 유리하다.

```bash
git switch main
git merge --no-ff feat/work-order-ui
git branch -d feat/work-order-ui
```

- 커밋이 잘게 흩어진 작은 브랜치는 squash 머지로 정리해도 된다.
- `main`은 force-push 하지 않는다. 공유 브랜치 히스토리를 다시 쓰지 않는다.
- rebase는 아직 머지하지 않은 로컬 작업 브랜치 정리에만 쓴다.

## 5. 일상 흐름

```bash
git switch main && git pull # 원격이 있으면
git switch -c feat/<주제> # 작업 브랜치 생성
# ... 작업 + 논리 단위 커밋 ...
./scripts/check_all.sh # 검증 (QUALITY_GATE 기준)
git switch main
git merge --no-ff feat/<주제>
git branch -d feat/<주제>
```

## 6. 추적 제외 (이미 추적 중인 경우)

`.gitignore`에 규칙을 추가해도 이미 추적된 파일은 계속 따라온다. 로컬 파일을 보존하려면 index에서만 제거한다.

```bash
git rm --cached -- backend/data/lms_control.db data/lms_control.db
git rm --cached -- '*.db' 2>/dev/null || true
```

- DB 파일, `.env`, 빌드 산출물, 캐시, 오피스 lock 파일은 추적하지 않는다.
- `.pytest_cache/`, `frontend/web/dist/`, `frontend/web/node_modules/`는 항상 local-only다.
- runtime DB 삭제가 `git status`에 `D`로 보이는 것은 index 제거 의도다. 실제 파일 보존은 `test -e data/lms_control.db`로 확인한다.
- 커밋 전 점검 항목은 [DEVELOPMENT_GUIDE](../contributing/DEVELOPMENT_GUIDE.md)를 따른다.

## 7. 대규모 정리 분류

구조 전환 중 `git status`가 커지면 아래 순서로 분류한다. 각 묶음은 별도 커밋을 권장한다.

| 묶음 | 기준 | 검증 |
| --- | --- | --- |
| runtime/local only | DB, cache, build output | `git rm --cached`, 로컬 파일 존재 확인 |
| 문서 구조 전환 | root/docs/worklog/ref 재배치 | `./scripts/check_docs.sh` |
| DB runtime 전환 | PostgreSQL DDL/seed/repository | `./scripts/check_pg_mvp.sh` |
| backend router/service 분리 | `api/routers`, `services`, schema | backend unittest |
| frontend 구조 전환 | routes, menus, feature directories | `npm run typecheck`, `npm run build` |

삭제 파일은 `rg`로 참조가 남지 않았는지 확인한 뒤 확정한다. 남은 참조는 현재 기준 문서로 바꾸거나, 과거 기록이면 `worklog/`에 둔다.

## 8. 원격 (선택)

원격(GitHub 비공개 레포 권장)을 두면 백업, PR, 코드 리뷰를 쓸 수 있다.

```bash
git remote add origin <repo-url>
git push -u origin main
```

- 외부 push는 코드가 외부 서비스에 공개·인덱싱될 수 있으므로 공개 범위를 먼저 정한다.
- 원격이 생기면 `main`에 직접 push 대신 작업 브랜치 push + PR 검토를 권장한다.
