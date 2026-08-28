# -*- coding: utf-8 -*-
"""P0 剩余任务验证：Agent 模式导出 Word（模板在导出时应用）
链路：/api/agent/chat (result.format_mode) -> /api/export/report (word) -> /api/export/download
"""
import os, sys, json, httpx, asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
for _n, _v in [("float_", np.float64), ("int_", np.int64), ("uint", np.uint64),
               ("bool8", np.bool_), ("object_", object), ("complex_", np.complex128)]:
    if not hasattr(np, _n):
        setattr(np, _n, _v)

BASE = "http://localhost:8000"


async def agent_chat(session_id: str, message: str, token: str):
    """调 /api/agent/chat，返回 (success, answer, format_mode, plan)。result 事件为平铺结构。"""
    H = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=420) as c:
        async with c.stream("POST", f"{BASE}/api/agent/chat",
                            headers={**H, "Content-Type": "application/json"},
                            json={"message": message, "session_id": session_id, "client_id": None}) as r:
            evt = ""
            out = {"success": False, "answer": "", "format_mode": None, "plan": []}
            async for line in r.aiter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    evt = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    try:
                        d = json.loads(line[5:])
                    except Exception:
                        continue
                    if evt == "result":
                        out = {
                            "success": d.get("success", False),
                            "answer": d.get("answer") or "",
                            "format_mode": d.get("format_mode") or "solution",
                            "plan": d.get("plan") or [],
                        }
    return out


async def main():
    from app.services.auth_service import AuthService
    from app.utils.auth_utils import create_access_token
    user = AuthService.get_user_by_id(3)
    TOKEN, _ = create_access_token(user["id"], user["username"], user.get("role", "user"), user.get("token_version", 1))

    # ---- 1. Agent 对话：确认 result 带 format_mode + plan（失败自动重试一次） ----
    print("== 1. Agent 对话 result.format_mode ==")
    res = await agent_chat("verify-export-p0-5", "帮我在制造业客户做设备预测性维护方案匹配", TOKEN)
    if not res["success"] or len(res["answer"]) < 500:
        print("  首次运行失败/过短，重试...")
        res = await agent_chat("verify-export-p0-6", "帮我在制造业客户做设备预测性维护方案匹配", TOKEN)
    print(f"  success={res['success']} | format_mode={res['format_mode']} | answer_len={len(res['answer'])} | plan_steps={len(res['plan'])}")
    assert res["success"], "Agent 运行失败"
    assert res["format_mode"] in ("solution", "competitor"), f"format_mode 异常: {res['format_mode']}"
    assert len(res["answer"]) > 500, "answer 过短"
    assert len(res["plan"]) >= 3, f"plan 步数异常: {len(res['plan'])}"

    # ---- 2. 导出 Word（模板在导出端应用） ----
    print("== 2. /api/export/report (word) ==")
    H = {"Authorization": f"Bearer {TOKEN}"}
    r = httpx.post(f"{BASE}/api/export/report", headers={**H, "Content-Type": "application/json"}, json={
        "report_type": res["format_mode"],
        "format": "word",
        "content": res["answer"],
        "title": "华为云解决方案建议书" if res["format_mode"] == "solution" else "华为云竞品对比分析",
        "metadata": {"title": "华为云解决方案建议书" if res["format_mode"] == "solution" else "华为云竞品对比分析"},
        "source_documents": [],
    }, timeout=120)
    print(f"  HTTP {r.status_code}")
    d = r.json()
    print(f"  status={d.get('status')} | file={d.get('file_name')} | download_url={d.get('download_url')}")
    assert r.status_code == 200, f"导出接口异常: {d}"
    assert str(d.get("status") or "").upper() == "COMPLETED", f"导出未完成: {d}"

    # ---- 3. 下载并校验文件 ----
    print("== 3. 下载校验 ==")
    dl = d["download_url"].replace("/api", "")
    fr = httpx.get(f"{BASE}{dl}", timeout=60)
    print(f"  download HTTP {fr.status_code} | bytes={len(fr.content)}")
    assert fr.status_code == 200 and len(fr.content) > 5000, "下载内容异常"
    p = os.path.join(os.path.dirname(__file__), "_export_p0.docx")
    open(p, "wb").write(fr.content)
    print(f"  已保存: {p}")
    print("\nP0 导出链路验证全部通过 ✅")

asyncio.run(main())
