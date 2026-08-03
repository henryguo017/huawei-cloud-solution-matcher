"""
对话记忆管理器

管理 Agent 的短期记忆（当前轮次 ReAct 中间步骤）和长期记忆（跨轮次对话历史）。
设计原则：
- 短期记忆（ReAct 步骤）留内存，不落库，避免 IO 放大
- 长期记忆（用户/助手对话）落库 SQLite（data/users.db 的 agent_memory 表），
  按 user_id 隔离，进程重启后可读回 —— 即「阶段2 持久记忆」
- 长期记忆保留最近 N 轮（默认 15），超出窗口或超 30 天的旧记忆归档到
  agent_memory_archive 表（不删除），由 _trim_and_archive 维护
- 接口与改造前完全一致（harness.py 零改动）
"""

import time
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """单条记忆条目"""
    role: str           # "user" | "agent" | "thought" | "action" | "observation"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConversationMemory:
    """
    对话记忆管理器（持久化版）

    两层结构：
    - short_term:  当前 ReAct 循环的中间步骤（Thought/Action/Observation），仅内存
    - long_term:   跨轮次的对话历史（User 输入 / Agent 最终回复），内存 + SQLite 双写
    """

    def __init__(self, max_history_turns: int = 15):
        self._sessions: Dict[str, Dict[str, List[MemoryEntry]]] = {}
        self.max_history_turns = max_history_turns
        # 已从句库加载进内存的 session 集合，避免重复加载 / 重复追加
        self._loaded: set = set()

    # ---------- DB 辅助 ----------

    @staticmethod
    def _db_conn():
        from app.utils import db_init
        return db_init.get_db_connection()

    @staticmethod
    def _parse_user_id(session_id: str) -> int:
        try:
            # session_id 形如 "{user_id}" 或 "{user_id}:{client_id}"，取冒号前部分
            return int(str(session_id).split(':')[0])
        except (ValueError, TypeError):
            return 0

    def _get_or_create_session(self, session_id: str) -> Dict[str, List[MemoryEntry]]:
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "short_term": [],
                "long_term": [],
            }
        return self._sessions[session_id]

    def _ensure_loaded(self, session_id: str) -> None:
        """首次访问某 session 时，从 DB 载入最近 N*2 条长期记忆到内存（重启后记忆恢复）"""
        if session_id in self._loaded:
            return
        self._loaded.add(session_id)
        self._get_or_create_session(session_id)  # 确保 dict 存在
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            uid = self._parse_user_id(session_id)
            # 用自增 id 排序（插入顺序）而非 created_at：created_at 仅秒级精度，
            # 同一秒内多条记忆会导致窗口/归档选取不确定，进而归档错条目。
            cur.execute(
                """SELECT role, content FROM agent_memory
                   WHERE user_id=? AND session_id=?
                   ORDER BY id DESC LIMIT ?""",
                (uid, session_id, self.max_history_turns * 2),
            )
            rows = cur.fetchall()
            conn.close()
            # DB 倒序取出，需反转为时间正序塞进内存
            session = self._sessions[session_id]
            for r in reversed(rows):
                session["long_term"].append(MemoryEntry(role=r["role"], content=r["content"]))
        except Exception as e:
            logger.warning(f"[memory] 加载长期记忆失败 session={session_id}: {e}")

    # ---- 短期记忆（ReAct 中间步骤，仅内存） ----

    def add_thought(self, session_id: str, content: str) -> None:
        session = self._get_or_create_session(session_id)
        session["short_term"].append(MemoryEntry(role="thought", content=content))

    def add_action(self, session_id: str, tool_name: str, tool_input: str) -> None:
        session = self._get_or_create_session(session_id)
        session["short_term"].append(MemoryEntry(
            role="action",
            content=f"{tool_name}: {tool_input}",
            metadata={"tool": tool_name, "input": tool_input}
        ))

    def add_observation(self, session_id: str, content: str) -> None:
        session = self._get_or_create_session(session_id)
        session["short_term"].append(MemoryEntry(role="observation", content=content))

    def clear_short_term(self, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id]["short_term"] = []

    def get_short_term(self, session_id: str) -> List[MemoryEntry]:
        if session_id not in self._sessions:
            return []
        return self._sessions[session_id]["short_term"]

    def get_recent_thoughts_actions(self, session_id: str, n: int = 3) -> str:
        entries = self.get_short_term(session_id)
        if not entries:
            return ""
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

    # ---- 长期记忆（跨轮次历史，内存 + SQLite 双写） ----

    def add_user_message(self, session_id: str, content: str) -> None:
        self._ensure_loaded(session_id)
        session = self._get_or_create_session(session_id)
        session["long_term"].append(MemoryEntry(role="user", content=content))
        self._persist(session_id, "user", content)
        self._upsert_conversation(session_id, content)
        self._trim_long_term(session_id)
        self._trim_and_archive(session_id)

    def add_agent_response(self, session_id: str, content: str) -> None:
        self._ensure_loaded(session_id)
        session = self._get_or_create_session(session_id)
        session["long_term"].append(MemoryEntry(role="agent", content=content))
        self._persist(session_id, "agent", content)
        self._trim_long_term(session_id)
        self._trim_and_archive(session_id)

    def _persist(self, session_id: str, role: str, content: str) -> None:
        """单条长期记忆落库（截断 500 字，写失败降级内存仅记日志）"""
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            uid = self._parse_user_id(session_id)
            cur.execute(
                "INSERT INTO agent_memory (user_id, session_id, role, content) VALUES (?, ?, ?, ?)",
                (uid, session_id, role, content[:500]),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"[memory] 长期记忆落库失败 session={session_id}: {e}")

    def get_conversation_history(self, session_id: str, max_rounds: Optional[int] = None) -> str:
        """
        注入给 LLM 的对话历史文本。

        默认仅注入最近 max_rounds 轮（默认取全局配置 AGENT_MEMORY_MAX_ROUNDS=6）：
        任务型 Agent（每条指令独立完成）只需少量最近上下文，窗口过大会导致跨任务串味
        （连跑多条时被前几条历史污染，输出畸形/误判"已生成过"）。
        """
        self._ensure_loaded(session_id)
        if session_id not in self._sessions:
            return "（这是第一次对话）"
        entries = self._sessions[session_id]["long_term"]
        if not entries:
            return "（这是第一次对话）"
        if max_rounds is None:
            try:
                from app.config import AGENT_MEMORY_MAX_ROUNDS
                max_rounds = AGENT_MEMORY_MAX_ROUNDS
            except Exception:
                max_rounds = 6
        # 最近 max_rounds 轮 = 最近 max_rounds*2 条（一轮 = 用户1条 + 助手1条）
        window_entries = entries[-(max_rounds * 2):] if max_rounds > 0 else []
        if not window_entries:
            return "（这是第一次对话）"
        lines = ["【对话历史】"]
        for e in window_entries:
            role_label = "用户" if e.role == "user" else "助手"
            content = e.content[:300] + "..." if len(e.content) > 300 else e.content
            lines.append(f"{role_label}: {content}")
        return "\n".join(lines)

    def get_recent_conversation_for_profile(self, session_id: str, n: int = 4) -> str:
        """提取最近 n 轮对话文本，用于用户画像提炼"""
        self._ensure_loaded(session_id)
        if session_id not in self._sessions:
            return ""
        entries = self._sessions[session_id]["long_term"]
        # 取最近 n 轮 = 2n 条
        recent = entries[-(n * 2):]
        lines = []
        for e in recent:
            role_label = "用户" if e.role == "user" else "助手"
            lines.append(f"{role_label}: {e.content[:400]}")
        return "\n".join(lines)

    def _trim_long_term(self, session_id: str) -> None:
        """限制内存中长期记忆长度，保留最近的 N 轮对话"""
        if session_id not in self._sessions:
            return
        entries = self._sessions[session_id]["long_term"]
        max_entries = self.max_history_turns * 2
        if len(entries) > max_entries:
            self._sessions[session_id]["long_term"] = entries[-max_entries:]

    def _trim_and_archive(self, session_id: str) -> None:
        """
        维护长期记忆窗口 + 30 天归档策略：
        - 超出最近 N*2 条的旧记忆 → 归档（移入 agent_memory_archive，不删除）
        - 任何创建于 30 天前的记忆 → 归档
        """
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            uid = self._parse_user_id(session_id)
            window = self.max_history_turns * 2
            # 找出需归档的 id：窗口外（按 id 判定插入顺序） 或 超 30 天
            cur.execute(
                """SELECT id FROM agent_memory
                   WHERE user_id=? AND session_id=?
                   AND (
                       id NOT IN (
                           SELECT id FROM agent_memory
                           WHERE user_id=? AND session_id=?
                           ORDER BY id DESC LIMIT ?
                       )
                       OR created_at < datetime('now', 'localtime', '-30 days')
                   )""",
                (uid, session_id, uid, session_id, window),
            )
            ids = [r[0] for r in cur.fetchall()]
            if ids:
                placeholders = ",".join("?" * len(ids))
                cur.execute(
                    f"""INSERT INTO agent_memory_archive
                       (user_id, session_id, role, content, created_at)
                       SELECT user_id, session_id, role, content, created_at
                       FROM agent_memory WHERE id IN ({placeholders})""",
                    ids,
                )
                cur.execute(
                    f"DELETE FROM agent_memory WHERE id IN ({placeholders})", ids
                )
                conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"[memory] 记忆归档失败 session={session_id}: {e}")

    # ---- 管理 ----

    def clear_session(self, session_id: str) -> None:
        """彻底清空某会话记忆：内存 + SQLite（agent_memory 表），供「清空对话」使用"""
        if session_id in self._sessions:
            del self._sessions[session_id]
        self._loaded.discard(session_id)
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            uid = self._parse_user_id(session_id)
            cur.execute(
                "DELETE FROM agent_memory WHERE user_id=? AND session_id=?",
                (uid, session_id),
            )
            cur.execute(
                "DELETE FROM agent_memory_archive WHERE user_id=? AND session_id=?",
                (uid, session_id),
            )
            conn.commit()
            conn.close()
            logger.info(f"[memory] 已清空会话记忆 session={session_id}")
        except Exception as e:
            logger.warning(f"[memory] 清空会话记忆失败 session={session_id}: {e}")

    def get_stats(self, session_id: str) -> Dict[str, int]:
        if session_id not in self._sessions:
            return {"short_term": 0, "long_term": 0}
        return {
            "short_term": len(self._sessions[session_id]["short_term"]),
            "long_term": len(self._sessions[session_id]["long_term"]),
        }

    # ---- M2：会话元数据（左侧会话列表 / 归档 / 删除） ----

    def _upsert_conversation(self, session_id: str, user_text: str) -> None:
        """每次用户发言时 upsert 会话行（标题=首条消息前 24 字，last_message=最新）"""
        try:
            uid = self._parse_user_id(session_id)
            title = (user_text or "").strip().replace("\n", " ")[:24]
            conn = self._db_conn()
            cur = conn.cursor()
            # 已有则更新 last_message + updated_at；否则插入（标题只在首次设置）
            cur.execute(
                """SELECT id, title FROM agent_conversations
                   WHERE user_id=? AND session_id=?""",
                (uid, session_id),
            )
            row = cur.fetchone()
            if row:
                if not row["title"] and title:
                    cur.execute(
                        "UPDATE agent_conversations SET title=?, last_message=?, updated_at=datetime('now','localtime') WHERE id=?",
                        (title, (user_text or "")[:100], row["id"]),
                    )
                else:
                    cur.execute(
                        "UPDATE agent_conversations SET last_message=?, updated_at=datetime('now','localtime') WHERE id=?",
                        ((user_text or "")[:100], row["id"]),
                    )
            else:
                cur.execute(
                    """INSERT INTO agent_conversations (user_id, session_id, title, last_message)
                       VALUES (?, ?, ?, ?)""",
                    (uid, session_id, title, (user_text or "")[:100]),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"[memory] upsert 会话元数据失败 session={session_id}: {e}")

    def list_conversations(self, user_id: int, include_archived: bool = False, limit: int = 30) -> List[Dict[str, Any]]:
        """列出用户的会话（默认不含已归档；include_archived=True 时含全部）"""
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            if include_archived:
                cur.execute(
                    """SELECT session_id, title, last_message, archived, updated_at
                       FROM agent_conversations WHERE user_id=?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (user_id, limit),
                )
            else:
                cur.execute(
                    """SELECT session_id, title, last_message, archived, updated_at
                       FROM agent_conversations WHERE user_id=? AND archived=0
                       ORDER BY updated_at DESC LIMIT ?""",
                    (user_id, limit),
                )
            rows = cur.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"[memory] 列表会话失败 user={user_id}: {e}")
            return []

    def archive_conversation(self, user_id: int, session_id: str, archived: bool = True) -> bool:
        """归档/取消归档会话（归档后从最近列表消失，历史 agent_memory 仍保留可查）"""
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            cur.execute(
                "UPDATE agent_conversations SET archived=?, updated_at=datetime('now','localtime') WHERE user_id=? AND session_id=?",
                (1 if archived else 0, user_id, session_id),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.warning(f"[memory] 归档会话失败 session={session_id}: {e}")
            return False

    def delete_conversation(self, user_id: int, session_id: str) -> bool:
        """彻底删除会话（元数据 + 全部记忆，不可恢复）"""
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM agent_conversations WHERE user_id=? AND session_id=?",
                (user_id, session_id),
            )
            cur.execute(
                "DELETE FROM agent_memory WHERE user_id=? AND session_id=?",
                (user_id, session_id),
            )
            cur.execute(
                "DELETE FROM agent_memory_archive WHERE user_id=? AND session_id=?",
                (user_id, session_id),
            )
            conn.commit()
            conn.close()
            if session_id in self._sessions:
                del self._sessions[session_id]
            self._loaded.discard(session_id)
            return True
        except Exception as e:
            logger.warning(f"[memory] 删除会话失败 session={session_id}: {e}")
            return False

