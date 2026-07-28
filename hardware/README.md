# Hardware 문서

TurtleBot3 기반 물류 로봇의 Lift, Rack, Pallet 기구와 Lift 전장 구현을 정리한다.

## 문서 인덱스

| 문서 | 내용 |
| --- | --- |
| [3D 기구 설계](MECHANICAL_DESIGN.md) | Lift·Rack·Pallet CAD, STEP 파일, 출력물과 층별 높이 |
| [전장 및 배선 설계](WIRING_DESIGN.md) | Step motor, controller, driver, 전원, limit switch와 배선 |

## 설계 자산

| 자산                | 위치                                                                          |
| ----------------- | --------------------------------------------------------------------------- |
| STEP 파일           | [`assets/Cads/`](../assets/Cads/)                                           |
| CAD 렌더            | [`hardware/images/cad/`](images/cad/)                                       |
| 실물 및 공통 이미지       | [`assets/Images/`](../assets/Images/)                                       |

기구 형상·출력·결합 치수는 3D 기구 설계에서, 전기 부품·전원·배선은 전장 및
배선 설계에서 관리한다. 서로 다른 Confluence 문서의 사양이 충돌하면 실물
부품 label과 배선 측정 결과를 확인해 확정한다.
