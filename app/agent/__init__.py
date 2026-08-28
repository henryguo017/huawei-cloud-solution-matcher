"""
Agent 层 — 单 Agent + Tool Calling 架构
Phase 1: 解决模糊需求输入导致 RAG 检索失败的核心痛点

组件:
- tools.py:     工具定义 + 注册中心
- memory.py:    对话记忆管理
- harness.py:   ReAct 循环执行引擎
- agent.py:     单一 Agent 入口
"""

from app.agent.agent import SolutionAgent, get_agent
from app.agent.harness import AgentHarness
from app.agent.tools import ToolRegistry, create_default_tools
from app.agent.memory import ConversationMemory

__all__ = [
    "SolutionAgent",
    "get_agent",
    "AgentHarness",
    "ToolRegistry",
    "create_default_tools",
    "ConversationMemory",
]
