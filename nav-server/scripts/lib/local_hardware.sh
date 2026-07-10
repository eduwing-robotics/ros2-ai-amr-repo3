#!/usr/bin/env bash
# Shared local-hardware configuration and SSH authentication helpers.

NAV_SERVER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Read connection values as data, never as shell code. Process environment
# values take precedence over config/local-hardware.env.
load_local_hardware_env() {
  local env_file="$NAV_SERVER_ROOT/config/local-hardware.env"
  local line key value
  [[ -r "$env_file" ]] || return 0

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ "$line" =~ ^[[:space:]]*(ROBOT_SSH|ROBOT_PW|ROBOT_WS_SETUP|LIFT_WS_SETUP)=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"
      if (( ${#value} >= 2 )) \
        && [[ "${value:0:1}" == '"' && "${value: -1}" == '"' || "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
        value="${value:1:${#value}-2}"
      fi
      if [[ ! -v "$key" ]]; then
        printf -v "$key" '%s' "$value"
        export "$key"
      fi
    fi
  done < "$env_file"
}

# Configure SSH without placing the password in argv or generated command text.
configure_robot_ssh() {
  local connect_timeout="${1:-8}"
  ROBOT_PW="${ROBOT_PW:-}"
  if [[ -n "$ROBOT_PW" ]] && command -v sshpass >/dev/null 2>&1; then
    export SSHPASS="$ROBOT_PW"
    SSH_CMD=(sshpass -e ssh -o StrictHostKeyChecking=accept-new -o "ConnectTimeout=$connect_timeout")
    SSH_MODE="sshpass"
  else
    SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new -o "ConnectTimeout=$connect_timeout")
    SSH_MODE="key"
  fi
}
