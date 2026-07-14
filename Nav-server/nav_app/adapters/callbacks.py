import json
import time
from typing import Any, Dict
from urllib import error, request
from urllib.parse import urlsplit

from nav_app.config import MAIN_API_BASE
from nav_app.settings import CALLBACK_MAX_ATTEMPTS, CALLBACK_RETRY_BASE_SEC, CALLBACK_TIMEOUT_SEC, MOVEMENT_CALLBACK_TOKEN


def post_json_callback(url: str, payload: Dict[str, Any], label: str = "Callback") -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        print(f"[{label} 경고] invalid callback_url: {url}")
        return False
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if MOVEMENT_CALLBACK_TOKEN:
        headers["X-Movement-Callback-Token"] = MOVEMENT_CALLBACK_TOKEN
    for attempt in range(CALLBACK_MAX_ATTEMPTS):
        req = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=CALLBACK_TIMEOUT_SEC) as response:
                if 200 <= response.status < 300:
                    return True
        except error.HTTPError as exc:
            print(f"[{label} 경고] {url} HTTP {exc.code}")
            if exc.code in (400, 401, 403, 404, 409, 422):
                return False
        except (error.URLError, TimeoutError) as exc:
            print(f"[{label} 경고] {url} 전송 실패: {exc}")
        if attempt + 1 < CALLBACK_MAX_ATTEMPTS:
            time.sleep(CALLBACK_RETRY_BASE_SEC * (2 ** attempt))
    return False


def post_main_callback(path: str, payload: Dict[str, Any]) -> bool:
    """Main Server callback으로 Movement 결과/상태를 보고합니다."""
    if not MAIN_API_BASE:
        return True
    return post_json_callback(f"{MAIN_API_BASE}{path}", payload, label="MainCallback")
