# -*- coding: utf-8 -*-
"""密码找回收紧（缺口②）+ 邮箱改绑验证码（缺口①）服务层单测。

不连 SMTP、不依赖生产库：临时 SQLite + monkeypatch 发信函数。

运行：python tests/verify_email_flows.py   （venv 内）
"""
import os
import sys
import sqlite3
import tempfile
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 本地 venv 缺 numpy（已知坑）：app.config 顶部 shim 只用几个类型属性，注入轻量 stub
try:
    import numpy  # noqa: F401
except ImportError:
    import types as _types
    _np_stub = _types.ModuleType("numpy")

    class _FakeNPType:
        pass

    _np_stub.float64 = _FakeNPType
    _np_stub.int64 = _FakeNPType
    _np_stub.uint64 = _FakeNPType
    _np_stub.bool_ = _FakeNPType
    _np_stub.complex128 = _FakeNPType
    sys.modules["numpy"] = _np_stub

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


# ── 临时库：按生产 users 表关键列建表（含新迁移列） ──
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
DB_PATH = _tmp.name

_conn = sqlite3.connect(DB_PATH)
_conn.execute("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE,
        password_hash TEXT NOT NULL,
        reset_token TEXT,
        reset_token_expiry TIMESTAMP,
        pending_email TEXT,
        email_code TEXT,
        email_code_expiry TIMESTAMP
    )
""")
_conn.execute("INSERT INTO users (username, email, password_hash) VALUES ('alice', 'alice@test.com', 'hash_a')")
_conn.execute("INSERT INTO users (username, email, password_hash) VALUES ('bob', 'bob@test.com', 'hash_b')")
_conn.commit()
_conn.close()

# ── monkeypatch：auth_service 的 get_db_connection 指向临时库 ──
import app.services.auth_service as auth_svc
import app.utils.email_utils as email_utils


def _fake_conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


auth_svc.get_db_connection = _fake_conn

# 发信函数默认 mock 为成功；SMTP 视为已配置（用例内按需覆盖）
email_utils.smtp_configured = lambda: True
_sent_reset = []
_sent_codes = []
email_utils.send_reset_email = lambda email, token: _sent_reset.append((email, token)) or True
email_utils.send_email_code = lambda email, code, minutes: _sent_codes.append((email, code, minutes)) or True

from app.services.auth_service import AuthService


def _row(user_id):
    c = _fake_conn()
    r = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    c.close()
    return r


def run():
    # ===== 缺口②：forgot_password 收紧 =====
    # 1) SMTP 未配置 → 查库前统一失败（对所有邮箱一致）
    email_utils.smtp_configured = lambda: False
    r1 = AuthService.forgot_password("alice@test.com")
    check("SMTP未配置→显式失败", r1["success"] is False and "未配置" in r1["message"], str(r1))
    check("SMTP未配置→不写reset_token", _row(1)["reset_token"] is None)
    r1b = AuthService.forgot_password("nobody@test.com")
    check("SMTP未配置→未注册邮箱同样失败(不泄露存在性)", r1b["success"] is False, str(r1b))
    email_utils.smtp_configured = lambda: True

    # 2) 发送失败 → 显式失败（不再静默成功）
    email_utils.send_reset_email = lambda email, token: False
    r2 = AuthService.forgot_password("alice@test.com")
    check("发送失败→显式失败", r2["success"] is False and "失败" in r2["message"], str(r2))

    # 3) 发送成功 → 统一成功文案 + token 落库 + 全流程 reset_password 可用
    email_utils.send_reset_email = lambda email, token: _sent_reset.append((email, token)) or True
    r3 = AuthService.forgot_password("alice@test.com")
    check("发送成功→统一成功文案", r3["success"] is True and "如果该邮箱已注册" in r3["message"], str(r3))
    tok = _row(1)["reset_token"]
    check("reset_token已落库", bool(tok))
    r3b = AuthService.reset_password(tok, "newpass123")
    check("token重置密码成功", r3b["success"] is True, str(r3b))
    check("重置后token清空", _row(1)["reset_token"] is None)

    # 4) 未注册邮箱 + 已配置 → 防探测语义保留
    r4 = AuthService.forgot_password("nobody@test.com")
    check("未注册邮箱→统一成功(防探测)", r4["success"] is True and "如果该邮箱已注册" in r4["message"], str(r4))

    # ===== 缺口①：邮箱改绑验证码 =====
    # 5) 格式错误
    r5 = AuthService.request_email_change(1, "not-an-email")
    check("改绑请求→格式错误拒绝", r5["success"] is False and "格式" in r5["message"], str(r5))

    # 6) 他人已占用
    r6 = AuthService.request_email_change(1, "bob@test.com")
    check("改绑请求→被占用拒绝", r6["success"] is False and "已被其他账号" in r6["message"], str(r6))

    # 7) 正常请求：发码 + pending 落库（6位数字码）
    r7 = AuthService.request_email_change(1, "alice-new@test.com")
    check("改绑请求→成功且带时效文案", r7["success"] is True and "15 分钟内有效" in r7["message"], str(r7))
    row7 = _row(1)
    code7 = row7["email_code"]
    check("验证码6位数字落库", code7 and len(code7) == 6 and code7.isdigit(), repr(code7))
    check("pending_email落库", row7["pending_email"] == "alice-new@test.com")
    check("验证码发到新邮箱", _sent_codes and _sent_codes[-1][0] == "alice-new@test.com")

    # 8) 冷却期重复请求 → 429 语义
    r8 = AuthService.request_email_change(1, "alice-new@test.com")
    check("冷却期重复请求被限流", r8["success"] is False and "retry_after" in r8, str(r8))

    # 9) 验证码错误
    r9 = AuthService.confirm_email_change(1, "alice-new@test.com", "000000" if code7 != "000000" else "111111")
    check("错误验证码被拒", r9["success"] is False and "验证码错误" in r9["message"], str(r9))

    # 10) 邮箱与请求不一致
    r10 = AuthService.confirm_email_change(1, "other@test.com", code7)
    check("邮箱与请求不一致被拒", r10["success"] is False and "不一致" in r10["message"], str(r10))

    # 11) 正确验证码 → 改绑成功 + pending 清理 + 临时库生效
    r11 = AuthService.confirm_email_change(1, "alice-new@test.com", code7)
    check("正确验证码改绑成功", r11["success"] is True and r11.get("email") == "alice-new@test.com", str(r11))
    row11 = _row(1)
    check("改绑后email生效且pending清空",
          row11["email"] == "alice-new@test.com" and row11["pending_email"] is None and row11["email_code"] is None)

    # 12) 过期验证码 → 拒绝并清理 pending（直接写库模拟过期）
    expired = (datetime.datetime.now() - datetime.timedelta(minutes=1)).isoformat()
    c = _fake_conn()
    c.execute(
        "UPDATE users SET pending_email='again@test.com', email_code='123456', email_code_expiry=? WHERE id=1",
        (expired,),
    )
    c.commit()
    c.close()
    r12 = AuthService.confirm_email_change(1, "again@test.com", "123456")
    check("过期验证码被拒并清理", r12["success"] is False and "过期" in r12["message"] and _row(1)["pending_email"] is None, str(r12))

    # 13) 未请求就确认 → 引导先取码
    r13 = AuthService.confirm_email_change(2, "whatever@test.com", "654321")
    check("未请求先确认→引导取码", r13["success"] is False and "先获取验证码" in r13["message"], str(r13))


def main():
    try:
        run()
    finally:
        try:
            os.unlink(DB_PATH)
        except OSError:
            pass
    print(f"\n{PASS}/{PASS + FAIL} passed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
