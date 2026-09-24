#!/usr/bin/env python3
"""对已启动的复核服务做 API/HTTP 冒烟。

用法：python3 scripts/smoke_http.py [BASE_URL]
- GET  /healthz        健康响应
- GET  /               复核页
- POST /api/review     无冲突文法
- POST /api/review     移进/归约冲突（悬空 else）
- POST /api/review     归约/归约冲突（双可空前缀）

任一检查失败以退出码 1 结束。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"

CONFLICT_FREE = {
    "terminals": "int float = + ( ) ;",
    "nonterminals": "S T D L",
    "start": "S",
    "productions": "S -> T ;\nT -> D\nD -> L = int\nL -> L + float\nL -> float\n",
}
SHIFT_REDUCE = {
    "terminals": "if then else expr",
    "nonterminals": "S E",
    "start": "S",
    "productions": "S -> if E then S\nS -> if E then S else S\nS -> expr\nE -> expr\n",
}
REDUCE_REDUCE = {
    "terminals": "a",
    "nonterminals": "S A B",
    "start": "S",
    "productions": "S -> A a\nS -> B a\nA -> ε\nB -> ε\n",
}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f" —— {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def wait_healthy(url: str, attempts: int = 30, delay: float = 1.0) -> bool:
    for i in range(attempts):
        try:
            with urllib.request.urlopen(f"{url}/healthz", timeout=3) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8"))
                    if payload.get("status") == "ok":
                        return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        print(f"  等待服务就绪（{i + 1}/{attempts}）……")
        time.sleep(delay)
    return False


def get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.read()


def post(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def main() -> int:
    print(f"== API/HTTP 冒烟：{BASE_URL} ==")
    if not wait_healthy(BASE_URL):
        print("  [FAIL] /healthz 在等待期内未返回 ok")
        return 1
    print("  [PASS] /healthz 返回 {status: ok}")

    status, body = get(f"{BASE_URL}/healthz")
    check("健康路径 HTTP 200", status == 200 and b'"ok"' in body)

    status, body = get(f"{BASE_URL}/")
    check("复核页 HTTP 200 且含标题", status == 200 and "LR(1) 复核".encode() in body)

    status, data = post(f"{BASE_URL}/api/review", CONFLICT_FREE)
    check("无冲突文法：HTTP 200", status == 200)
    ok = bool(data.get("ok")) and data.get("analysis", {}).get("conflict") is None
    check("无冲突文法：ok=true 且无冲突", ok, str(data.get("errors")))
    check(
        "无冲突文法：给出稳定编号项目集",
        len(data.get("analysis", {}).get("states", [])) > 1,
    )

    status, data = post(f"{BASE_URL}/api/review", SHIFT_REDUCE)
    c = (data.get("analysis") or {}).get("conflict") or {}
    check("悬空 else：HTTP 200 且 ok=false", status == 200 and data.get("ok") is False)
    check("移进/归约冲突：kind 正确", c.get("kind") == "shift_reduce", str(c))
    check("移进/归约冲突：展望符为 else", c.get("lookahead") == "else")
    check("移进/归约冲突：状态编号存在", isinstance(c.get("state"), int))
    check("移进/归约冲突：两项动作", len(c.get("actions", [])) == 2)
    check("移进/归约冲突：竞争项目两项", len(c.get("items", [])) == 2)
    check("移进/归约冲突：活前缀证据", bool(c.get("prefix")) and "活前缀" in c.get("evidence", ""))

    status, data = post(f"{BASE_URL}/api/review", REDUCE_REDUCE)
    c = (data.get("analysis") or {}).get("conflict") or {}
    check("归约/归约冲突：kind 正确", c.get("kind") == "reduce_reduce", str(c))
    check("归约/归约冲突：展望符为 a", c.get("lookahead") == "a")
    check("归约/归约冲突：两项归约动作", len(c.get("actions", [])) == 2)
    check("归约/归约冲突：前缀证据", "活前缀" in c.get("evidence", ""))

    if failures:
        print(f"\n冒烟失败：{len(failures)} 项 -> {failures}")
        return 1
    print("\n全部冒烟通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
