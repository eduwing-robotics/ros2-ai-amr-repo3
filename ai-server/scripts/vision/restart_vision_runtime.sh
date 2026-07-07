#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROFILE="lab-gopro-tb3-low-load"
OVERRIDE_FILE=""
DELAY_SEC="1"
RUN_ID="manual"
GIT_PULL="false"
REQUIRE_CLEAN_GIT="true"

usage() {
  cat << USAGE
Usage: $(basename "$0") --profile lab-gopro-tb3-low-load --override-file <env-file> [--delay-sec 1] [--run-id id] [--git-pull]

Lab-only detached helper used by the AI Server operator runtime-control API.
It waits briefly so the HTTP response can return, optionally updates the current
branch with git pull --ff-only, stops the current Vision runtime, and starts the
low-load profile with SF_VISION_RUNTIME_OVERRIDE_FILE applied.

Safety boundary: this helper only restarts the local Vision runtime; it does not
start robot motion, Nav2, teleop, /cmd_vel, ROS parameter mutation, or DB writes.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile)
      PROFILE="${2:-}"
      shift 2
      ;;
    --override-file)
      OVERRIDE_FILE="${2:-}"
      shift 2
      ;;
    --delay-sec)
      DELAY_SEC="${2:-}"
      shift 2
      ;;
    --run-id)
      RUN_ID="${2:-}"
      shift 2
      ;;
    --git-pull)
      GIT_PULL="true"
      shift
      ;;
    --require-clean-git)
      REQUIRE_CLEAN_GIT="true"
      shift
      ;;
    --allow-dirty-git)
      REQUIRE_CLEAN_GIT="false"
      shift
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "${PROFILE}" in
  low-load | lowload | lite) PROFILE="lab-gopro-tb3-low-load" ;;
  lab-gopro-tb3-low-load) ;;
  *)
    echo "ERROR: restart helper only supports lab-gopro-tb3-low-load, got: ${PROFILE}" >&2
    exit 2
    ;;
esac

if [ -z "${OVERRIDE_FILE}" ] || [ ! -f "${OVERRIDE_FILE}" ]; then
  echo "ERROR: override file not found: ${OVERRIDE_FILE:-<empty>}" >&2
  exit 2
fi

case "${DELAY_SEC}" in
  '' | *[!0-9.]*)
    echo "ERROR: --delay-sec must be numeric: ${DELAY_SEC}" >&2
    exit 2
    ;;
esac

cd "${ROOT_DIR}"

RESULT_DIR="$(dirname "${OVERRIDE_FILE}")"
RESULT_FILE="${RESULT_DIR}/${RUN_ID}.result.json"
LAST_RESULT_FILE="${RESULT_DIR}/last_result.json"
STARTED_AT="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
GIT_BRANCH_BEFORE=""
GIT_HEAD_BEFORE=""
GIT_STATUS_BEFORE=""
GIT_PULL_EXIT_CODE=""
GIT_PULL_OUTPUT=""
GIT_PULL_COMMAND=""
GIT_BRANCH_AFTER=""
GIT_HEAD_AFTER=""
TMUX_TARGET_PANE=""
TMUX_TARGET_CONTEXT=""
TMUX_PASTE_STATUS=""
RESULT_FINALIZED="false"
RESULT_STAGE_NAME="initializing"

current_git_branch() {
  git branch --show-current 2> /dev/null || true
}

current_git_head() {
  git rev-parse --short HEAD 2> /dev/null || true
}

current_git_status_short() {
  git status --short 2> /dev/null || true
}

