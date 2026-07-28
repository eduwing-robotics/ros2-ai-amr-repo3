# 테스트 안내

루트 `tests/`에는 여러 서비스가 함께 사용하는 계약·문서·evidence·no-hardware 검증을 둡니다. 각 서비스에만 해당하는 단위 테스트는 해당 서비스 디렉터리의 `tests/`가 소유합니다.

| 경로 | 역할 |
| --- | --- |
| `contracts/` | 서비스 간 동작, 보안과 운영 설정의 정합성 검사 |
| `docs/` | 문서 경로 정책, 제목과 내부 링크 검사 |
| `evidence/` | E2E evidence 기록 도구 검증 |
| [`nohardware/`](nohardware/README.md) | 로봇 장비 없이 Main·Nav·AI를 조립하는 통합 검증 |

## 실행 진입점

저장소 루트에서 목적에 맞는 runner를 실행합니다.

```bash
./scripts/check_docs.sh
./scripts/test-nohardware.sh
```

개별 영역은 pytest로 선택 실행할 수 있습니다.

```bash
python3 -m pytest -q tests/contracts
python3 -m pytest -q tests/docs
python3 -m pytest -q tests/evidence
```

검증 코드와 fixture는 `tests/`, 실행 순서와 환경 구성을 담당하는 runner는 `scripts/`에 둡니다.
