#!/usr/bin/env bash
#
# Configure the Navigation PC's DDS runtime for the field LAN.
#
# Robot SBCs may keep Fast DDS.  DDSI interoperability lets the Navigation PC
# use Cyclone DDS, which avoids the Fast DDS / multi-NIC USB Wi-Fi failure seen
# on operator PCs.  The route to the hostname-first peer selects the interface;
# no workstation address is hard-coded.

set -euo pipefail

export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
if [[ "$RMW_IMPLEMENTATION" != rmw_cyclonedds_cpp ]]; then
  echo "[cyclonedds_lan] unsupported Nav PC RMW: ${RMW_IMPLEMENTATION}" >&2
  return 1 2>/dev/null || exit 1
fi

configured_peer_list="${ROS_STATIC_PEERS:-smartfactory-robot1.local;smartfactory-robot2.local}"
route_probe="${SMARTFACTORY_DDS_ROUTE_PROBE:-${configured_peer_list%%[;,]*}}"
route_probe="${route_probe//[[:space:]]/}"
route_ip="$(getent ahostsv4 "$route_probe" 2>/dev/null | awk 'NR == 1 { print $1 }')"
route_ip="${route_ip:-$route_probe}"
route_line="$(ip -o route get "$route_ip" 2>/dev/null | head -n 1 || true)"
lan_interface="$(awk '{ for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit } }' <<<"$route_line")"
lan_address="$(awk '{ for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit } }' <<<"$route_line")"
required_prefix="${SMARTFACTORY_LAN_IPV4_PREFIX:-192.168.30.}"

if [[ -z "$lan_interface" || -z "$lan_address" ]]; then
  echo "[cyclonedds_lan] route lookup failed for ${route_probe} (${route_ip})" >&2
  return 1 2>/dev/null || exit 1
fi
if [[ "$lan_address" != "$required_prefix"* ]]; then
  echo "[cyclonedds_lan] refusing non-field route: peer=${route_probe} src=${lan_address} expected=${required_prefix}x" >&2
  return 1 2>/dev/null || exit 1
fi

peer_mode="${SMARTFACTORY_DDS_PEER_MODE:-lan}"
case "$peer_mode" in
  lan)
    peer_list="$configured_peer_list"
    ;;
  self)
    peer_list="$lan_address"
    ;;
  *)
    echo "[cyclonedds_lan] unsupported peer mode: ${peer_mode}" >&2
    return 1 2>/dev/null || exit 1
    ;;
esac

allow_multicast="${SMARTFACTORY_DDS_ALLOW_MULTICAST:-false}"
case "$allow_multicast" in
  true) multicast_value="true"; discovery_range="SUBNET" ;;
  false) multicast_value="false"; discovery_range="${SMARTFACTORY_ROS_DISCOVERY_RANGE:-LOCALHOST}" ;;
  *)
    echo "[cyclonedds_lan] SMARTFACTORY_DDS_ALLOW_MULTICAST must be true or false" >&2
    return 1 2>/dev/null || exit 1
    ;;
esac

profile_dir="${XDG_RUNTIME_DIR:-/tmp}/smartfactory-cyclonedds"
mkdir -p "$profile_dir"
profile_file="${profile_dir}/lan-${UID}-${lan_interface}-${peer_mode}-multicast-${allow_multicast}.xml"

peer_xml=""
IFS=';,' read -r -a peers <<<"$peer_list"
for peer in "${peers[@]}"; do
  peer="${peer//[[:space:]]/}"
  [[ -z "$peer" ]] && continue
  resolved="$(getent ahostsv4 "$peer" 2>/dev/null | awk 'NR == 1 { print $1 }')"
  resolved="${resolved:-$peer}"
  if [[ "$resolved" != "$required_prefix"* ]]; then
    echo "[cyclonedds_lan] refusing peer outside field LAN: ${peer} -> ${resolved}" >&2
    return 1 2>/dev/null || exit 1
  fi
  peer_xml+="        <Peer Address=\"${peer}\"/>"$'\n'
done

cat >"$profile_file" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<CycloneDDS xmlns="https://cdds.io/config">
  <Domain Id="any">
    <General>
      <Interfaces>
        <NetworkInterface name="${lan_interface}" priority="default" multicast="${multicast_value}"/>
      </Interfaces>
      <AllowMulticast>${multicast_value}</AllowMulticast>
      <DontRoute>true</DontRoute>
    </General>
    <Discovery>
      <Peers>
${peer_xml}      </Peers>
    </Discovery>
  </Domain>
</CycloneDDS>
EOF

export CYCLONEDDS_URI="file://${profile_file}"
export ROS_AUTOMATIC_DISCOVERY_RANGE="$discovery_range"
export ROS_STATIC_PEERS="$peer_list"
export SMARTFACTORY_DDS_LAN_INTERFACE="$lan_interface"
export SMARTFACTORY_DDS_LAN_ADDRESS="$lan_address"
unset FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE

echo "[cyclonedds_lan] mode=${peer_mode} multicast=${allow_multicast} peer=${route_probe} interface=${lan_interface} address=${lan_address}" >&2
