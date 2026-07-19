"""책임: Main이 추적하는 Movement Scenario 9단계와 초기 timeline을 소유한다.
비책임: Movement의 Nav2·정렬·리프트 실행과 callback 상태 반영."""

from __future__ import annotations

from typing import Any

BUSINESS_STEPS: tuple[tuple[str, str], ...] = (
    ("LEAVE_HOME", "대기 위치 출차"),
    ("PICKUP_APPROACH", "적재 위치 이동"),
    ("PICKUP_ALIGN", "적재 위치 정밀 접근"),
    ("LOAD", "화물 적재"),
    ("TRANSPORT", "목적 위치 이동"),
    ("DROPOFF_ALIGN", "하역 위치 정밀 접근"),
    ("UNLOAD", "화물 하역"),
    ("RETURN_HOME", "대기 위치 복귀"),
    ("PARK", "대기 위치 주차"),
)
STEP_CODE_TO_INDEX = {code: index for index, (code, _label) in enumerate(BUSINESS_STEPS)}
TRANSFER_ACTION_BY_STEP = {"LOAD": "load", "UNLOAD": "unload"}
UNLOAD_STEP_INDEX = STEP_CODE_TO_INDEX["UNLOAD"]
PARK_STEP_INDEX = STEP_CODE_TO_INDEX["PARK"]


def business_timeline() -> list[dict[str, Any]]:
    return [
        {
            "step_index": index,
            "kind": code,
            "step_code": code,
            "label": label,
            "status": "PENDING",
            "command_id": None,
            "transfer_action": TRANSFER_ACTION_BY_STEP.get(code),
        }
        for index, (code, label) in enumerate(BUSINESS_STEPS)
    ]
