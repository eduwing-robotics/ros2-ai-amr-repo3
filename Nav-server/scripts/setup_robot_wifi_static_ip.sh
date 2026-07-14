#!/usr/bin/env bash
# 로봇 Wi-Fi 망 고정 IP (NetworkManager)
# 가이드: ~/Downloads/ros2-robot-network-static-ip-and-dds.md
#
# 사용:
#   ROBOT_WIFI_IP=192.168.30.12 bash scripts/setup_robot_wifi_static_ip.sh
#   bash scripts/setup_robot_wifi_static_ip.sh --status
#
set -euo pipefail

CONN="${ROBOT_WIFI_CONN:-codelab_robot_team_3_5G}"
IP="${ROBOT_WIFI_IP:-192.168.30.12}"
IFACE="${ROBOT_WIFI_IFACE:-wlx6c4cbccebe39}"

status() {
  nmcli -f DEVICE,STATE,CONNECTION device status
  echo "---"
  ip -br addr show "$IFACE" 2>/dev/null || true
  nmcli -f connection.id,ipv4.method,ipv4.addresses,ipv4.never-default,ipv4.route-metric \
    connection show "$CONN" 2>/dev/null || true
}

if [[ "${1:-}" == "--status" ]]; then
  status
  exit 0
fi

echo "[robot_wifi] connection=$CONN ip=$IP/24 iface=$IFACE"

nmcli con mod "$CONN" \
  connection.interface-name "$IFACE" \
  ipv4.method manual \
  ipv4.addresses "$IP/24" \
  ipv4.gateway "" \
  ipv4.dns "" \
  ipv4.never-default yes \
  ipv4.route-metric 600

echo "[robot_wifi] static config saved. reconnecting Wi-Fi..."
if ! nmcli con up "$CONN"; then
  echo "[robot_wifi] reconnect failed — GUI에서 Wi-Fi 다시 연결하거나:" >&2
  echo "  nmcli con up \"$CONN\" --ask" >&2
  exit 1
fi

sleep 2
status
echo "[robot_wifi] route check:"
ip route get 192.168.30.101 || true
ip route get 192.168.30.102 || true