write_result() {
  local status="$1"
  local stage="$2"
  local error="${3:-}"
  RESULT_STAGE_NAME="${stage}"
  mkdir -p "${RESULT_DIR}"
  RESULT_STATUS="${status}" RESULT_STAGE="${stage}" RESULT_ERROR="${error}" RESULT_UPDATED_AT="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" RESULT_RUN_ID="${RUN_ID}" RESULT_PROFILE="${PROFILE}" RESULT_STARTED_AT="${STARTED_AT}" RESULT_GIT_PULL_REQUESTED="${GIT_PULL}" RESULT_REQUIRE_CLEAN_GIT="${REQUIRE_CLEAN_GIT}" RESULT_GIT_BRANCH_BEFORE="${GIT_BRANCH_BEFORE}" RESULT_GIT_HEAD_BEFORE="${GIT_HEAD_BEFORE}" RESULT_GIT_STATUS_BEFORE="${GIT_STATUS_BEFORE}" RESULT_GIT_PULL_EXIT_CODE="${GIT_PULL_EXIT_CODE}" RESULT_GIT_PULL_OUTPUT="${GIT_PULL_OUTPUT}" RESULT_GIT_PULL_COMMAND="${GIT_PULL_COMMAND}" RESULT_GIT_BRANCH_AFTER="${GIT_BRANCH_AFTER}" RESULT_GIT_HEAD_AFTER="${GIT_HEAD_AFTER}" RESULT_GIT_STATUS_AFTER="$(current_git_status_short)" RESULT_TMUX_TARGET_PANE="${TMUX_TARGET_PANE}" RESULT_TMUX_TARGET_CONTEXT="${TMUX_TARGET_CONTEXT}" RESULT_TMUX_PASTE_STATUS="${TMUX_PASTE_STATUS}" python3 - "${RESULT_FILE}" "${LAST_RESULT_FILE}" << 'PYRESULT'
import json
import os
import sys
from pathlib import Path

result_file = Path(sys.argv[1])
last_result_file = Path(sys.argv[2])

def env(name: str) -> str:
    return os.environ.get(name, "")

def bool_env(name: str) -> bool:
    return env(name).lower() == "true"

def split_lines(value: str) -> list[str]:
    return [line for line in value.splitlines() if line]

payload = {
    "schema_version": "smartfactory-operator-runtime-control-result.v1",
    "run_id": env("RESULT_RUN_ID"),
    "profile": env("RESULT_PROFILE"),
    "started_at": env("RESULT_STARTED_AT"),
    "updated_at": env("RESULT_UPDATED_AT"),
    "status": env("RESULT_STATUS"),
    "stage": env("RESULT_STAGE"),
    "git_pull_requested": bool_env("RESULT_GIT_PULL_REQUESTED"),
    "require_clean_git": bool_env("RESULT_REQUIRE_CLEAN_GIT"),
    "git": {
        "branch_before": env("RESULT_GIT_BRANCH_BEFORE") or None,
        "head_before": env("RESULT_GIT_HEAD_BEFORE") or None,
        "status_before": split_lines(env("RESULT_GIT_STATUS_BEFORE")),
        "pull_command": env("RESULT_GIT_PULL_COMMAND") or None,
        "pull_exit_code": int(env("RESULT_GIT_PULL_EXIT_CODE")) if env("RESULT_GIT_PULL_EXIT_CODE") else None,
        "pull_output_tail": split_lines(env("RESULT_GIT_PULL_OUTPUT"))[-40:],
        "branch_after": env("RESULT_GIT_BRANCH_AFTER") or None,
        "head_after": env("RESULT_GIT_HEAD_AFTER") or None,
        "status_after": split_lines(env("RESULT_GIT_STATUS_AFTER")),
    },
    "tmux": {
        "target_pane": env("RESULT_TMUX_TARGET_PANE") or None,
        "target_context": env("RESULT_TMUX_TARGET_CONTEXT") or None,
        "paste_status": env("RESULT_TMUX_PASTE_STATUS") or None,
    },
}
if env("RESULT_ERROR"):
    payload["error"] = env("RESULT_ERROR")
result_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
last_result_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PYRESULT
}

finalize_unexpected_failure() {
  local exit_code="$?"
  if [ "${RESULT_FINALIZED}" != "true" ]; then
    write_result "failed" "${RESULT_STAGE_NAME:-unexpected_failure}" "helper exited with status ${exit_code}"
  fi
  exit "${exit_code}"
}
trap finalize_unexpected_failure ERR

current_tmux_context() {
  if [ -z "${TMUX:-}" ] || ! command -v tmux > /dev/null 2>&1; then
    return 1
  fi
  if [ -n "${TMUX_PANE:-}" ]; then
    tmux display-message -p -t "${TMUX_PANE}" '#S:#I:#W' 2> /dev/null && return 0
  fi
  tmux display-message -p '#S:#I:#W' 2> /dev/null
}

tmux_pane_context() {
  local pane="$1"
  if [ -z "${pane}" ] || ! command -v tmux > /dev/null 2>&1; then
    return 1
  fi
  tmux display-message -p -t "${pane}" '#S:#I:#W' 2> /dev/null
}

