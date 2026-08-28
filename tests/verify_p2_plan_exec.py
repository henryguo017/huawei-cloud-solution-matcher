"""P2-1-A 验证：真·两阶段执行（plan 驱动工具调用顺序）

断言（通过 /api/agent/chat 流式事件）：
  1. 收到 plan 事件（3 步，solution 意图）
  2. tool_start 事件的 plan_index 严格单调非降（按 plan 顺序执行，不允许乱序/跳步）
  3. 每个 tool_start 的工具属于该 plan 步允许的工具集（PLAN_STEP_TOOL_MAP）
  4. final 事件 plan_index = len(plan)-1（末步综合生成点亮）
  5. result.plan_status 全部 done
"""
import sys, os, json, asyncio, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("OMP_NUM_THREADS", "1")

BASE = "http://localhost:8000"
# 与多智能体角色工具集对齐（solution 3 步：分析师/架构师/校验官）
TOOL_MAP = {
    0: {"analyze_demand", "read_customer_file", "list_dir", "web_search"},  # 需求分析师
    1: {"search_kb", "search_competitor", "web_search"},                    # 方案架构师
    2: {"search_kb"},                                                       # 质量校验官
}


def make_token():
    from app.services.auth_service import AuthService
    from app.utils.auth_utils import create_access_token
    user = AuthService.get_user_by_id(3)
    tok, _ = create_access_token(user["id"], user["username"], user.get("role", "user"), user.get("token_version", 1))
    return tok


async def stream_chat(session_id, message, token, max_retry=3):
    """流式调用 /api/agent/chat，收集关键事件；LLM 非确定 → 重试直到观察到工具调用"""
    import httpx
    for attempt in range(1, max_retry + 1):
        evts = {"plan": [], "tool": [], "final": [], "result": None, "clarify": None}
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
                        if evt == "plan":
                            evts["plan"] = d.get("steps", [])
                        elif evt == "tool_start":
                            evts["tool"].append(("start", d.get("plan_index", -1), d.get("tool") or d.get("name")))
                        elif evt == "tool_end":
                            evts["tool"].append(("end", d.get("plan_index", -1), d.get("tool") or d.get("name")))
                        elif evt == "final":
                            evts["final"].append(d.get("plan_index", None))
                        elif evt == "result":
                            evts["result"] = d
                        elif evt == "clarify":
                            evts["clarify"] = d
        if evts["tool"]:
            return evts, attempt
        print(f"  (attempt {attempt}: 本次未观察到工具调用，重试)")
    return evts, max_retry


async def main():
    print("=== P2-1-A 两阶段执行验证 ===")
    token = make_token()
    res, attempt = await stream_chat("p2_plan_exec", "帮我在制造业客户做设备预测性维护方案匹配", token)
    print(f"  (第 {attempt} 次尝试成功)")

    plan = res["plan"]
    assert plan, "❌ 未收到 plan 事件"
    assert len(plan) == 3, f"❌ solution plan 应为 3 步，实际 {len(plan)}"
    print(f"  ✅ plan 3 步: {' | '.join(plan)}")

    # 工具调用序列
    tool_seq = [t for t in res["tool"] if t[0] == "start"]
    assert tool_seq, "❌ 未观察到任何工具调用"
    idxs = [i for _, i, _ in tool_seq]
    names = [n for _, _, n in tool_seq]
    print(f"  ✅ 工具调用序列: {list(zip(names, idxs))}")

    # 1. plan_index 单调非降
    assert all(b >= a for a, b in zip(idxs, idxs[1:])), f"❌ plan_index 非单调: {idxs}"
    print(f"  ✅ plan_index 单调非降: {idxs}")

    # 2. 工具归属正确（每个工具属于该 plan 步允许的工具集）
    for name, i in zip(names, idxs):
        assert name in TOOL_MAP.get(i, set()), f"❌ 工具 {name} 不属于 plan 步 {i} 允许的工具集 {TOOL_MAP.get(i)}"
    print(f"  ✅ 工具均属于对应 plan 步允许的工具集")

    # 3. final 指向最后一步
    final_idx = res["final"][-1] if res["final"] else None
    assert final_idx == len(plan) - 1, f"❌ final plan_index 应为 {len(plan)-1}，实际 {final_idx}"
    print(f"  ✅ final plan_index={final_idx}（综合生成步）")

    # 4. result.plan_status 全 done
    rps = res["result"].get("plan_status") if res["result"] else None
    assert isinstance(rps, list) and len(rps) == len(plan), f"❌ result.plan_status 异常: {rps}"
    assert all(s == "done" for s in rps), f"❌ 应有全部 done，实际 {rps}"
    print(f"  ✅ result.plan_status={rps}")

    print("\nP2-1-A 两阶段执行验证全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
