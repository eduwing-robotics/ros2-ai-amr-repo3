#!/usr/bin/env python3
"""
Mock Main Server (웹훅 수신 테스트 서버)

Nav 서버의 MAIN_API_BASE 또는 command callback_url을 이 서버로 설정하면
메인 서버/DB 없이도 Movement callback payload를 확인할 수 있습니다.

사용 예:
  python3 scripts/mock_main_server.py --port 8088
  MAIN_API_BASE=http://127.0.0.1:8088/api/v1 python3 scripts/nav_server.py
  callback_url=http://127.0.0.1:8088/api/v1/movement/command-events
"""

import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EVENTS = []
MOVEMENT_RESULTS = []
ROBOT_STATUSES = []


class MockMainServerHandler(BaseHTTPRequestHandler):
    server_version = "MockMainServer/1.0"

    def _send_json(self, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "event_count": len(EVENTS)})
            return
        if self.path == "/events":
            self._send_json(200, {"events": EVENTS})
            return
        if self.path == "/movement/results":
            self._send_json(200, {"results": MOVEMENT_RESULTS})
            return
        if self.path == "/movement/robot-statuses":
            self._send_json(200, {"statuses": ROBOT_STATUSES})
            return
        self._send_json(404, {"detail": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._send_json(400, {"detail": f"invalid json: {exc}"})
            return

        payload["received_at"] = datetime.now(timezone.utc).isoformat()

        if self.path in ("/webhook/robot-status", "/api/v1/movement/command-events"):
            EVENTS.append(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
            self._send_json(200, {"ok": True, "message": "movement command event saved", "event_count": len(EVENTS)})
            return

        if self.path == "/api/v1/movement/results":
            MOVEMENT_RESULTS.append(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
            self._send_json(200, {"ok": True, "message": "movement result accepted"})
            return

        if self.path.startswith("/api/v1/movement/robots/") and self.path.endswith("/status"):
            robot_name = self.path.split("/robots/", 1)[1].rsplit("/status", 1)[0]
            payload["robot_name"] = robot_name
            ROBOT_STATUSES.append(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
            self._send_json(200, {"ok": True, "message": "robot status accepted"})
            return

        self._send_json(404, {"detail": "not found"})

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main():
    parser = argparse.ArgumentParser(description="Mock receiver for Nav server webhooks")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MockMainServerHandler)
    print(f"Mock main server listening on http://{args.host}:{args.port}")
    print(f"Command events endpoint: http://{args.host}:{args.port}/api/v1/movement/command-events")
    print(f"Movement results endpoint: http://{args.host}:{args.port}/api/v1/movement/results")
    print(f"Robot statuses endpoint:  http://{args.host}:{args.port}/movement/robot-statuses")
    print(f"Events endpoint:          http://{args.host}:{args.port}/events")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMock main server stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
