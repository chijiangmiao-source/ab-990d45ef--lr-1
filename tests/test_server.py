"""HTTP/API/页面测试：健康路径、复核 API、静态页与可访问性基本检查。"""

import json
import os
import sys
import threading
import unittest
import http.client

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.server import build_server  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "app", "static")

CONFLICT_FREE = {
    "terminals": "int float = + ( ) ;",
    "nonterminals": "S T D L",
    "start": "S",
    "productions": "S -> T ;\nT -> D\nD -> L = int\nL -> L + float\nL -> float\n",
}
DANGLING_ELSE = {
    "terminals": "if then else expr",
    "nonterminals": "S E",
    "start": "S",
    "productions": "S -> if E then S\nS -> if E then S else S\nS -> expr\nE -> expr\n",
}


class ServerTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = build_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                     headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data


class HealthAndStaticTests(ServerTestBase):
    def test_healthz(self):
        status, data = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["status"], "ok")

    def test_index_served(self):
        status, data = self.request("GET", "/")
        self.assertEqual(status, 200)
        html = data.decode("utf-8")
        self.assertIn("<html lang=\"zh-CN\"", html)

    def test_assets_served(self):
        for path, ctype in (("/app.js", "javascript"), ("/styles.css", "css")):
            status, data = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertGreater(len(data), 100)

    def test_unknown_route_404_json(self):
        status, _ = self.request("GET", "/nope")
        self.assertEqual(status, 404)

    def test_bad_json_400(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/review", body=b"{not-json",
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        resp.read()
        conn.close()


class ReviewApiTests(ServerTestBase):
    def test_conflict_free_api(self):
        status, data = self.request("POST", "/api/review", CONFLICT_FREE)
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["analysis"]["conflict"])
        self.assertTrue(payload["analysis"]["states"])

    def test_shift_reduce_conflict_api(self):
        status, data = self.request("POST", "/api/review", DANGLING_ELSE)
        payload = json.loads(data)
        self.assertEqual(status, 200)
        self.assertFalse(payload["ok"])
        c = payload["analysis"]["conflict"]
        self.assertEqual(c["kind"], "shift_reduce")
        self.assertEqual(c["lookahead"], "else")
        self.assertEqual(len(c["actions"]), 2)

    def test_reduce_reduce_conflict_api(self):
        grammar = {
            "terminals": "a",
            "nonterminals": "S A B",
            "start": "S",
            "productions": "S -> A a\nS -> B a\nA -> ε\nB -> ε\n",
        }
        status, data = self.request("POST", "/api/review", grammar)
        payload = json.loads(data)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["analysis"]["conflict"]["kind"], "reduce_reduce")


class PageBuildTests(unittest.TestCase):
    """页面构建检查：静态文件自洽且具备可访问性关键要素。"""

    def test_accessibility_markers(self):
        with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        for marker in [
            'lang="zh-CN"',
            'class="skip-link"',
            'aria-live="polite"',
            'role="status"',
            "<title>",
            "for=\"terminals\"",
            "for=\"productions\"",
        ]:
            self.assertIn(marker, html, f"缺少可访问性要素：{marker}")

    def test_js_balanced_and_references_exist(self):
        with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as fh:
            js = fh.read()
        # 基本构建检查：括号配平、关键函数存在、无残留笔误
        self.assertEqual(js.count("{"), js.count("}"))
        self.assertEqual(js.count("("), js.count(")"))
        for token in ["runReview", "cancelReview", "invalidateResults", "AbortController",
                      "localStorage", "renderConflict"]:
            self.assertIn(token, js)
        self.assertNotIn("trtr", js)
        with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('src="/app.js"', html)
        self.assertIn('href="/styles.css"', html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
