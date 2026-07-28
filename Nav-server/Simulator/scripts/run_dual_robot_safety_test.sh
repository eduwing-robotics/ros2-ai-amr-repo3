#!/usr/bin/env bash
# Reset to both 20cm hold lines, run all safety scenarios, and keep evidence.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK="$SCRIPT_DIR/start_dual_robot_standby.sh"
EVIDENCE="${DUAL_SIM_EVIDENCE:-$SCRIPT_DIR/../generated/dual_robot/latest_safety_evidence.json}"

"$STACK" reset
python3 "$SCRIPT_DIR/run_dual_robot_safety_scenarios.py" \
  --scenario all \
  --evidence "$EVIDENCE" \
  "$@"
echo "[dual_sim] PASS evidence=$EVIDENCE"
echo "[dual_sim] next repeat starts from fresh 20cm lines automatically"
