# -*- coding: utf-8 -*-
"""P1-A 飞书/钉钉通知本地验证（零外部网络依赖）。

起一个本地 HTTP mock server 接收 webhook POST，复用与飞书/钉钉相同的签名算法校验
到达 payload 的 timestamp+sign 是否正确、Markdown 内容是否含需求/行业/链接。
同时断言「webhook 为空 → 不发送任何请求」（默认关零副作用）。

运行：python tests/verify_p1_notify.py   （从项目根目录）
"""
import os
import sys
import json
import time
import hmac
import hashlib
import base64
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# 必须在 import notify 之前设好环境变量（notify 在模块加载时读取 webhook/secret）
PORT = _free_port()
os.environ["FEISHU_WEBHOOK"] = f"http://127.0.0.1:{PORT}/feishu"
os.environ["FEISHU_SECRET"] = "feishu-secret-123"
os.environ["DINGTALK_WEBHOOK"] = f"http://127.0.0.1:{PORT}/dingtalk"
os.environ["DINGTALK_SECRET"] = "dingtalk-secret-456"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services.notify import notify_match_complete, notify_agent_result, _sign  # noqa: E402

captured = []


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n) if n else b""
        captured.append({"path": self.path, "body": body})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"code":0,"msg":"ok"}')

    def log_message(self, *a):
        pass


def _recompute_sign(secret, ts):
    s = ts + "\n" + secret
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), s.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")


def _wait_captures(expected, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(captured) >= expected:
            return True
        time.sleep(0.05)
    return len(captured) >= expected


def main():
    srv = HTTPServer(("127.0.0.1", PORT), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    # 1) 签名算法单测
    ts, sign = _sign("feishu-secret-123")
    assert sign == _recompute_sign("feishu-secret-123", ts), "飞书签名算法不一致"
    ts2, sign2 = _sign("dingtalk-secret-456")
    assert sign2 == _recompute_sign("dingtalk-secret-456", ts2), "钉钉签名算法不一致"
    print("[OK] 签名算法与飞书/钉钉公式一致")

    # 2) 经典 match 完成通知：应触发飞书+钉钉两次 POST
    notify_match_complete(demand="为某制造企业做上云方案", industry="制造", url="https://cloudsol.cn")
    assert _wait_captures(2), f"期望 2 次推送，实际 {len(captured)} 次"
    print(f"[OK] match 完成触发 {len(captured)} 次推送（飞书+钉钉）")

    by_path = {c["path"]: json.loads(c["body"]) for c in captured}
    feishu = by_path.get("/feishu")
    ding = by_path.get("/dingtalk")
    assert feishu and feishu.get("msg_type") == "interactive", "飞书 payload 结构错误"
    assert feishu["sign"] == _recompute_sign("feishu-secret-123", feishu["timestamp"]), "飞书 sign 校验失败"
    card_text = feishu["card"]["elements"][0]["content"]
    assert "为某制造企业做上云方案" in card_text and "制造" in card_text and "cloudsol.cn" in card_text, \
        "飞书正文缺需求/行业/链接"
    assert ding and ding.get("msgtype") == "markdown", "钉钉 payload 结构错误"
    assert ding["sign"] == _recompute_sign("dingtalk-secret-456", ding["timestamp"]), "钉钉 sign 校验失败"
    assert "为某制造企业做上云方案" in ding["markdown"]["text"] and "cloudsol.cn" in ding["markdown"]["text"], \
        "钉钉正文缺需求/链接"
    print("[OK] 飞书/钉钉 payload 签名正确、Markdown 含需求+行业+链接")

    # 3) Agent 结果通知（不同入口，复用同一适配器）
    captured.clear()
    notify_agent_result(message="帮政务客户设计灾备方案", answer="长文...", url="https://cloudsol.cn")
    assert _wait_captures(2), f"Agent 通知期望 2 次，实际 {len(captured)} 次"
    print(f"[OK] Agent 结果触发 {len(captured)} 次推送")

    # 4) 默认关零副作用：清空 webhook 后（重新 import 模块级变量）应不发请求
    # notify 在模块加载时读取 webhook；此处用 monkeypatch 模块全局验证 no-op 分支
    import app.services.notify as _n
    _n.FEISHU_WEBHOOK = ""
    _n.DINGTALK_WEBHOOK = ""
    captured.clear()
    notify_match_complete(demand="x")
    time.sleep(1.0)
    assert len(captured) == 0, f"webhook 为空时应不发送，实际 {len(captured)} 次"
    print("[OK] webhook 为空 → 零请求（默认关零副作用）")

    srv.shutdown()
    print("\n✅ P1-A 通知验证全部通过")


if __name__ == "__main__":
    main()
