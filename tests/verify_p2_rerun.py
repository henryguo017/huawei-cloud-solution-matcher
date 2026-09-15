"""P2-D5 验证：Plan 单步重跑（rerun_plan_index）

流程：
  1. 先跑完整方案匹配（两阶段执行，产生 _plan/_step_results）
  2. 发 rerun_plan_index=0 → 应收到该步的 agent_phase + tool_start(plan_index=0)
  3. result.success=True 且 answer 非空（重新汇总生成新终稿）
"""
import sys, os, json, asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("OMP_NUM_THREADS", "1")

BASE = "http://localhost:8000"


def make_token():
    from app.services.auth_service import AuthService
    from app.utils.auth_utils import create_access_token
    user = AuthService.get_user_by_id(3)
    tok, _ = create_access_token(user["id"], user["username"], user.get("role", "user"), user.get("token_version", 1))
    return tok


async def stream_chat(session_id, message, token, rerun=None, max_retry=3):
    import httpx
    for attempt in range(1, max_retry + 1):
        evts = {"phases": [], "tool": [], "final": [], "result": None}
        payload = {"message": message, "session_id": session_id}
        if rerun is not None:
            payload["rerun_plan_index"] = rerun
        async with httpx.AsyncClient(timeout=420) as c:
            async with c.stream("POST", f"{BASE}/api/agent/chat", headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            }, json=payload) as r:
                evt = ""
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
                        if evt == "agent_phase":
                            evts["phases"].append((d.get("phase"), d.get("step_index")))
                        elif evt == "tool_start":
                            evts["tool"].append(("start", d.get("plan_index", -1), d.get("tool") or d.get("name")))
                        elif evt == "final":
                            evts["final"].append(d.get("plan_index", None))
                        elif evt == "result":
                            evts["result"] = d
        if evts["result"] is not None:
            return evts, attempt
        print(f"  (attempt {attempt}: 无 result，重试)")
    return evts, max_retry


async def main():
    print("=== P2-D5 Plan 单步重跑验证 ===")
    token = make_token()
    SID = "p2_rerun"

    # 1. 首跑完整方案
    print("  [1] 首跑完整方案匹配（填充 plan / step_results）")
    r1, _ = await stream_chat(SID, "帮我在制造业客户做设备预测性维护方案匹配", token)
    assert r1["result"] and r1["result"].get("success"), "❌ 首跑未成功"
    print(f"      ✅ 首跑成功，终稿 {len(r1['result'].get('answer',''))} 字，plan_steps={len(r1['result'].get('plan') or [])}")

    # 2. 重跑第 0 步
    print("  [2] 重跑 plan 第 0 步（rerun_plan_index=0）")
    r2, attempt = await stream_chat(SID, "__rerun_plan__", token, rerun=0)
    print(f"      (第 {attempt} 次尝试成功)")

    # 该步 agent_phase 出现 demand_analysis
    phases = [p for p, _ in r2["phases"]]
    assert "demand_analysis" in phases, f"❌ 重跑第 0 步应出现 demand_analysis 阶段: {phases}"
    print(f"  ✅ agent_phase: {phases}")

    # 该步工具调用 plan_index=0
    tool0 = [t for t in r2["tool"] if t[1] == 0]
    assert tool0, f"❌ 重跑第 0 步未观察到 plan_index=0 的工具调用: {r2['tool']}"
    print(f"  ✅ 重跑工具: {[(n, i) for _, i, n in tool0]}")

    # 3. 重新汇总成功
    assert r2["result"].get("success"), "❌ 重跑后未成功"
    ans2 = r2["result"].get("answer", "")
    assert len(ans2) > 200, f"❌ 重跑后终稿过短: {len(ans2)}"
    print(f"  ✅ 重跑后 success=True，新终稿 {len(ans2)} 字")

    print("\nP2-D5 Plan 单步重跑验证全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
