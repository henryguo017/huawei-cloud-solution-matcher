# -*- coding: utf-8 -*-
"""修复复验脚本"""
import os, sys, json, httpx
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.auth_service import AuthService
from app.utils.auth_utils import create_access_token
user = AuthService.get_user_by_id(3)
TOKEN, _ = create_access_token(user["id"], user["username"], user.get("role", "user"), user.get("token_version", 1))
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def probe(msg, sid, timeout=150):
    ev = None; cid = ""; nq = 0; ans = ""; tools = []
    with httpx.Client(timeout=timeout) as c:
        with c.stream("POST", "http://localhost:8000/api/agent/chat", headers=H,
                      json={"message": msg, "session_id": sid}) as r:
            for line in r.iter_lines():
                if line.startswith("event: "):
                    ev = line[7:].strip()
                elif line.startswith("data: "):
                    try:
                        d = json.loads(line[6:])
                        if ev == "clarify":
                            cid = d.get("clarify_id", ""); nq = len(d.get("questions", []))
                        elif ev == "tool":
                            tools.append(d.get("name") or d.get("tool"))
                        elif ev == "result":
                            ans = d.get("answer", "") or ""
                    except Exception:
                        pass
    return cid, nq, tools, ans


print("[修复①] 澄清触发验证:", flush=True)
cid, nq, _, _ = probe("帮我做个云方案", "verify_1", 90)
print(f"   clarify_id={'有' if cid else '无'} 问题数={nq} => {'PASS' if cid else 'FAIL'}", flush=True)

print("[修复②③④] 文件操作验证:", flush=True)
_, _, tools, ans = probe("帮我看看我上传了哪些文件", "verify_2", 150)
has_file = "13B变频调速" in ans
print(f"   tools={tools} ans_len={len(ans)} 含真实文件列表={has_file} => {'PASS' if has_file else 'FAIL'}", flush=True)