preflight_tmux_context_before_destructive_steps() {
  case "${SF_VISION_TMUX_GUARD_ENABLED:-false}" in
    0 | false | FALSE | no | NO | off | OFF) return 0 ;;
  esac
  local required current
  required="${SF_VISION_TMUX_REQUIRED_CONTEXT:-Smartfactory:3:Development}"
  current="$(current_tmux_context || true)"
  if [ "${current}" = "${required}" ]; then
    return 0
  fi
  cat >&2 << ERROR
ERROR: refusing remote restart before stopping current runtime because tmux context is not ${required}.
Current context: ${current:-<not inside tmux>}
Start the laptop low-load runtime from the required tmux pane once, then retry runtime-control.
ERROR
  write_result "failed" "tmux_context_preflight_failed" "current tmux context is ${current:-<not inside tmux>}; required ${required}"
  RESULT_FINALIZED="true"
  exit 4
}

runtime_tmux_target_pane() {
  printf '%s\n' "${SF_RUNTIME_CONTROL_TMUX_PANE:-${TMUX_PANE:-}}"
}

preflight_runtime_target_pane() {
  case "${SF_VISION_TMUX_GUARD_ENABLED:-false}" in
    0 | false | FALSE | no | NO | off | OFF) return 0 ;;
  esac
  local required target target_context
  required="${SF_VISION_TMUX_REQUIRED_CONTEXT:-Smartfactory:3:Development}"
  target="$(runtime_tmux_target_pane)"
  target_context="$(tmux_pane_context "${target}" || true)"
  if [ -n "${target}" ] && [ "${target_context}" = "${required}" ]; then
    return 0
  fi
  cat >&2 << ERROR
ERROR: refusing remote restart because target tmux pane is not in ${required}.
Target pane: ${target:-<empty>}
Target context: ${target_context:-<unavailable>}
Start the laptop low-load runtime from the required tmux pane once, then retry runtime-control.
ERROR
  TMUX_TARGET_PANE="${target}"
  TMUX_TARGET_CONTEXT="${target_context}"
  write_result "failed" "tmux_target_preflight_failed" "target tmux context is ${target_context:-<unavailable>}; required ${required}"
  RESULT_FINALIZED="true"
  exit 4
}

shell_quote() {
  printf '%q' "$1"
}

append_env_assignment() {
  local name="$1"
  if [ -n "${!name+x}" ]; then
    LAUNCH_COMMAND+=" ${name}=$(shell_quote "${!name}")"
  fi
}

build_launch_command() {
  LAUNCH_COMMAND="cd $(shell_quote "${ROOT_DIR}") && env -u VISION_STREAM_SOURCE_UPSTREAMS_JSON"
  for name in \
    SF_RUNTIME_CONTROL_ENABLED \
    SF_RUNTIME_CONTROL_TOKEN \
    SF_VISION_TMUX_GUARD_ENABLED \
    SF_VISION_TMUX_REQUIRED_CONTEXT \
    AI_SERVER_HOST \
    AI_SERVER_PORT \
    AI_SERVER_URL \
    VISION_MODEL_WORKER_ENABLED \
    VISION_MODEL_PATH \
    VISION_MODEL_TASK \
    VISION_MODEL_DEVICE \
    VISION_MODEL_IMGSZ \
    VISION_MODEL_CONF \
    VISION_MODEL_IOU \
    VISION_GATEWAY_REQUEST_TIMEOUT_SEC; do
    append_env_assignment "${name}"
  done
  LAUNCH_COMMAND+=" SF_VISION_RUNTIME_OVERRIDE_FILE=$(shell_quote "${OVERRIDE_FILE}")"
  LAUNCH_COMMAND+=" SF_RUNTIME_CONTROL_RUN_ID=$(shell_quote "${RUN_ID}")"
  LAUNCH_COMMAND+=" ./scripts/vision/sf_vision.sh up $(shell_quote "${PROFILE}")"
}

