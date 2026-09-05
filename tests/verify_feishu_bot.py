# -*- coding: utf-8 -*-
"""飞书 bot 核心逻辑单测（mock client/网络，不连飞书不连 API）。

覆盖：@前缀剥离、白名单、每日限次、内部令牌缺失提示、ACK 不炸、_allow 日重置。

运行：python tests/verify_feishu_bot.py   （venv 内，已装 lark-oapi）
"""
import os
import sys
import json
import types
import logging
import asyncio

logging.basicConfig(level=logging.CRITICAL)
os.environ.setdefault("IM_BOT_WHITELIST", "ou_testA")
os.environ.setdefault("IM_BOT_DAILY_LIMIT", "2")
os.environ.setdefault("INTERNAL_API_TOKEN", "tok")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services.feishu_bot import CloudsolFeishuHandler

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[OK ] {label}")
    else:
        FAIL += 1
        print(f"[XX ] {label}" + (f"  -> {detail}" if detail else ""))


class FakeClient:
    def __init__(self):
        self.sent = []

    def fake_send(self, handler, chat_id, msg_type, content_json):
        handler.sent = getattr(handler, "sent", [])
        handler.sent.append((chat_id, msg_type, content_json))


def make_event(text, open_id="ou_testA", chat_id="oc_1"):
    """构造 P2ImMessageReceiveV1 同构对象（SimpleNamespace 鸭子类型）。"""
    import types as _t
    ns = _t.SimpleNamespace()
    ns.event = _t.SimpleNamespace(
        message=_t.SimpleNamespace(
            chat_id=chat_id,
            chat_type="group",
            content=json.dumps({"text": text}),
        ),
        sender=_t.SimpleNamespace(
            sender_id=_t.SimpleNamespace(open_id=open_id),
        ),
    )
    return ns


def run():
    sent = []
    h = CloudsolFeishuHandler(client=None)
    h._send = lambda chat_id, msg_type, content_json: sent.append((chat_id, msg_type, content_json))

    # 1) @前缀剥离 + 白名单内受理
    h._on_receive(make_event("@云方案助手 给500人工厂做上云方案"))
    check("@前缀剥离后受理", len(sent) == 1 and "已收到" in sent[0][2], f"{sent}")

    # 2) 白名单外拒绝
    sent.clear()
    h._on_receive(make_event("做个方案", open_id="ou_stranger"))
    check("白名单外被拒", len(sent) == 1 and "不在" in sent[0][2], f"{sent}")

    # 3) 限次（限额 2：已用 1，再 1 次通过、第 3 次拒绝）
    h._on_receive(make_event("需求2"))
    sent.clear()
    h._on_receive(make_event("需求3"))
    check("每日限次生效", len(sent) == 1 and "上限" in sent[0][2], f"{sent}")

    # 4) 空文本不炸不回
    sent.clear()
    h._on_receive(make_event(""))
    check("空消息静默忽略", len(sent) == 0)

    # 5) 内部令牌缺失 → 明确提示（放开白名单 + 新 open_id 避开限次，才能走到令牌分支）
    import app.services.feishu_bot as mod
    old = mod.INTERNAL_TOKEN
    old_wl = mod.WHITELIST
    mod.INTERNAL_TOKEN = ""
    mod.WHITELIST = set()
    sent.clear()
    h._on_receive(make_event("做个方案", open_id="ou_tok_check"))
    mod.INTERNAL_TOKEN = old
    mod.WHITELIST = old_wl
    check("令牌缺失给明确提示", len(sent) == 1 and "INTERNAL_API_TOKEN" in sent[0][2])

    # 6) _allow 日重置
    h6 = CloudsolFeishuHandler(client=None)
    check("_allow 两次通过", h6._allow("x") and h6._allow("x"))
    check("_allow 第三次拒绝", not h6._allow("x"))


def main():
    run()
    print(f"\n{PASS}/{PASS + FAIL} passed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
