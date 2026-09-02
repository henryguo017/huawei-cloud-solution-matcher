# -*- coding: utf-8 -*-
"""P1 多用户通知绑定本地验证（不依赖网络/服务器）。

覆盖：绑定/列表脱敏/个人绑定返回 secret/notify_for_user 按用户推送/
全局兜底去重/解绑/测试发送。使用临时 DB + 打桩推送，零副作用。
"""
import os
import sys
import time
import sqlite3
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import app.services.notify as notify

# ---- 临时 DB（绕过项目固定路径）----
tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "users.db")


def fake_conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


c = fake_conn()
c.execute(
    "CREATE TABLE IF NOT EXISTS user_notify_bindings ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, platform TEXT, "
    "webhook TEXT, secret TEXT DEFAULT '', enabled INTEGER DEFAULT 1, "
    "created_at DATETIME DEFAULT (datetime('now','localtime')), "
    "updated_at DATETIME DEFAULT (datetime('now','localtime')), "
    "UNIQUE(user_id, platform))"
)
c.commit()
c.close()
notify._db_conn = fake_conn

# ---- 打桩：捕获推送目标 + 屏蔽真实网络 ----
captured = []


async def fake_push(targets, title, text):
    for t in targets:
        captured.append((t["platform"], t["webhook"], t["secret"], title))


notify._push_targets = fake_push
notify._post_json = lambda url, payload: "{}"


def run_push():
    # safe_fire 在无非运行 loop 时走守护线程 asyncio.run，需等待线程执行
    time.sleep(0.6)


def check(name, cond):
    if not cond:
        raise AssertionError("FAIL: " + name)
    print("[OK] " + name)


# 1. 绑定 + 列表脱敏（secret 绝不回传）
notify.save_user_binding(3, "feishu", "https://open.feishu.cn/open-apis/bot/v2/hook/abc123", "mysec", 1)
binds = notify.list_user_bindings(3)
check("列表仅 1 条且 enabled=True", len(binds) == 1 and binds[0]["platform"] == "feishu" and binds[0]["enabled"] is True)
check("列表不泄露 secret", "mysec" not in str(binds))
check("webhook 脱敏（含 **** 且保留末尾）",
      "****" in binds[0]["webhook_masked"] and binds[0]["webhook_masked"].endswith("123"))

# 2. 个人绑定可回取 secret（供推送用）
pb = notify.get_user_bindings(3)
check("get_user_bindings 返回 secret", pb and pb[0]["secret"] == "mysec")

# 3. notify_for_user 推送到个人飞书
captured.clear()
notify.notify_for_user(3, demand="测试需求")
run_push()
check("按用户推送到个人飞书", any(p[0] == "feishu" and p[1].endswith("abc123") for p in captured))

# 4. 全局兜底：用户绑了钉钉，env 全局飞书应补发
notify.FEISHU_WEBHOOK = "https://global/feishu"
notify.FEISHU_SECRET = "gsec"
notify.save_user_binding(3, "dingtalk", "https://oapi.dingtalk.com/robot/send?access_token=dt1", "dtsec", 1)
captured.clear()
notify.notify_for_user(3, demand="x")
run_push()
plats = {p[0] for p in captured}
check("个人钉钉 + 全局飞书都推", "dingtalk" in plats and "feishu" in plats)

# 5. 去重：用户也绑了飞书 → 全局飞书不应重复
notify.save_user_binding(3, "feishu", "https://open.feishu.cn/open-apis/bot/v2/hook/abc123", "mysec", 1)
captured.clear()
notify.notify_for_user(3, demand="x")
run_push()
feishu = [p for p in captured if p[0] == "feishu"]
check("个人飞书存在时全局飞书去重（仅 1 次）",
      len(feishu) == 1 and feishu[0][1].endswith("abc123"))

# 6. 解绑
notify.delete_user_binding(3, "feishu")
check("解绑后无飞书绑定", all(b["platform"] != "feishu" for b in notify.get_user_bindings(3)))

# 7. 测试发送（同步，即时返回）
ok, err = notify.test_user_binding(3, "dingtalk")
check("测试发送成功", ok is True and err == "")

# 7b. 钉钉返回 errcode!=0 时必须识别为失败（不再误报成功）
notify._post_json = lambda url, payload: '{"errcode":31001,"errmsg":"sign not match"}'
ok2, err2 = notify.test_user_binding(3, "dingtalk")
check("钉钉 errcode!=0 被识别为失败", ok2 is False and "31001" in err2)
notify._post_json = lambda url, payload: "{}"  # 复原

# 8. 无绑定无 env → 零推送
notify.FEISHU_WEBHOOK = ""
notify.FEISHU_SECRET = ""
notify.DINGTALK_WEBHOOK = ""
notify.DINGTALK_SECRET = ""
captured.clear()
notify.notify_for_user(999, demand="x")
run_push()
check("无任何绑定时零推送", len(captured) == 0)

print("\n✅ ALL_PERUSER_GREEN")
