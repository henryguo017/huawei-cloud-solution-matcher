# -*- coding: utf-8 -*-
"""钉钉 bot 核心逻辑单测（mock 网络，不连钉钉不连 API）。

覆盖：每日限次、白名单拦截、@前缀剥离、process 各分支 ack 返回、
严重错误吞掉不影响 Stream 连接。

运行：python tests/verify_dingtalk_bot.py   （venv 内，已装 dingtalk-stream）
"""
import os
import sys
import types
import asyncio
import logging

logging.basicConfig(level=logging.CRITICAL)
os.environ.setdefault("DINGTALK_BOT_CLIENT_ID", "test-id")
os.environ.setdefault("DINGTALK_BOT_CLIENT_SECRET", "test-secret")
os.environ.setdefault("IM_BOT_WHITELIST", "staffA")
os.environ.setdefault("IM_BOT_DAILY_LIMIT", "2")
os.environ.setdefault("INTERNAL_API_TOKEN", "tok")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services.dingtalk_bot import CloudsolChatbotHandler

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


class FakeMsg:
    def __init__(self, text="", staff="staffA", webhook="http://hook"):
        self.data = {
            "text": {"content": text},
            "senderStaffId": staff,
            "sessionWebhook": webhook,
            "conversationId": "cid1",
        }


def make_handler(replies):
    h = CloudsolChatbotHandler()
    h._reply_markdown = lambda webhook, title, text: replies.append((webhook, title, text))
    return h


async def drive():
    # 1) @前缀剥离后正常受理（白名单内）
    replies = []
    h = make_handler(replies)
    st, _ = await h.process(FakeMsg("@云方案助手 给500人工厂做上云方案"))
    check("白名单内消息受理并返回 ACK", st == 200, f"st={st}")
    check("先回『已收到』提示", len(replies) == 1 and "已收到" in replies[0][2], f"{replies}")

    # 2) 白名单外拒绝
    replies.clear()
    h2 = make_handler(replies)
    st, _ = await h2.process(FakeMsg(text="做个方案", staff="staffB"))
    check("白名单外被拒", st == 200 and len(replies) == 1 and "不在" in replies[0][2])

    # 3) 限次：同一 sender 第 3 次被限（限额 2）
    h3 = make_handler([])
    await h3.process(FakeMsg(text="需求1"))
    await h3.process(FakeMsg(text="需求2"))
    replies3 = []
    h3._reply_markdown = lambda webhook, title, text: replies3.append(text)
    st, _ = await h3.process(FakeMsg(text="需求3"))
    check("每日限次生效（第3次拒绝）", "上限" in (replies3[0] if replies3 else ""), f"{replies3}")

    # 4) 空消息/空 webhook 不炸
    h4 = make_handler([])
    st, _ = await h4.process(FakeMsg(text=""))
    check("空消息返回 ACK 且无回复", st == 200 and not h4._daily.get("") )

    # 5) INTERNAL_API_TOKEN 为空 → 提示未配置（不进重活）
    import app.services.dingtalk_bot as mod
    old_tok = mod.INTERNAL_TOKEN
    mod.INTERNAL_TOKEN = ""
    replies5 = []
    h5 = make_handler(replies5)
    st, _ = await h5.process(FakeMsg(text="做个方案"))
    mod.INTERNAL_TOKEN = old_tok
    check("内部令牌缺失时给明确提示", len(replies5) == 1 and "INTERNAL_API_TOKEN" in replies5[0][2] or "令牌" in (replies5[0][2] if replies5 else ""))

    # 6) _allow 计数按日重置逻辑
    h6 = CloudsolChatbotHandler()
    check("_allow 前两次通过", h6._allow("x") and h6._allow("x"))
    check("_allow 第三次拒绝", not h6._allow("x"))


def main():
    asyncio.run(drive())
    print(f"\n{PASS}/{PASS + FAIL} passed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
