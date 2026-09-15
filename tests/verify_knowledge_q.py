# -*- coding: utf-8 -*-
"""knowledge_q 修复验证：查询 IoTDA 产品图谱应检索+结构化呈现（不套模板）"""
import os, sys, json, httpx
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.auth_service import AuthService
from app.utils.auth_utils import create_access_token
user = AuthService.get_user_by_id(3)
TOKEN, _ = create_access_token(user["id"], user["username"], user.get("role", "user"), user.get("token_version", 1))
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

msg = "查询华为云 IoTDA 的产品图谱"
print(f"Q: {msg}\n", flush=True)
ev = None; tools = []; ans = ""
with httpx.Client(timeout=180) as c:
    with c.stream("POST", "http://localhost:8000/api/agent/chat", headers=H,
                  json={"message": msg, "session_id": "kq_verify"}) as r:
        for line in r.iter_lines():
            if line.startswith("event: "):
                ev = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    d = json.loads(line[6:])
                    if ev == "thought":
                        print(f"  [thought] {d.get('text','')[:100]}", flush=True)
                    elif ev == "tool":
                        tools.append(d.get("name") or d.get("tool"))
                        print(f"  [tool] {d.get('name') or d.get('tool')}", flush=True)
                    elif ev == "result":
                        ans = d.get("answer", "") or ""
                except Exception:
                    pass

print(f"\n工具调用: {tools}", flush=True)
print(f"回答长度: {len(ans)}", flush=True)
print(f"是否套模板(含'执行摘要'): {'执行摘要' in ans}", flush=True)
print(f"是否结构化(含列表/小标题): {('-' in ans or '#' in ans or '1.' in ans or '•' in ans)}", flush=True)
print(f"\n=== 回答内容 ===\n{ans[:1200]}", flush=True)
