#!/usr/bin/env bash

# Registry of process groups created by the no-hardware runner.  A recorded
# /proc start time prevents a recycled PID from being mistaken for a fixture
# that this shell launched earlier.
declare -Ag NOHARDWARE_OWNED_PROCESS_GROUPS=()

nohardware_process_start_time() {
  local pid="$1"
  local stat_line stat_fields

  [[ -r "/proc/${pid}/stat" ]] || return 1
  IFS= read -r stat_line < "/proc/${pid}/stat" || return 1
  stat_fields="${stat_line##*) }"
  read -r -a stat_fields <<< "${stat_fields}"
  [[ ${#stat_fields[@]} -ge 20 ]] || return 1
  printf '%s\n' "${stat_fields[19]}"
}

nohardware_process_group_has_live_members() {
  local pgid="$1"
  local member_pgid member_state

  while read -r member_pgid member_state; do
    [[ "${member_pgid}" == "${pgid}" ]] || continue
    [[ "${member_state}" == Z* ]] || return 0
  done < <(ps -eo pgid=,stat= 2>/dev/null)
  return 1
}

nohardware_register_process_group() {
  local pid="$1"
  local pgid start_time
  local attempt

  [[ "${pid}" =~ ^[1-9][0-9]*$ ]] || return 1
  pgid=""
  for attempt in {1..50}; do
    pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]' || true)"
    [[ "${pgid}" == "${pid}" ]] && break
    sleep 0.01
  done
  [[ "${pgid}" == "${pid}" ]] || {
    echo "[nohardware-tcp] refusing non-isolated process pid=${pid} pgid=${pgid:-missing}" >&2
    return 1
  }
  start_time="$(nohardware_process_start_time "${pid}")" || return 1
  NOHARDWARE_OWNED_PROCESS_GROUPS["${pid}"]="${start_time}"
}

nohardware_stop_process_group() {
  local pid="$1"
  local expected_start_time="${NOHARDWARE_OWNED_PROCESS_GROUPS[${pid}]:-}"
  local current_start_time pgid
  local owned_group=0
  local attempt

  [[ -n "${expected_start_time}" ]] || return 0
  current_start_time="$(nohardware_process_start_time "${pid}" 2>/dev/null || true)"
  pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ "${current_start_time}" == "${expected_start_time}" && "${pgid}" == "${pid}" ]]; then
    owned_group=1
  elif [[ -z "${current_start_time}" ]] && nohardware_process_group_has_live_members "${pid}"; then
    # The registered leader may crash before the EXIT trap runs.  Its PGID
    # cannot be reused while descendants still belong to that group, so the
    # remaining group is still the one this runner created.
    owned_group=1
  fi
  if [[ ${owned_group} -eq 1 ]]; then
    kill -TERM -- "-${pid}" 2>/dev/null || true
    for ((attempt = 0; attempt < 40; attempt++)); do
      nohardware_process_group_has_live_members "${pid}" || break
      sleep 0.05
    done
    if nohardware_process_group_has_live_members "${pid}"; then
      kill -KILL -- "-${pid}" 2>/dev/null || true
    fi
    wait "${pid}" 2>/dev/null || true
  fi
  unset 'NOHARDWARE_OWNED_PROCESS_GROUPS['"${pid}"']'
}

nohardware_stop_all_process_groups() {
  local pid

  for pid in "${!NOHARDWARE_OWNED_PROCESS_GROUPS[@]}"; do
    nohardware_stop_process_group "${pid}"
  done
}
