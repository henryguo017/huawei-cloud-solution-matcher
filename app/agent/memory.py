"""
对话记忆管理器

管理 Agent 的短期记忆（当前轮次 ReAct 中间步骤）和长期记忆（跨轮次对话历史）。
设计原则：
- 零外部依赖
- 内存存储（不持久化），重启即清
- 支持会话隔离（按 session_id）
"""

import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class MemoryEntry:
    """单条记忆条目"""
    role: str           # "user" | "agent" | "thought" | "action" | "observation"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConversationMemory:
    """
    对话记忆管理器

    两层结构：
    - short_term:  当前 ReAct 循环的中间步骤（Thought/Action/Observation）
    - long_term:   跨轮次的对话历史（User 输入 / Agent 最终回复）
    """

    def __init__(self, max_history_turns: int = 10):
        self._sessions: Dict[str, Dict[str, List[MemoryEntry]]] = {}
        self.max_history_turns = max_history_turns

    def _get_or_create_session(self, session_id: str) -> Dict[str, List[MemoryEntry]]:
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "short_term": [],
                "long_term": [],
            }
        return self._sessions[session_id]

    # ---- 短期记忆（ReAct 中间步骤） ----

    def add_thought(self, session_id: str, content: str) -> None:
        """记录 Thought 步骤"""
        session = self._get_or_create_session(session_id)
        session["short_term"].append(MemoryEntry(role="thought", content=content))

    def add_action(self, session_id: str, tool_name: str, tool_input: str) -> None:
        """记录 Action 步骤"""
        session = self._get_or_create_session(session_id)
        session["short_term"].append(MemoryEntry(
            role="action",
            content=f"{tool_name}: {tool_input}",
            metadata={"tool": tool_name, "input": tool_input}
        ))

    def add_observation(self, session_id: str, content: str) -> None:
        """记录 Observation 步骤"""
        session = self._get_or_create_session(session_id)
        session["short_term"].append(MemoryEntry(role="observation", content=content))

    def clear_short_term(self, session_id: str) -> None:
        """清空短期记忆（一轮 ReAct 完成后调用）"""
        if session_id in self._sessions:
            self._sessions[session_id]["short_term"] = []

    def get_short_term(self, session_id: str) -> List[MemoryEntry]:
        """获取当前轮次的短期记忆"""
        if session_id not in self._sessions:
            return []
        return self._sessions[session_id]["short_term"]

    def get_recent_thoughts_actions(self, session_id: str, n: int = 3) -> str:
        """
        获取最近的 N 组 Thought/Action/Observation，拼接成 Prompt 上下文
        用于注入到下一轮 LLM 调用，避免 Agent 重复操作
        """
        entries = self.get_short_term(session_id)
        if not entries:
            return ""

        # 取最近的 n 组完整循环（每轮约 3 条：thought/action/observation）
        recent = entries[-(n * 3):]
        lines = []
        for e in recent:
            if e.role == "thought":
                lines.append(f"Thought: {e.content}")
            elif e.role == "action":
                lines.append(f"Action: {e.content}")
            elif e.role == "observation":
                lines.append(f"Observation: {e.content}")
        return "\n".join(lines)

    # ---- 长期记忆（跨轮次历史） ----

    def add_user_message(self, session_id: str, content: str) -> None:
        """记录用户消息（长期记忆）"""
        session = self._get_or_create_session(session_id)
        session["long_term"].append(MemoryEntry(role="user", content=content))
        self._trim_long_term(session_id)

    def add_agent_response(self, session_id: str, content: str) -> None:
        """记录 Agent 最终回复（长期记忆）"""
        session = self._get_or_create_session(session_id)
        session["long_term"].append(MemoryEntry(role="agent", content=content))
        self._trim_long_term(session_id)

    def get_conversation_history(self, session_id: str) -> str:
        """
        获取对话历史，拼接成 Prompt 上下文
        用于让 Agent 感知之前的对话
        """
        if session_id not in self._sessions:
            return "（这是第一次对话）"

        entries = self._sessions[session_id]["long_term"]
        if not entries:
            return "（这是第一次对话）"

        lines = ["【对话历史】"]
        for e in entries:
            role_label = "用户" if e.role == "user" else "助手"
            # 截断过长内容
            content = e.content[:300] + "..." if len(e.content) > 300 else e.content
            lines.append(f"{role_label}: {content}")
        return "\n".join(lines)

    def _trim_long_term(self, session_id: str) -> None:
        """限制长期记忆长度，保留最近的 N 轮对话"""
        if session_id not in self._sessions:
            return
        entries = self._sessions[session_id]["long_term"]
        # 一轮对话 = 1 user + 1 agent = 2 条 entry
        max_entries = self.max_history_turns * 2
        if len(entries) > max_entries:
            self._sessions[session_id]["long_term"] = entries[-max_entries:]

    # ---- 管理 ----

    def clear_session(self, session_id: str) -> None:
        """清除整个会话的所有记忆"""
        if session_id in self._sessions:
            del self._sessions[session_id]

    def get_stats(self, session_id: str) -> Dict[str, int]:
        """获取会话统计"""
        if session_id not in self._sessions:
            return {"short_term": 0, "long_term": 0}
        return {
            "short_term": len(self._sessions[session_id]["short_term"]),
            "long_term": len(self._sessions[session_id]["long_term"]),
        }
