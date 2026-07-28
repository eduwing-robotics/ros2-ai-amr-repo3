#!/usr/bin/env bash
set -euo pipefail

TB3_1_URL="${TB3_1_URL:-http://localhost:8001}"
TB3_2_URL="${TB3_2_URL:-http://localhost:8002}"

check_one() {
  local label="$1"
  local base_url="$2"
  local robot_name="$3"

  echo "== ${label}: robots =="
  curl -fsS "${base_url}/movement-api/v1/robots" | jq .

  echo "== ${label}: nav-state =="
  curl -fsS "${base_url}/movement-api/v1/robots/${robot_name}/nav-state" | jq .
}

check_one "tb3_burger_01" "$TB3_1_URL" "tb3_1"
check_one "tb3_burger_02" "$TB3_2_URL" "tb3_2"