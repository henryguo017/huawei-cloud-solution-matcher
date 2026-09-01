"""P3-1 真反思-重规划 验证：直接驱动 harness._reflexion_replan。

构造一个「第 2 步检索工具失败」的场景（_step_results[1] 含 Error:），
断言：
1. _reflexion_replan 返回非空终稿（重规划成功，未降级）。
2. 发出 reflexion 事件且 replanned=True。
3. 发出 plan 事件且 plan_version=2（plan_status 重新点亮）。
4. 失败步 _step_results[1] 被重跑修复（不再含 Error:）。
5. 重规划次数受 REFLEXION_MAX_REPLANS 保护（此处仅验证单次成功路径）。

为确定性，monkeypatch _call_llm（按 prompt 标记路由）与 _execute_tool（返回固定 observation），
不依赖真实 LLM 行为，只验证编排逻辑。
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
    h._quality_warn = False
    h._plan = ["分析需求", "检索资料", "撰写方案"]
    h._plan_original_input = "我们是制造企业，想把ERP上云，给个方案"
    h._step_results = {
        0: "（第1步完成：需求已明确，制造业约200人）",
        1: "Error: search_kb 暂时不可用：连接超时（未能检索资料）",  # 失败步
        2: "（第3步：综合生成阶段，由汇总完成）",
    }
    h._start_time = time.time()
    h.timeout = 120
    h.max_steps = 8
    h._step_count = 0
    return h


async def main():
    from app.config import AGENT_REFLEXION_REPLAN, REFLEXION_MAX_REPLANS
    assert (AGENT_REFLEXION_REPLAN or "1").strip() == "1", "AGENT_REFLEXION_REPLAN 应默认开启"

    h = make_harness()

    # 确定性 LLM 路由：planner / step / synthesize 三类 prompt 各返回固定文本
    step_action_done = {"v": False}

    async def fake_llm(prompt):
        if "PLANNER" in prompt or "重规划" in prompt or "修订计划" in prompt:
            # plan_v2：拆出补强检索步 + 撰写步
            return '["重新检索制造业ERP上云资料（补强失败步）", "基于检索资料撰写完整方案"]'
        if "Final Answer" in prompt:
            return "Final Answer: 重规划后的完整方案：华为云ECS+RDS+CBR组合，分两阶段迁移ERP与OA，预计TCO降30%。"
        # _execute_step 单步子循环：首次给 Action，再次给 STEP_DONE
        if not step_action_done["v"]:
            step_action_done["v"] = True
            return 'Thought: 需要补强检索\nAction: search_kb\nAction Input: {"query": "制造业 ERP 上云 补强"}'
        return "STEP_DONE: 已补强检索到制造业上云资料"

    h._call_llm = fake_llm

    async def fake_tool(name, tool_input, event_callback=None):
        return f"[检索结果] 华为云制造业ERP上云方案3篇，要点：ECS c7.2xlarge + RDS主备 + CBR云备份。"

    h._execute_tool = fake_tool

    events = []

    async def cb(ev):
        events.append(ev)

    out = await h._reflexion_replan(cb, "sid-test", [])

    print(f"[P3-1] _reflexion_replan 返回: {'非None' if out else 'None'}")
    refl = [e for e in events if e.get("type") == "reflexion" and e.get("replanned")]
    plans = [e for e in events if e.get("type") == "plan" and e.get("plan_version") == 2]
    print(f"        reflexion.replanned 事件数={len(refl)} plan_version=2 事件数={len(plans)}")
    print(f"        失败步重跑后 _step_results[1]={h._step_results.get(1, '')[:60]}...")
    print(f"        重规划次数 _replan_count={getattr(h, '_replan_count', 0)} (上限 {REFLEXION_MAX_REPLANS})")

    assert out is not None, "重规划应返回非空终稿（未降级）"
    assert refl, "应发出 reflexion 事件且 replanned=True"
    assert plans, "应发出 plan 事件且 plan_version=2"
    assert "Error:" not in (h._step_results.get(1, "") or ""), "失败步应被重跑修复（不再含 Error:）"
    assert getattr(h, "_replan_count", 0) >= 1, "应记录重规划次数"

    print("\n✅ P3-1 真反思-重规划 验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
