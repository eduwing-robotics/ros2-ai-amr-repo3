# RViz Costmap 표시 설정 전달서

기준일: 2026-07-16
대상: `tb3_2` 실물 Nav2 / RViz
목적: 현재 RViz에서 보이는 깔끔한 global·local costmap을 다른 환경에서도 동일하게 재현

## 1. 실제 사용 파일

- Nav2 파라미터: `config/nav2/burger_smartfactory.yaml`
- EKF 사용 시: `config/nav2/burger_smartfactory_ekf.yaml` — costmap 값은 동일
- 실행 스크립트: `scripts/run_nav2_with_initial_pose.sh`
- RViz 원본: TurtleBot3 패키지의 `rviz/tb3_navigation2.rviz`
- 이 PC에서 확인한 RViz 절대 경로:
  `/home/lucas/turtlebot3_ws/install/turtlebot3_navigation2/share/turtlebot3_navigation2/rviz/tb3_navigation2.rviz`

`scripts/run_nav2_with_initial_pose.sh`는 기본적으로 `burger_smartfactory.yaml`을 사용하고,
`launch/navigation2_labeled.launch.py`는 TurtleBot3의 `tb3_navigation2.rviz`를 로드한다.

## 2. 깔끔하게 보이는 핵심 원리

1. 정적 지도 `/map`을 가장 뒤에 표시한다.
2. global costmap은 Alpha `0.3`으로 얇게 겹친다.
3. local costmap은 Alpha `0.7`로 로봇 주변만 선명하게 표시한다.
4. global costmap에는 `static_layer + inflation_layer`만 활성화한다.
5. 실시간 `/scan` 장애물은 local costmap에서만 `obstacle + voxel + inflation`으로 표시한다.
6. costmap 해상도를 `0.02m`로 사용해 벽과 inflation 경계가 거칠게 보이지 않게 한다.
7. global/local 모두 동일한 footprint와 inflation 값을 사용한다.

중요: global 설정 안에 `obstacle_layer`와 `voxel_layer` 상세값이 작성돼 있어도 현재 `plugins` 목록에는
포함되지 않는다. 따라서 global 화면에는 실시간 스캔 노이즈가 누적되지 않는다. 이 점이 현재 화면이
깔끔한 가장 중요한 이유 중 하나다.

## 3. Nav2 costmap 핵심값

### Local costmap

```yaml
local_costmap:
  local_costmap:
    ros__parameters:
      update_frequency: 5.0
      publish_frequency: 2.0
      global_frame: odom
      robot_base_frame: base_footprint
      transform_tolerance: 1.5
      rolling_window: true
      width: 3
      height: 3
      resolution: 0.02
      footprint: '[[0.120, 0.060], [0.120, -0.060], [-0.120, -0.060], [-0.120, 0.060]]'
      footprint_padding: 0.01
      plugins:
        - obstacle_layer
        - voxel_layer
        - inflation_layer
      inflation_layer:
        plugin: nav2_costmap_2d::InflationLayer
        inflation_radius: 0.18
        cost_scaling_factor: 4.0
        inflate_unknown: false
        inflate_around_unknown: false
      obstacle_layer:
        plugin: nav2_costmap_2d::ObstacleLayer
        enabled: true
        observation_sources: scan
        scan:
          topic: /scan
          clearing: true
          marking: true
          data_type: LaserScan
          obstacle_max_range: 2.5
          raytrace_max_range: 3.0
      voxel_layer:
        plugin: nav2_costmap_2d::VoxelLayer
        enabled: true
        publish_voxel_map: true
        origin_z: 0.0
        z_resolution: 0.05
        z_voxels: 16
        max_obstacle_height: 2.0
        mark_threshold: 0
        observation_sources: scan
        scan:
          topic: /scan
          clearing: true
          marking: true
          data_type: LaserScan
          obstacle_max_range: 2.5
          raytrace_max_range: 3.0
      always_send_full_costmap: true
```

### Global costmap

