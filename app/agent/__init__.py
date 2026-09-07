"""
Agent 层 — 单 Agent + Tool Calling 架构
Phase 1: 解决模糊需求输入导致 RAG 检索失败的核心痛点

组件:
- tools.py:     工具定义 + 注册中心
- memory.py:    对话记忆管理
- harness.py:   ReAct 循环执行引擎
- agent.py:     单一 Agent 入口

⚠️ 惰性导入（PEP 562 __getattr__）：
    本包会被 `python -m app.agent.mcp_server_*` 作为 MCP 子进程启动时，Python 会
    先执行本 __init__。若在此处顶层 import 重型依赖（chromadb/langchain/BGE），
    子进程会卡在 import 阶段直至 mcp_client.py 的 35s 超时跳过 → 工具未注册 →
    Agent 幻觉"已保存/已测算"。改为惰性导入后，import 本包本身零副作用，
    只有真正访问 SolutionAgent/AgentHarness 等时才按需加载对应子模块。
"""

import importlib

_SUBMODULE_ATTRS = {
    "SolutionAgent": "app.agent.agent",
    "get_agent": "app.agent.agent",
    "AgentHarness": "app.agent.harness",
    "ToolRegistry": "app.agent.tools",
    "create_default_tools": "app.agent.tools",
    "ConversationMemory": "app.agent.memory",
}

__all__ = list(_SUBMODULE_ATTRS.keys())


def __getattr__(name):
    if name in _SUBMODULE_ATTRS:
        module = importlib.import_module(_SUBMODULE_ATTRS[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals().keys()) | set(_SUBMODULE_ATTRS.keys()))
