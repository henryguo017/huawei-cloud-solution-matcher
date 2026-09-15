"""P3-2 并行子体 验证：直接驱动 harness._execute_step 的并行分支。

构造一个 plan 步（工具集含 search_kb + search_competitor），让 LLM 单轮产出两个只读 Action，
断言：
1. 并发发起 >=2 个 tool_start（同 plan_index）。
2. 两个只读工具均被执行（_execute_tool 各调用一次）。
3. 并发完成：总耗时明显小于两工具串行之和（sleep 0.3s ×2 → 并行应 ~0.3s）。
4. 两路 observation 都进入本步结果（供汇总消费）。

为确定性，monkeypatch _call_llm（首轮双 Action、次轮 STEP_DONE）与 _execute_tool（记录起止时间并 sleep 模拟耗时）。
只读工具（search_kb/search_competitor）默认权限 allow，不会触发 human-in-the-loop 阻塞。
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.harness import AgentHarness
from app.agent.tools import create_default_tools
from app.agent.memory import ConversationMemory


def make_harness():
    tools = create_default_tools()
    mem = ConversationMemory(max_history_turns=15)
    h = AgentHarness(tools=tools, memory=mem, max_steps=8, timeout=120)
    h._intent = "solution"
    h._multi_agent_enabled = False
    h._plan_original_input = "我们是制造企业，想把ERP上云，和阿里云对比一下"
    h._start_time = time.time()
    h.timeout = 120
    h.max_steps = 8
    h._step_count = 0
    return h


async def main():
    from app.config import AGENT_PARALLEL_TOOLS, MAX_PARALLEL
    assert (AGENT_PARALLEL_TOOLS or "1").strip() == "1", "AGENT_PARALLEL_TOOLS 应默认开启"
    assert MAX_PARALLEL >= 2, "MAX_PARALLEL 应 >=2"

    h = make_harness()
    step_action_done = {"v": False}

    async def fake_llm(prompt):
        if not step_action_done["v"]:
            step_action_done["v"] = True
            return (
                "Thought: 同时检索知识库与竞品，可并行加速\n"
                "Action: search_kb\nAction Input: {\"query\": \"制造业 ERP 上云\"}\n"
                "Action: search_competitor\nAction Input: {\"query\": \"阿里云 制造业 ERP 上云\"}"
            )
        return "STEP_DONE: 已并行检索到资料与竞品对比"

    h._call_llm = fake_llm

    calls = []

    async def fake_tool(name, tool_input, event_callback=None):
        t0 = time.time()
        await asyncio.sleep(0.3)  # 模拟检索耗时
        calls.append({"name": name, "start": t0, "end": time.time()})
        return f"[{name}] 检索结果：制造业上云相关资料 / 阿里云对比要点。"

    h._execute_tool = fake_tool

    events = []

    async def cb(ev):
        events.append(ev)

    obs = await h._execute_step(
        0, "检索资料与竞品", ["search_kb", "search_competitor"],
        cb, "sid-test", [],
    )

    tool_starts = [e for e in events if e.get("type") == "tool_start"]
    print(f"[P3-2] tool_start 数={len(tool_starts)} 实际执行工具数={len(calls)}")
    if calls:
        total = max(c["end"] for c in calls) - min(c["start"] for c in calls)
        ser = sum(c["end"] - c["start"] for c in calls)
        print(f"        并行总耗时={total:.3f}s 串行理论={ser:.3f}s")
        print(f"        起止: {[ (round(c['start'],3), round(c['end'],3)) for c in calls ]}")

    assert len(tool_starts) >= 2, "应并发发起 >=2 个 tool_start"
    assert len(calls) == 2, "search_kb 与 search_competitor 都应被执行"
    assert "search_kb" in obs and "search_competitor" in obs, "两路 observation 都应进入本步结果"
    # 并发证据：总耗时应接近单次耗时（~0.3s），远小于串行之和（~0.6s）。
    # 用 0.45s 中点区分：真正并发≈0.3，顺序≈0.6。
    assert total < 0.45, f"应真正并发（总耗时≈0.3s），实际 {total:.3f}s（疑似顺序执行）"

    print("\n✅ P3-2 并行子体 验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
