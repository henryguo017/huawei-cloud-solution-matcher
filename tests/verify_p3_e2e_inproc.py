"""P3 全链路本地验收（in-process，真实 LLM + 真实知识库，无需后端服务）。

直接驱动 AgentHarness.run() 跑一份真实方案需求，断言：
1. run 成功（success=True），终稿完整（>300 字）。
2. 发出 plan 事件（两阶段执行存在）。
3. 发出带 plan_index 的工具事件（P2 执行 + P3-2 并行不破坏 plan_index）。
4. 发出 self_check 事件（P3-3 自检 Gate 已接入终稿前管线）。
5. result 含 quality_warn / replanned 字段（P3 字段透传）。
6. 全程使用 flash 模型（MATCH_LLM_MODEL），不触发 pro。

耗时约 3-5 分钟（真实 LLM 多步执行）。
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.harness import AgentHarness, MATCH_LLM_MODEL
from app.agent.tools import create_default_tools
from app.agent.memory import ConversationMemory
from app.config import AGENT_SELF_CHECK, AGENT_REFLEXION_REPLAN, AGENT_PARALLEL_TOOLS


async def main():
    assert (AGENT_SELF_CHECK or "1").strip() == "1", "AGENT_SELF_CHECK 应默认开"
    assert (AGENT_REFLEXION_REPLAN or "1").strip() == "1", "AGENT_REFLEXION_REPLAN 应默认开"
    assert (AGENT_PARALLEL_TOOLS or "1").strip() == "1", "AGENT_PARALLEL_TOOLS 应默认开"

    h = AgentHarness(tools=create_default_tools(), memory=ConversationMemory(max_history_turns=15), max_steps=8, timeout=600)
    events = []

    async def cb(ev):
        events.append(ev)

    demand = "我们是制造企业，约200人，想把ERP和OA上云，和阿里云对比一下，给个完整方案"
    t0 = time.time()
    res = await h.run(user_input=demand, session_id="p3_e2e", user_id=3,
                      user_info={"id": 3, "username": "guo", "role": "user", "token_version": 24},
                      event_callback=cb)
    wall = round(time.time() - t0, 1)

    types = [e.get("type") for e in events]
    from collections import Counter
    print(f"[P3 E2E] 事件总数={len(events)} 类型分布={dict(Counter(types))}")
    plans = [e for e in events if e.get("type") == "plan"]
    self_checks = [e for e in events if e.get("type") == "self_check"]
    tool_idx = [e for e in events if e.get("type") in ("tool_start", "tool_end") and isinstance(e.get("plan_index"), int)]
    print(f"[P3 E2E] 耗时={wall}s success={res.get('success')} 终稿长度={len(res.get('answer',''))}")
    print(f"        plan事件数={len(plans)} self_check事件数={len(self_checks)} 带plan_index工具事件数={len(tool_idx)}")
    print(f"        quality_warn={res.get('quality_warn')} replanned={res.get('replanned')}")
    if self_checks:
        print(f"        self_check gates={[ (e.get('gate'), e.get('score')) for e in self_checks ]}")
    print(f"        模型={MATCH_LLM_MODEL}（应为 deepseek-v4-flash）")

    assert res.get("success"), f"run 应成功，实际: {str(res.get('answer',''))[:200]}"
    assert plans, "应发出 plan 事件（两阶段执行）"
    assert tool_idx, "应有带 plan_index 的工具事件（P2/P3-2 未破坏）"
    assert self_checks, "P3-3 应发出 self_check 事件（已接入终稿前管线）"
    assert len(res.get("answer", "")) > 300, "终稿应完整"
    assert "quality_warn" in res and "replanned" in res, "result 应透传 P3 字段"
    assert MATCH_LLM_MODEL == "deepseek-v4-flash", "Agent 主路径应走 flash，非 pro"

    print("\n✅ P3 全链路本地验收通过（真实 LLM 跑通 plan→工具→自检→终稿）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
