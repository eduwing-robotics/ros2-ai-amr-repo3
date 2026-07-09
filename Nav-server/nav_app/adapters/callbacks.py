import json
from typing import Any, Dict
from urllib import error, request

from nav_app.config import MAIN_API_BASE
from nav_app.settings import CALLBACK_TIMEOUT_SEC


def post_json_callback(url: str, payload: Dict[str, Any], label: str = "Callback") -> bool:
    if not url.startswith(("http://", "https://")):
        print(f"[{label} 경고] 지원하지 않는 callback_url scheme: {url}")
        return False

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=CALLBACK_TIMEOUT_SEC) as response:
            if 200 <= response.status < 300:
                return True
            print(f"[{label} 경고] {url} HTTP {response.status}")
    except (error.URLError, TimeoutError) as exc:
        print(f"[{label} 경고] {url} 전송 실패: {exc}")
    return False


def post_main_callback(path: str, payload: Dict[str, Any]) -> bool:
    """Main Server callback으로 Movement 결과/상태를 보고합니다."""
    if not MAIN_API_BASE:
        return True
    return post_json_callback(f"{MAIN_API_BASE}{path}", payload, label="MainCallback")
