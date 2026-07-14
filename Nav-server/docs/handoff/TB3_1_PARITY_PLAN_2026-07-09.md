# 로봇1 = 로봇2 동일 구성 — 어떻게 할지 (간단판)

작성: 2026-07-09
목표: **tb3_1을 tb3_2와 같은 방식으로** 띄우고, **같은 맵(`robot2_map`)** · 같은 도킹·리프트를 쓴다.

---

## 한눈에 보기

| | 로봇1 (tb3_1) | 로봇2 (tb3_2) |
|--|---------------|---------------|
| API | `:8001` | `:8002` |
| ROS domain | `2` | `5` |
| **맵** | **`robot2_map` (동일)** | **`robot2_map`** |
| 대기장 | `vehicle_1` (marker 3) | `vehicle_2` (marker 4) |
| **SBC** | **`codelab@192.168.30.101`** | **`musk@192.168.30.102`** |
| 런처 | `scripts/start_all_tb3_1.sh` | `scripts/start_all_tb3_2.sh` |

**같은 것:** 맵, `zones.json`, 리프트 높이, 도킹 코드, EKF
**다른 것:** 포트 / domain / 대기장 / SBC IP

---

## 브링업 (로봇1)

```bash
WITH_EKF=1 scripts/start_all_tb3_1.sh restart
scripts/start_all_tb3_1.sh status
```

기본 SSH: `codelab@192.168.30.101` / 비번 `<robot-password>` (로봇2는 `musk@192.168.30.102` / `<robot-password>`)

한 번에 뜨는 것:

```text
[SBC .101]  bringup + 카메라 + lift_bridge
[Nav]       Nav2+RViz (robot2_map) + ArUco + Movement API(:8001)
```

---

## 둘 다

```bash
# 터미널 A — 로봇1 (codelab@.101, :8001)
WITH_EKF=1 scripts/start_all_tb3_1.sh restart

# 터미널 B — 로봇2 (musk@.102, :8002)
WITH_EKF=1 scripts/start_all_tb3_2.sh restart
```

`restart`/`stop`은 **그 로봇만** 끕니다 (상대 Nav2·API 유지).
처음 두 대 올릴 때, 예전에 같이 뜨던 세션이 있으면 **둘 다 stop 한 뒤** 위 순서로 다시 start.

처음엔 **한 대씩** 검증.

---

## LMS

| 파일 | 용도 |
|------|------|
| `MAIN_LMS_HANDOFF_2026-07-09.md` | 공통 |
| `lms_nav_waypoint_map_tb3_1.json` | 로봇1 (HOME=대기1) |
| `lms_nav_waypoint_map_tb3_2.json` | 로봇2 (HOME=대기2) |

로봇1: `robot_id=tb3_1`, URL `:8001`, 대기 marker **3**, SBC **`.101`**.

---

**요약:** 맵 동일(`robot2_map`). 로봇1=`codelab@192.168.30.101`, 로봇2=`musk@192.168.30.102`.
