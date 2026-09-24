"""仅依赖标准库的复核 HTTP 服务。

路由：
- GET  /            复核页（静态 SPA）
- GET  /healthz     健康检查（始终 200 JSON）
- POST /api/review  提交文法，返回校验与 LR(1) 分析结果
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .grammar import review

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_MAX_BODY = 1 << 20  # 1 MiB


class Handler(BaseHTTPRequestHandler):
    server_version = "GrammarReview/1.0"

    def log_message(self, fmt, *args):  # 精简访问日志
        self.server.access_log.append("%s - %s" % (self.address_string(), fmt % args))
        if len(self.server.access_log) > 200:
            del self.server.access_log[:100]

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self._send_json({"status": "ok", "service": "grammar-review"})
            return
        if path in ("/", "/index.html"):
            self._serve_file("index.html", "text/html; charset=utf-8")
            return
        if path == "/app.js":
            self._serve_file("app.js", "application/javascript; charset=utf-8")
            return
        if path == "/styles.css":
            self._serve_file("styles.css", "text/css; charset=utf-8")
            return
        self._send_json({"ok": False, "errors": [{"code": "NOT_FOUND", "message": path}]}, 404)

    def _serve_file(self, name: str, content_type: str) -> None:
        try:
            with open(os.path.join(STATIC_DIR, name), "rb") as fh:
                body = fh.read()
        except OSError:
            self._send_json({"ok": False, "errors": [{"code": "NOT_FOUND", "message": name}]}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/review":
            self._send_json({"ok": False, "errors": [{"code": "NOT_FOUND", "message": path}]}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > _MAX_BODY:
            self._send_json(
                {"ok": False, "errors": [{"code": "BAD_REQUEST", "message": "请求体为空或过大"}]},
                413 if length > _MAX_BODY else 400,
            )
            return
        try:
            raw = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("payload must be object")
        except (ValueError, UnicodeDecodeError):
            self._send_json(
                {"ok": False, "errors": [{"code": "BAD_REQUEST", "message": "请求体不是合法 JSON 对象"}]},
                400,
            )
            return
        try:
            result = review(raw)
        except Exception as exc:  # 引擎异常不应击垮服务
            self._send_json(
                {"ok": False, "errors": [{"code": "INTERNAL", "message": f"分析失败：{exc}"}]},
                500,
            )
            return
        self._send_json(result, 200)


def build_server(host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.access_log = []
    return server


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    server = build_server(host, port)
    print(f"grammar-review listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
