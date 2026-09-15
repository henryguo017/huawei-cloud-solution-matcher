# -*- coding: utf-8 -*-
"""验证 P0 重塑：Plan 面板 + 模板降权 + 工具摘要 + 完整性自检"""
import os, sys, json, httpx, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.auth_service import AuthService
from app.utils.auth_utils import create_access_token

user = AuthService.get_user_by_id(3)
TOKEN, _ = create_access_token(user["id"], user["username"], user.get("role", "user"), user.get("token_version", 1))
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def probe(msg, sid, timeout=280):
    print(f"\n{'='*60}\nQ: {msg}")
    t0 = time.time()
    plan = None
    tool_events = []
    has_template = False
    ans = ""
    with httpx.Client(timeout=timeout) as c:
        with c.stream("POST", "http://localhost:8000/api/agent/chat", headers=H,
                      json={"message": msg, "session_id": sid}) as r:
            ev = None
            for line in r.iter_lines():
                if line.startswith("event: "):
                    ev = line[7:].strip()
                elif line.startswith("data: "):
                    try:
                        d = json.loads(line[6:])
                        if ev == "plan":
                            plan = d.get("steps", [])
                            print(f"  [PLAN] {plan}")
                        elif ev == "tool_start":
                            print(f"  [tool_start] {d.get('name') or d.get('tool')}")
                        elif ev == "tool_end":
                            nm = d.get('name') or d.get('tool')
                            sm = d.get('summary', '')
                            tool_events.append((nm, sm))
                            print(f"  [tool_end] {nm} | summary={sm}")
                        elif ev == "result":
                            ans = d.get("answer", "") or ""
                    except Exception:
                        pass
    wall = round(time.time() - t0, 1)
    has_template = "## 1. 执行摘要" in ans or "价值主张：" in ans
    print(f"  [result] wall={wall}s ans_len={len(ans)} 套14章模板={has_template}")
    print(f"  摘要: {ans[:200].replace(chr(10),' ')}")
    return {"plan": plan, "tools": tool_events, "template": has_template, "len": len(ans)}

r1 = probe("帮我在制造业客户做设备预测性维护方案匹配", "p0_verify_1")
print("\n=== 判定 ===")
print(f"Plan 面板: {'✅ 有' if r1['plan'] else '❌ 无'}")
print(f"工具摘要: {'✅ 有' if any(s for _, s in r1['tools']) else '❌ 无'}")
print(f"模板降权(不应套14章): {'✅ 未套模板' if not r1['template'] else '❌ 仍套模板'}")
