#!/usr/bin/env bash
# SSH_ASKPASS helper — ROBOT_PW 환경변수로 비번 자동 입력 (sshpass 없을 때)
printf '%s\n' "${ROBOT_PW:-}"
