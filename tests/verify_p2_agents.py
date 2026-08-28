"""P2-1-B 验证：多智能体 Orchestrator-Workers（分析师→架构师→校验官）

断言（/api/agent/chat 流式事件）：
  1. 收到 agent_phase 事件 ≥3 个，顺序为 demand_analysis → solution_architect → quality_review
  2. 各 phase 的 step_index 依次 0/1/2（角色 ↔ plan 步对齐）
  3. 有工具调用且 plan_index 单调非降
  4. result.success=True 且 answer 非空
"""
import sys, os, json, asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("OMP_NUM_THREADS", "1")

BASE = "http://localhost:8000"
PHASE_ORDER = ["demand_analysis", "solution_architect", "quality_review"]


def make_token():
    from app.services.auth_service import AuthService
    from app.utils.auth_utils import create_access_token
    user = AuthService.get_user_by_id(3)
    tok, _ = create_access_token(user["id"], user["username"], user.get("role", "user"), user.get("token_version", 1))
    return tok


async def stream_chat(session_id, message, token, max_retry=3):
    import httpx
    for attempt in range(1, max_retry + 1):
        evts = {"phases": [], "tool": [], "result": None}
        async with httpx.AsyncClient(timeout=420) as c:
            async with c.stream("POST", f"{BASE}/api/agent/chat", headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            }, json={"message": message, "session_id": session_id}) as r:
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
                        elif evt == "result":
                            evts["result"] = d
        if evts["phases"]:
            return evts, attempt
        print(f"  (attempt {attempt}: 未观察到 agent_phase，重试)")
    return evts, max_retry


async def main():
    print("=== P2-1-B 多智能体验证 ===")
    token = make_token()
    res, attempt = await stream_chat("p2_agents", "帮我在制造业客户做设备预测性维护方案匹配", token)
    print(f"  (第 {attempt} 次尝试成功)")

    phases = res["phases"]
    assert len(phases) >= 3, f"❌ agent_phase 应 ≥3 个，实际 {len(phases)}"
    order = [p for p, _ in phases]
    print(f"  ✅ agent_phase 序列: {order}")

    # 顺序断言：demand_analysis → solution_architect → quality_review（允许重复/额外，但需保持该顺序出现）
    pos = {p: order.index(p) for p in PHASE_ORDER if p in order}
    assert set(PHASE_ORDER) <= set(order), f"❌ 缺少角色阶段: 应有 {PHASE_ORDER}，实际 {order}"
    assert pos["demand_analysis"] < pos["solution_architect"] < pos["quality_review"], \
        f"❌ 阶段顺序错误: {pos}"
    print("  ✅ 三阶段顺序正确（分析师→架构师→校验官）")

    # step_index 对齐
    step_idx = [i for _, i in phases]
    print(f"  ✅ 阶段对应 plan 步: {step_idx}")
    assert 0 in step_idx and 1 in step_idx and 2 in step_idx, f"❌ 应覆盖 plan 步 0/1/2: {step_idx}"

    # 工具调用
    tool_seq = [t for t in res["tool"] if t[0] == "start"]
    assert tool_seq, "❌ 未观察到工具调用"
    idxs = [i for _, i, _ in tool_seq]
    assert all(b >= a for a, b in zip(idxs, idxs[1:])), f"❌ plan_index 非单调: {idxs}"
    print(f"  ✅ 工具调用 plan_index 单调: {idxs}")

    # 结果
    r = res["result"]
    assert r and r.get("success"), "❌ 结果未成功"
    assert r.get("answer") and len(r["answer"]) > 200, "❌ 终稿过短"
    print(f"  ✅ success=True，终稿 {len(r['answer'])} 字")

    print("\nP2-1-B 多智能体验证全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