start_runtime_in_tmux_pane() {
  local target buffer loaded
  target="$(runtime_tmux_target_pane)"
  TMUX_TARGET_PANE="${target}"
  TMUX_TARGET_CONTEXT="$(tmux_pane_context "${target}" || true)"
  RESULT_STAGE_NAME="tmux_target_preflight"
  preflight_runtime_target_pane
  build_launch_command
  buffer="sf-runtime-control-${RUN_ID}"
  RESULT_STAGE_NAME="tmux_buffer_load"
  tmux set-buffer -b "${buffer}" -- "${LAUNCH_COMMAND}"
  loaded="$(tmux show-buffer -b "${buffer}")"
  if [ "${loaded}" != "${LAUNCH_COMMAND}" ]; then
    echo "ERROR: tmux buffer verification failed for ${buffer}" >&2
    write_result "failed" "tmux_buffer_verification_failed" "tmux named buffer did not match launch command"
    RESULT_FINALIZED="true"
    exit 5
  fi
  RESULT_STAGE_NAME="tmux_paste"
  tmux send-keys -t "${target}" C-u
  tmux paste-buffer -t "${target}" -b "${buffer}" -p -d
  tmux send-keys -t "${target}" Enter
  TMUX_PASTE_STATUS="ok"
  echo "[runtime-control] pasted restart command into tmux pane ${target}"
}

GIT_BRANCH_BEFORE="$(current_git_branch)"
GIT_HEAD_BEFORE="$(current_git_head)"
GIT_STATUS_BEFORE="$(current_git_status_short)"
write_result "running" "scheduled"

preflight_tmux_context_before_destructive_steps
write_result "running" "preflight_ok"

echo "[runtime-control] run_id=${RUN_ID} profile=${PROFILE} override=${OVERRIDE_FILE} delay=${DELAY_SEC}s git_pull=${GIT_PULL} require_clean_git=${REQUIRE_CLEAN_GIT}"
echo "[runtime-control] sleeping before restart so API response can return"
sleep "${DELAY_SEC}"

if [ "${GIT_PULL}" = "true" ]; then
  echo "[runtime-control] checking git state before pull"
  if [ "${REQUIRE_CLEAN_GIT}" = "true" ] && [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: git working tree is dirty; refusing remote pull/restart" >&2
    git status --short >&2 || true
    write_result "failed" "git_dirty" "git working tree is dirty; refusing remote pull/restart"
    RESULT_FINALIZED="true"
    exit 3
  fi
  local_branch="${GIT_BRANCH_BEFORE:-$(current_git_branch)}"
  git_remote="${SF_RUNTIME_CONTROL_GIT_REMOTE:-origin}"
  if [ -n "${local_branch}" ]; then
    GIT_PULL_COMMAND="git pull --ff-only ${git_remote} ${local_branch}"
  else
    GIT_PULL_COMMAND="git pull --ff-only"
  fi
  echo "[runtime-control] ${GIT_PULL_COMMAND}"
  RESULT_STAGE_NAME="git_pull"
  trap - ERR
  set +e
  if [ -n "${local_branch}" ]; then
    GIT_PULL_OUTPUT="$(git pull --ff-only "${git_remote}" "${local_branch}" 2>&1)"
  else
    GIT_PULL_OUTPUT="$(git pull --ff-only 2>&1)"
  fi
  GIT_PULL_EXIT_CODE="$?"
  set -e
  trap finalize_unexpected_failure ERR
  printf '%s\n' "${GIT_PULL_OUTPUT}"
  GIT_BRANCH_AFTER="$(current_git_branch)"
  GIT_HEAD_AFTER="$(current_git_head)"
  if [ "${GIT_PULL_EXIT_CODE}" != "0" ]; then
    write_result "failed" "git_pull_failed" "git pull --ff-only exited ${GIT_PULL_EXIT_CODE}"
    RESULT_FINALIZED="true"
    exit "${GIT_PULL_EXIT_CODE}"
  fi
  write_result "running" "git_pulled"
else
  GIT_BRANCH_AFTER="$(current_git_branch)"
  GIT_HEAD_AFTER="$(current_git_head)"
fi

echo "[runtime-control] stopping existing Vision runtime"
RESULT_STAGE_NAME="runtime_down"
./scripts/vision/sf_vision.sh down || true
write_result "running" "runtime_stopped"

echo "[runtime-control] starting ${PROFILE} with override file in the operator tmux pane"
start_runtime_in_tmux_pane
GIT_BRANCH_AFTER="$(current_git_branch)"
GIT_HEAD_AFTER="$(current_git_head)"
write_result "succeeded" "restart_pasted"
RESULT_FINALIZED="true"
