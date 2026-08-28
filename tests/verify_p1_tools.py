# -*- coding: utf-8 -*-
"""P1-2 验证：generate_doc 拦截导出 + web_search 可插拔（默认关闭降级）

  A. web_search 单元测试（无 LLM）：未配置 WEB_SEARCH_PROVIDER 时优雅降级为 status=disabled。
  B. 流式验证（依赖 localhost:8000）：
     - 先跑一次方案匹配（填充 harness._last_draft），
     - 再说「导出成 Word」→ 触发 export 意图 → 拦截生成 → 收到 doc_generated 事件（带 download_url），
     - 用 download_url 直接下载，校验文件非空。
"""
import os, sys, json, asyncio, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

BASE = "http://localhost:8000"


async def web_search_unit():
    print("=== A. web_search 单元测试（无 LLM） ===")
    from app.agent.tools import _tool_web_search
    out = await _tool_web_search("华为云最新产品动态")
    d = json.loads(out) if isinstance(out, str) else out
    print(f"  web_search 默认返回: {d}")
    # 本地 .env 未配置 WEB_SEARCH_PROVIDER → 应降级 disabled（不报错、不阻断）
    assert d.get("status") == "disabled", f"❌ 未配置 provider 时应降级 disabled，实际 {d.get('status')}"
    assert "message" in d, "❌ disabled 应带友好说明"
    print("  ✅ web_search 默认关闭时优雅降级（status=disabled），不污染主流程")
    return True


async def stream_chat(session_id, message, token, timeout=300):
    import httpx
    H = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=timeout) as c:
        async with c.stream("POST", f"{BASE}/api/agent/chat",
                            headers={**H, "Content-Type": "application/json"},
                            json={"message": message, "session_id": session_id}) as r:
            evt = ""
            out = {"success": False, "answer": "", "doc_generated": None, "events": []}
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
                    out["events"].append((evt, d))
                    if evt == "result":
                        out["success"] = d.get("success", False)
                        out["answer"] = d.get("answer") or ""
                    elif evt == "doc_generated":
                        out["doc_generated"] = d
    return out


async def stream_checks():
    print("\n=== B. generate_doc 导出拦截流式验证（localhost:8000） ===")
    from app.services.auth_service import AuthService
    from app.utils.auth_utils import create_access_token
    user = AuthService.get_user_by_id(3)
    TOKEN, _ = create_access_token(user["id"], user["username"], user.get("role", "user"), user.get("token_version", 1))
    import httpx

    # 第一步：方案匹配（填充 _last_draft）。LLM 偶发先澄清导致 paused，重试直到产出方案。
    print("  [1] 方案匹配（填充终稿缓存，含重试）")
    r1 = None
    for attempt in range(1, 4):
        t0 = time.time()
        r1 = await stream_chat(f"p1_tool_1_{attempt}", "帮我在制造业（装备制造）客户做设备预测性维护方案匹配，客户规模约200人，关注降低非计划停机", TOKEN)
        print(f"      尝试{attempt}: success={r1['success']} | answer_len={len(r1['answer'])} | wall={round(time.time()-t0,1)}s")
        if r1["success"] and len(r1["answer"]) > 500:
            break
        # paused（澄清）或失败：换更具体的表述再试
        print(f"      尝试{attempt} 未产出方案（可能澄清/失败），重试…")
    assert r1["success"] and len(r1["answer"]) > 500, "❌ 第一步方案匹配失败，无法填充终稿"

    # 第二步：导出意图
    print("  [2] 导出意图：把上面的方案导出成 Word")
    t0 = time.time()
    r2 = await stream_chat("p1_tool_2", "把上面的方案导出成 Word", TOKEN)
    print(f"      wall={round(time.time()-t0,1)}s | 事件类型={[e for e,_ in r2['events']]}")
    dg = r2["doc_generated"]
    assert dg, f"❌ 未收到 doc_generated 事件，events={[e for e,_ in r2['events']]}"
    assert dg.get("download_url"), f"❌ doc_generated 缺少 download_url: {dg}"
    assert dg.get("fmt") in ("word", "pdf"), f"❌ doc_generated fmt 异常: {dg.get('fmt')}"
    print(f"  ✅ 收到 doc_generated: download_url={dg['download_url']} | fmt={dg['fmt']} | file={dg.get('file_name')}")

    # 第三步：直接下载校验
    print("  [3] 下载校验")
    dl_url = dg["download_url"]
    async with httpx.AsyncClient(timeout=120) as c:
        fr = await c.get(f"{BASE}{dl_url}")
    print(f"      download HTTP {fr.status_code} | bytes={len(fr.content)}")
    assert fr.status_code == 200 and len(fr.content) > 2000, f"❌ 下载异常: {fr.status_code}/{len(fr.content)}"
    p = os.path.join(ROOT, "tests", "_p1_doc_generated.docx")
    open(p, "wb").write(fr.content)
    print(f"  ✅ 文档已下载并保存: {p}")
    print("\nP1-2 工具（generate_doc 拦截 + web_search 降级）验证全部通过 ✅")


async def main():
    await web_search_unit()
    await stream_checks()


if __name__ == "__main__":
    asyncio.run(main())
