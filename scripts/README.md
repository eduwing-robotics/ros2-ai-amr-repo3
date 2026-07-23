# 루트 스크립트 안내

`scripts/`는 Main·Nav·AI를 함께 운용하거나 저장소 전체를 검증할 때 사용하는
통합 진입점입니다. 특별한 설명이 없으면 모든 명령은 **저장소 루트**에서
실행합니다.

실제 장비 운용 순서는 [시작과 종료](../docs/operations/startup-shutdown.md),
입·출고 전체 절차는 [실물 E2E 통합 실행서](../docs/operations/physical-e2e-checklist.md)를
따릅니다. 이 문서는 스크립트의 역할과 진입점만 안내합니다.

## 통합 실행: `sf_stack.sh`

`sf_stack.sh`는 선택한 profile에 맞춰 Main, Nav, UI와 필요한 bridge를 관리합니다.

```bash
./scripts/sf_stack.sh profiles
./scripts/sf_stack.sh --profile tb1-local-e2e print-config
./scripts/sf_stack.sh --profile tb1-local-e2e check
./scripts/sf_stack.sh --profile tb1-local-e2e foreground
```

| 명령 | 용도 |
| --- | --- |
| `profiles` | 사용 가능한 stack profile 목록 |
| `print-config` | 실행 전에 해석된 component·port·URL 확인 |
| `check` | 설정, 필수 파일, port 상태 사전 검사 |
| `foreground` | 소유 component를 현재 terminal에서 시작 |
| `up` | 소유 component를 background로 시작 |
| `status` | 선택 profile의 process·health 확인 |
| `logs` | stack runtime log 확인 |
| `smoke` | 시작된 서비스의 기본 연결 확인 |
| `down` | 해당 stack이 시작한 process group 종료 |

### 주요 profile

| profile | 실행 범위 |
| --- | --- |
| `tb1-local-e2e` | 통합 PC에서 Main/UI + TB1 bridge/Nav |
| `tb2-local-e2e` | 통합 PC에서 Main/UI + TB2 Nav |
| `all-local-e2e` | 통합 PC에서 Main/UI + TB1·TB2 Nav |
| `tb1-synthetic-e2e` | TB1 실제 base/Nav + virtual lift; nonphysical 검증 |
| `main-field` | Main 전용 host |
| `nav-field-tb1`, `nav-field-tb2`, `nav-field-all` | Nav 전용 host |

`foreground`/`up`은 외부 robot SBC bringup과 외부 AI host를 임의로 시작하거나
종료하지 않습니다. 이미 사용 중인 port나 외부 process를 자동으로 종료하지도
않습니다.

## 환경 구성과 사전 점검

| script | 용도 |
| --- | --- |
| `bootstrap-nohardware-envs.sh` | AI·Main·Nav 가상환경과 Main frontend dependency를 no-hardware 검증용으로 준비 |
| `install-smartfactory-hosts.sh --check` | 현장 hostname의 `192.168.30.x` 해석 확인 |
| `install-smartfactory-hosts.sh --print` | 적용할 `/etc/hosts` block 미리 보기 |
| `install-smartfactory-hosts.sh --apply` | SmartFactory hostname block 적용; 필요한 경우만 sudo로 실행 |
| `operator-preflight.sh --software` | 가상환경, ROS/Nav 설정, credential file, Docker, map·port를 read-only로 확인 |
| `operator-preflight.sh --hardware-checklist` | 전체 fleet의 ROS/HTTP health를 read-only로 확인 |

`operator-preflight.sh`는 서비스를 시작하거나 ROS message를 publish하거나 로봇에
이동 명령을 보내지 않습니다.

## no-hardware 검증

| script | 범위 |
| --- | --- |
| `test-nohardware-config.sh` | robot·route·map·bridge·marker·AI source 정적 연결 검사 |
| `test-nohardware.sh` | 서비스 테스트, TCP stack, lifecycle/cleanup, DB seam을 포함한 전체 software 검증 |
| `test-nohardware-tcp.sh` | 임시 Main·Nav·AI·PostgreSQL·built UI를 사용한 TCP 통합 검증 |
| `test-nohardware-db.sh` | 임시 PostgreSQL container를 사용한 예약·복구·동시성 검증 |

전체 검증은 먼저 다음과 같이 환경을 준비합니다.

```bash
./scripts/bootstrap-nohardware-envs.sh
./scripts/test-nohardware.sh
```

no-hardware 결과는 software 통합 결과이며 실물 DDS, localization, 주행, ArUco
도킹, lift 성공을 대신하지 않습니다.

## 문서·evidence 도구

| script | 용도 |
| --- | --- |
| `check_docs.sh` | 문서 경로, 제목, 로컬 link, inventory 구조 검사 |
| `run-e2e-evidence.py` | 지정한 command의 log와 provenance를 E2E evidence manifest로 저장 |

`run-e2e-evidence.py`는 `--provenance physical|simulation|synthetic-hil`를
명시해야 합니다. simulation·synthetic·no-hardware 결과를 physical evidence로
표시하지 않습니다.

## 내부 helper

`scripts/lib/`는 다른 script가 source하는 공통 helper입니다.

- `lib/site_credentials.sh`: 서비스 credential bundle 로드·검증
- `lib/nohardware-process-groups.sh`: no-hardware process group 시작·종료·정리

두 파일은 운영자가 단독 실행하는 진입점이 아닙니다.

서비스 내부 script는 [Main Server](../main-server/README.md),
[Nav Server](../nav-server/README.md), [AI Server](../ai-server/README.md)에서 확인합니다.
