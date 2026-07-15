# 운영 네트워크와 호스트명

운영 서비스 통신은 `hostname-first`이며 `192.168.30.0/24` 현장망만 사용한다.
`192.168.10.0/24` 주소를 서비스 URL, fallback, mDNS 또는 WebRTC ICE 주소로
사용하지 않는다.

## 단일 기준

[`config/network/smartfactory-hosts`](../../config/network/smartfactory-hosts)가
Main, Nav, AI 및 로봇 호스트명의 단일 기준이다.

| 역할 | 호스트명 | 운영 IP |
| --- | --- | --- |
| Main | `smartfactory-main.local` | `192.168.30.9` |
| Nav | `smartfactory-nav.local` | `192.168.30.12` |
| Vision/AI | `smartfactory-vision.local` | `192.168.30.3` |
| Robot 1 | `smartfactory-robot1.local` | `192.168.30.101` |
| Robot 2 | `smartfactory-robot2.local` | `192.168.30.102` |

각 서버에서 동일한 매핑을 적용하고 확인한다.

```bash
sudo ./scripts/install-smartfactory-hosts.sh --apply
./scripts/install-smartfactory-hosts.sh --check
```

애플리케이션 설정, callback, browser URL에는 IP 대신 위 호스트명을 사용한다.
Commissioning을 포함해 runtime IP fallback을 두지 않는다. `192.168.30.x` 직접
접속은 이름 해석 장애를 확인하는 read-only 진단에만 쓰며 service 설정에 저장하지
않는다.

## Main 바인딩

Production Main의 canonical launcher는 저장소 루트의
`main-server/scripts/real.sh`다. 이 스크립트는 공통 hosts 매핑을 확인한 뒤
`smartfactory-main.local`이 이 PC에 할당된 `192.168.30.x` interface로 해석될 때만
Main과 production UI를 bind한다. 이름 해석 실패, 다른 subnet, 다른 PC 주소에서는
시작을 거부하며 `0.0.0.0`이나 직접 IP로 우회하지 않는다.

## AI와 WebRTC

AI 런타임은 `SMARTFACTORY_LAN_IPV4_PREFIX=192.168.30.`을 기본 정책으로
사용한다. 자동 주소 선택과 WebRTC ICE 광고는 이 prefix 밖의 주소를
거부한다. 표준 프로필은 임시 `smartfactory-vision.local` mDNS alias를
게시하지 않는다. 운영 호스트명은 공통 hosts 매핑으로 결정한다.

별도 개발 PC에서 AI를 임시 실행할 때 production 호스트명을 재광고하지 않는다.
해당 PC의 `192.168.30.x` 주소는 직접 진단에만 사용한다.

## 시작 전 확인

```bash
./scripts/install-smartfactory-hosts.sh --check
getent hosts smartfactory-main.local
getent hosts smartfactory-nav.local
getent hosts smartfactory-vision.local
```

세 결과가 각각 `192.168.30.9`, `192.168.30.12`, `192.168.30.3`이 아니면
서비스를 시작하지 않는다.
