#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001}"
ROBOT_NAME="${ROBOT_NAME:-tb3_1}"

echo "== robots =="
curl -fsS "$BASE_URL/movement-api/v1/robots" | jq .

echo "== nav-state =="
curl -fsS "$BASE_URL/movement-api/v1/robots/$ROBOT_NAME/nav-state" | jq .

echo "== map-state =="
curl -fsS "$BASE_URL/movement-api/v1/map-state" | jq .
