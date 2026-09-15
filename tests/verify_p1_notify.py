# -*- coding: utf-8 -*-
"""P1 飞书/钉钉通知本地验证（零外部网络依赖）。

起一个本地 HTTP mock server 接收 webhook POST，复用与飞书/钉钉相同的签名算法校验
到达 payload 的 timestamp+sign 是否正确、Markdown 内容是否含需求/行业/链接。
同时断言「webhook 为空 → 不发送任何请求」（默认关零副作用）。

注：历史入口 notify_match_complete / notify_agent_result 已删除（生产统一走
notify_for_user），本测试直接驱动其内部同一链路：
  _global_targets() → _push_targets(...) → _build_request → _post_json。
钉钉签名自 310000 修复后拼在 URL 查询串（非 body），校验时从 path 解析。

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
import urllib.parse
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

from app.services.notify import (  # noqa: E402
    _sign, _global_targets, _push_targets, _build_markdown, safe_fire,
)

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


def _ding_query_sign(captured_path):
    """钉钉签名在 URL 查询串（310000 修复后），从 mock 收到的 path 解析出来。"""
    q = urllib.parse.urlsplit(captured_path).query
    params = dict(urllib.parse.parse_qsl(q))
    return params.get("timestamp", ""), params.get("sign", "")


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

    # 2) 全局兜底目标推送（等价原 match 完成入口链路）：应触发飞书+钉钉两次 POST
    targets = _global_targets()
    assert len(targets) == 2 and {t["platform"] for t in targets} == {"feishu", "dingtalk"}, \
        f"全局兜底目标构造错误: {targets}"
    text = _build_markdown("为某制造企业做上云方案", "制造", "", "https://cloudsol.cn")
    safe_fire(_push_targets(targets, "cloudsol 方案完成", text))
    assert _wait_captures(2), f"期望 2 次推送，实际 {len(captured)} 次"
    print(f"[OK] 全局兜底链路触发 {len(captured)} 次推送（飞书+钉钉）")

    by_path = {c["path"].split("?")[0]: c for c in captured}
    feishu_raw = by_path.get("/feishu")
    ding_raw = by_path.get("/dingtalk")
    feishu = json.loads(feishu_raw["body"]) if feishu_raw else None
    ding = json.loads(ding_raw["body"]) if ding_raw else None
    assert feishu and feishu.get("msg_type") == "interactive", "飞书 payload 结构错误"
    assert feishu["sign"] == _recompute_sign("feishu-secret-123", feishu["timestamp"]), "飞书 sign 校验失败"
    card_text = feishu["card"]["elements"][0]["content"]
    assert "为某制造企业做上云方案" in card_text and "制造" in card_text and "cloudsol.cn" in card_text, \
        "飞书正文缺需求/行业/链接"
    assert ding and ding.get("msgtype") == "markdown", "钉钉 payload 结构错误"
    # 钉钉签名在 URL 查询串（body 里没有 sign 字段）
    d_ts, d_sign = _ding_query_sign(ding_raw["path"])
    assert d_sign == _recompute_sign("dingtalk-secret-456", d_ts), "钉钉 URL 查询串 sign 校验失败"
    assert "sign" not in ding, "钉钉 body 不应再携带 sign（310000 修复后只在 URL）"
    assert "为某制造企业做上云方案" in ding["markdown"]["text"] and "cloudsol.cn" in ding["markdown"]["text"], \
        "钉钉正文缺需求/链接"
    print("[OK] 飞书 body 签名 / 钉钉 URL 签名均正确、Markdown 含需求+行业+链接")

    # 3) Agent 结果链路（不同文案入口，复用同一适配器）
    captured.clear()
    text2 = _build_markdown("帮政务客户设计灾备方案", title="政务灾备方案", url="https://cloudsol.cn")
    safe_fire(_push_targets(targets, "cloudsol 方案完成", text2))
    assert _wait_captures(2), f"Agent 通知期望 2 次，实际 {len(captured)} 次"
    print(f"[OK] Agent 结果链路触发 {len(captured)} 次推送")

    # 4) 默认关零副作用：清空全局 webhook 后 _global_targets() 应为空 → 不发任何请求
    import app.services.notify as _n
    _n.FEISHU_WEBHOOK = ""
    _n.DINGTALK_WEBHOOK = ""
    captured.clear()
    safe_fire(_push_targets(_global_targets(), "cloudsol 方案完成", "x"))
    time.sleep(1.0)
    assert len(captured) == 0, f"webhook 为空时应不发送，实际 {len(captured)} 次"
    print("[OK] webhook 为空 → 零请求（默认关零副作用）")

    srv.shutdown()
    print("\n✅ P1-A 通知验证全部通过")


if __name__ == "__main__":
    main()
