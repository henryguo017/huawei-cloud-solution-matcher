"""
单一 Agent 入口

将所有组件（Tools + Memory + Harness）串联成一个可用的 Agent。
对外暴露简单的 async run() 接口，方便 API 路由直接调用。

用法:
    from app.agent import SolutionAgent

    agent = SolutionAgent()
    result = await agent.run("我想让工厂更智能", session_id="user_123")
    print(result["answer"])
"""

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from app.agent.tools import ToolRegistry, create_default_tools
from app.agent.memory import ConversationMemory
from app.agent.harness import AgentHarness

logger = logging.getLogger(__name__)


class SolutionAgent:
    """
    华为云解决方案智能匹配 Agent

    核心能力：
    1. 接收模糊需求 → 自动分析结构化
    2. 多步检索知识库 + 竞品资料
    3. 生成完整方案报告

    零改动现有代码，通过 import 对接现有 Service
    """

    def __init__(
        self,
        max_steps: int = 8,
        timeout: float = 120.0,
        verbose: bool = False,
    ):
        self.max_steps = max_steps
        self.timeout = timeout
        self.verbose = verbose

        # 创建工具注册中心（4 个核心工具）
        self.tools: ToolRegistry = create_default_tools()

        # 创建记忆管理器（保留最近 10 轮对话）
        self.memory: ConversationMemory = ConversationMemory(max_history_turns=10)

        # 创建执行引擎
        self.harness: AgentHarness = AgentHarness(
            tools=self.tools,
            memory=self.memory,
            max_steps=max_steps,
            timeout=timeout,
            verbose=verbose,
        )

    async def run(
        self,
        user_input: str,
        session_id: str = "default",
        extra_context: str = "",
        event_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        运行 Agent

        参数:
            user_input:     用户输入的原始需求（可以是模糊的）
            session_id:     会话 ID，用于记忆隔离（默认 "default"）
            extra_context:  额外上下文，如产品页面传递的行业信息
            event_callback: 可选异步回调，用于 SSE 流式推送进度事件

        返回:
            {
                "answer": str,       # 最终方案报告
                "steps": int,        # ReAct 执行步数
                "elapsed": float,    # 耗时（秒）
                "tool_calls": list,  # 工具调用记录
                "success": bool,     # 是否成功完成
            }
        """
        logger.info(f"Agent.run() session={session_id} input={user_input[:100]}...")
        return await self.harness.run(
            user_input=user_input,
            session_id=session_id,
            extra_context=extra_context,
            event_callback=event_callback,
        )

    async def run_with_competitor(
        self,
        user_input: str,
        competitor: str,
        industry: str = "",
        session_id: str = "default",
    ) -> Dict[str, Any]:
        """
        运行 Agent（带竞品分析）

        参数:
            user_input:   用户需求
            competitor:   竞品名称
            industry:     行业（可选）
            session_id:   会话 ID

        返回: 同上，但包含竞品对比内容
        """
        context = f"\n注意：用户关注的竞品是 {competitor}" + (f"，行业是 {industry}" if industry else "")
        return await self.run(
            user_input=user_input,
            session_id=session_id,
            extra_context=context,
        )

    def clear_session(self, session_id: str) -> None:
        """清除指定会话的记忆"""
        self.memory.clear_session(session_id)

    def get_stats(self, session_id: str = "default") -> Dict[str, Any]:
        """获取会话统计"""
        mem_stats = self.memory.get_stats(session_id)
        return {
            "session_id": session_id,
            "memory": mem_stats,
            "tools": self.tools.get_tool_names(),
            "max_steps": self.max_steps,
            "timeout": self.timeout,
        }


# ============================================================
# 单例工厂（复用 Agent 实例，节省资源）
# ============================================================

_agent_instance: Optional[SolutionAgent] = None


def get_agent(
    max_steps: int = 8,
    timeout: float = 120.0,
) -> SolutionAgent:
    """获取 Agent 单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SolutionAgent(
            max_steps=max_steps,
            timeout=timeout,
        )
    return _agent_instance


def reset_agent() -> None:
    """重置 Agent 单例（测试用）"""
    global _agent_instance
    _agent_instance = None