```yaml
global_costmap:
  global_costmap:
    ros__parameters:
      update_frequency: 1.0
      publish_frequency: 1.0
      global_frame: map
      robot_base_frame: base_footprint
      transform_tolerance: 1.5
      footprint: '[[0.120, 0.060], [0.120, -0.060], [-0.120, -0.060], [-0.120, 0.060]]'
      footprint_padding: 0.01
      resolution: 0.02
      track_unknown_space: false
      plugins:
        - static_layer
        - inflation_layer
      static_layer:
        plugin: nav2_costmap_2d::StaticLayer
        map_subscribe_transient_local: true
        transform_tolerance: 1.5
      inflation_layer:
        plugin: nav2_costmap_2d::InflationLayer
        inflation_radius: 0.18
        cost_scaling_factor: 4.0
        inflate_unknown: false
        inflate_around_unknown: false
      always_send_full_costmap: true
```

## 4. RViz 표시값

RViz의 Fixed Frame은 `map`이다.

### Static Map

```yaml
Class: rviz_default_plugins/Map
Name: Map
Enabled: true
Alpha: 1.0
Color Scheme: map
Draw Behind: true
Topic: /map
Update Topic: /map_updates
Topic QoS Durability: Transient Local
Topic QoS Reliability: Reliable
```

### Global Costmap

```yaml
Class: rviz_default_plugins/Map
Name: Global Costmap
Enabled: true
Alpha: 0.3
Color Scheme: costmap
Draw Behind: false
Topic: /global_costmap/costmap
Update Topic: /global_costmap/costmap_updates
Topic QoS Durability: Transient Local
Topic QoS Reliability: Reliable
Update QoS Durability: Volatile
Update QoS Reliability: Reliable
```

### Local Costmap

```yaml
Class: rviz_default_plugins/Map
Name: Local Costmap
Enabled: true
Alpha: 0.7
Color Scheme: costmap
Draw Behind: false
Topic: /local_costmap/costmap
Update Topic: /local_costmap/costmap_updates
Topic QoS Durability: Transient Local
Topic QoS Reliability: Reliable
Update QoS Durability: Volatile
Update QoS Reliability: Reliable
```

## 5. 확인할 ROS topic

```bash
ros2 topic info /map
ros2 topic info /scan
ros2 topic info /global_costmap/costmap
ros2 topic info /global_costmap/costmap_updates
ros2 topic info /local_costmap/costmap
ros2 topic info /local_costmap/costmap_updates
ros2 topic info /local_costmap/published_footprint
```

정상 기준:

- `/global_costmap/costmap`: publisher 1 이상
- `/local_costmap/costmap`: publisher 1 이상
- `/scan`: publisher 1 이상
- RViz Fixed Frame 오류 없음
- `map → odom → base_footprint` TF 연결 정상

## 6. 적용 시 주의사항

- `inflation_radius`, `footprint`, `resolution`은 단순 화면 꾸미기 값이 아니라 실제 경로 계획과 충돌 판정에
  영향을 준다. RViz 화면만 비슷하게 만들 목적이면 Nav2 YAML을 바꾸지 말고 RViz Alpha와 topic만 적용한다.
- global costmap에 `obstacle_layer`나 `voxel_layer`를 `plugins`로 추가하면 실시간 장애물이 전역 지도에
  표시되지만, 현재보다 화면이 복잡해지고 센서 흔적이 넓게 남을 수 있다.
- local costmap의 Alpha를 `1.0`으로 올리면 로봇 주변이 진해지지만 정적 지도가 가려진다. 현재 `0.7`이
  지도와 장애물을 함께 보기 좋은 값이다.
- simulation 설정 `burger_smartfactory_sim.yaml`은 해상도와 inflation 값이 다르므로 실물 화면 재현에는
  사용하지 않는다.

## 7. 전달용 한 줄 요약

`map`을 뒤에 두고 global `/global_costmap/costmap`은 Alpha 0.3, local
`/local_costmap/costmap`은 Alpha 0.7로 표시하며, 실물 Nav2는 0.02m 해상도와 0.18m inflation을 사용한다.
global은 static+inflation만, local은 obstacle+voxel+inflation을 활성화한다.
