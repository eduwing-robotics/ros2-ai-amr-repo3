FROM osrf/ros:jazzy-desktop-full

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=jazzy

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    git \
    jq \
    python3-pip \
    python3-venv \
    ros-jazzy-navigation2 \
    ros-jazzy-nav2-bringup \
    ros-jazzy-turtlebot3 \
    ros-jazzy-turtlebot3-gazebo \
    ros-jazzy-turtlebot3-navigation2 \
    ros-jazzy-rmw-cyclonedds-cpp \
    ros-jazzy-domain-bridge \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --break-system-packages \
    fastapi \
    uvicorn \
    requests \
    pydantic

ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
