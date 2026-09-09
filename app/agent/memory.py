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
import json
import logging
from typing import Any, Dict, List
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
        """
        把 session_id 解析出 user_id，兼容多种前端命名格式：
          - "123:client_x"        → 123        (历史：冒号分隔，已在用)
          - "user_42_1700000000"  → 42         (本次：前端 Agent 改用的 user_<uid>_<ts>)
          - "agent_1700000000"    → 0          (历史匿名)
          - "guest_1700000000"    → 0          (未登录)
          - 其它 / 解析失败       → 0
        注意：返回 0 时 _persist 仍落库（uid=0），但不同用户在同一进程隔离由 session_id 唯一性保证；
              跨进程重启后通过 DB 联合键 (user_id, session_id) 恢复互不串号。
        """
        sid = str(session_id or '')
        try:
            if ':' in sid:
                return int(sid.split(':', 1)[0])
            if sid.startswith('user_'):
                parts = sid.split('_')
                if len(parts) >= 2:
                    return int(parts[1])
            if sid.isdigit():
                return int(sid)
            return 0
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

    def add_user_message(self, session_id: str, content: str, images: Any = None) -> None:
        self._ensure_loaded(session_id)
        session = self._get_or_create_session(session_id)
        session["long_term"].append(MemoryEntry(role="user", content=content))
        self._persist(session_id, "user", content, images=images)
        self._trim_long_term(session_id)
        self._trim_and_archive(session_id)

    def add_agent_response(self, session_id: str, content: str) -> None:
        self._ensure_loaded(session_id)
        session = self._get_or_create_session(session_id)
        session["long_term"].append(MemoryEntry(role="agent", content=content))
        self._persist(session_id, "agent", content)
        self._trim_long_term(session_id)
        self._trim_and_archive(session_id)

    def _persist(self, session_id: str, role: str, content: str, images: Any = None) -> None:
        """单条长期记忆落库（截断 2000 字，写失败降级内存仅记日志）。

        边界审计（2026-09-07）：原 500 字截断会把方案/文档类回答砍得只剩开头，
        重启后"方案里的成本明细给我列一下"这类追问无法从历史恢复上下文。
        方案正文通常 3~8k 字，2000 字可保住章节骨架与成本表；DB 体积可忽略。

        images（2026-09-09 跨设备同步）：用户消息的图片元数据 [{path,name}]，
        JSON 落 agent_memory.images 列，供另一台设备恢复历史时显示图片徽标。
        """
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            uid = self._parse_user_id(session_id)
            cur.execute(
                "INSERT INTO agent_memory (user_id, session_id, role, content, images) VALUES (?, ?, ?, ?, ?)",
                (uid, session_id, role, content[:2000], self._dump_json(images)),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"[memory] 长期记忆落库失败 session={session_id}: {e}")

    # ---- JSON / 时间戳辅助（2026-09-09 跨设备同步） ----

    @staticmethod
    def _dump_json(v: Any) -> str:
        try:
            return json.dumps(v or [], ensure_ascii=False)
        except Exception:
            return "[]"

    @staticmethod
    def _load_json(s: Any) -> List[Any]:
        try:
            v = json.loads(s) if s else []
            return v if isinstance(v, list) else []
        except Exception:
            return []

    @staticmethod
    def _local_ts(s: Any) -> int:
        """'YYYY-MM-DD HH:MM:SS' → 毫秒时间戳（前端 relTime 用 ms）。解析失败返回 0。"""
        try:
            return int(time.mktime(time.strptime(str(s), "%Y-%m-%d %H:%M:%S")) * 1000)
        except Exception:
            return 0

    def get_history_messages(self, session_id: str, limit: int = 60) -> List[Dict[str, str]]:
        """结构化历史（[{role, content}]，时间正序）——供前端历史补全接口使用。

        注意：与 get_conversation_history 不同，这里返回结构化列表而非拼好的文本。
        单条 content 受 _persist 500 字截断限制（DB 里的存量即截断后的）。
        """
        self._ensure_loaded(session_id)
        entries = self._get_or_create_session(session_id)["long_term"]
        out = [
            {"role": e.role, "content": e.content}
            for e in entries if e.role in ("user", "agent")
        ]
        return out[-limit:]

    # ---- 会话元数据管理（2026-09-08 对话管理真服务端化） ----
    # 前端右上角 归档/重命名/删除 此前只写 localStorage，服务端 agent_memory 无感——
    # 属于历史迁移双轨问题。以下方法配合 agent_sessions 表（db_init）提供真身。

    def _session_uid(self, session_id: str) -> int:
        return self._parse_user_id(session_id)

    def set_session_title(self, session_id: str, title: str) -> bool:
        try:
            conn = self._db_conn()
            conn.execute("""
                INSERT INTO agent_sessions (user_id, session_id, title, updated_at)
                VALUES (?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(session_id) DO UPDATE SET
                    title=excluded.title, updated_at=datetime('now', 'localtime')
            """, (self._session_uid(session_id), session_id, (title or '')[:80]))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.warning(f"[memory] 会话改名落库失败 session={session_id}: {e}")
            return False

    def set_session_archived(self, session_id: str, archived: bool) -> bool:
        try:
            conn = self._db_conn()
            conn.execute("""
                INSERT INTO agent_sessions (user_id, session_id, archived, updated_at)
                VALUES (?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(session_id) DO UPDATE SET
                    archived=excluded.archived, updated_at=datetime('now', 'localtime')
            """, (self._session_uid(session_id), session_id, 1 if archived else 0))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.warning(f"[memory] 会话归档标记落库失败 session={session_id}: {e}")
            return False

    def delete_session(self, session_id: str) -> int:
        """物理删除会话：agent_memory 消息行 + agent_sessions 元数据行 + 内存缓存。

        返回删除的 agent_memory 行数（0 也可能合法：无消息的空会话）。
        """
        uid = self._session_uid(session_id)
        deleted = 0
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM agent_memory WHERE user_id=? AND session_id=?", (uid, session_id))
            deleted = cur.rowcount or 0
            cur.execute("DELETE FROM agent_sessions WHERE session_id=?", (session_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"[memory] 会话删除落库失败 session={session_id}: {e}")
            return deleted
        # 同步清内存缓存，防已删会话被内存残留"复活"
        self._sessions.pop(session_id, None)
        self._loaded.discard(session_id)
        return deleted

    # ---- 跨设备历史同步（2026-09-09 方案A'：服务端为唯一事实源） ----
    # 背景：消息本就落 agent_memory，但无列表/消息读取接口，前端只读 localStorage，
    # 导致换设备后历史全部"消失"。以下方法补齐 服务端读侧 + 元数据 upsert + 一次性迁移。

    def upsert_session_meta(self, session_id: str, title: Any = None, cap: Any = None,
                            client_id: Any = None, client_name: Any = None,
                            docs: Any = None) -> bool:
        """会话元数据 upsert：只更新传入的字段（None = 保持原值），行不存在则创建。

        前端在建对话（首条消息）/附件变更时推送；rename/archive 走原 setter。
        """
        try:
            conn = self._db_conn()
            conn.execute("""
                INSERT INTO agent_sessions (user_id, session_id, title, updated_at)
                VALUES (?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at=datetime('now', 'localtime')
            """, (self._session_uid(session_id), session_id, (str(title) if title else '')[:80]))
            sets, args = [], []
            if title is not None:
                sets.append("title=?"); args.append(str(title)[:80])
            if cap is not None:
                sets.append("cap=?"); args.append(str(cap)[:80])
            if client_id is not None:
                sets.append("client_id=?"); args.append(int(client_id))
            if client_name is not None:
                sets.append("client_name=?"); args.append(str(client_name)[:80])
            if docs is not None:
                sets.append("docs=?"); args.append(self._dump_json(docs))
            if sets:
                args.append(session_id)
                conn.execute(
                    f"UPDATE agent_sessions SET {', '.join(sets)} WHERE session_id=?", args
                )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.warning(f"[memory] 会话元数据落库失败 session={session_id}: {e}")
            return False

    def list_sessions(self, user_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        """该用户全部会话元数据（跨设备列表接口的数据源）。

        两层数据源：
        1) agent_sessions —— 有元数据真身的会话（含 cap/client/docs 扩展列）；
        2) 孤儿恢复 —— agent_memory 里有消息但没有 agent_sessions 行的会话
           （2026-09-08 管理端点上线前的历史），title 用首条用户消息兜底，
           并回填 agent_sessions 让后续 rename/archive 有落点。
        按 updated_ts 毫秒降序返回。
        """
        uid = int(user_id or 0)
        out: Dict[str, Dict[str, Any]] = {}
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            try:
                cur.execute(
                    """SELECT session_id, title, archived, cap, client_id, client_name,
                              docs, updated_at
                       FROM agent_sessions WHERE user_id=?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (uid, limit),
                )
                for r in cur.fetchall():
                    keys = set(r.keys())
                    out[r["session_id"]] = {
                        "session_id": r["session_id"],
                        "title": r["title"] or "",
                        "archived": bool(r["archived"]),
                        "cap": r["cap"] if "cap" in keys else "",
                        "client_id": r["client_id"],
                        "client_name": (r["client_name"] if "client_name" in keys else "") or "",
                        "docs": self._load_json(r["docs"]) if "docs" in keys else [],
                        "updated_ts": self._local_ts(r["updated_at"]),
                        "msg_count": 0,
                    }
            except Exception:
                # 旧库缺扩展列时降级为基础列（正常情况走不到：db_init 启动时已 ALTER）
                cur.execute(
                    """SELECT session_id, title, archived, updated_at
                       FROM agent_sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT ?""",
                    (uid, limit),
                )
                for r in cur.fetchall():
                    out[r["session_id"]] = {
                        "session_id": r["session_id"], "title": r["title"] or "",
                        "archived": bool(r["archived"]), "cap": "", "client_id": None,
                        "client_name": "", "docs": [],
                        "updated_ts": self._local_ts(r["updated_at"]), "msg_count": 0,
                    }
            # 孤儿恢复：有消息但无元数据行的会话
            cur.execute(
                """SELECT session_id,
                          MIN(CASE WHEN role='user' THEN content END) AS first_user,
                          MAX(created_at) AS last_at,
                          COUNT(*) AS msg_count
                   FROM agent_memory
                   WHERE user_id=? AND session_id NOT IN
                         (SELECT session_id FROM agent_sessions)
                   GROUP BY session_id ORDER BY last_at DESC LIMIT ?""",
                (uid, limit),
            )
            orphans = cur.fetchall()
            if orphans:
                for r in orphans:
                    sid = r["session_id"]
                    title = (r["first_user"] or "").strip()[:80] or "未命名对话"
                    out[sid] = {
                        "session_id": sid, "title": title, "archived": False,
                        "cap": "", "client_id": None, "client_name": "", "docs": [],
                        "updated_ts": self._local_ts(r["last_at"]),
                        "msg_count": r["msg_count"] or 0,
                    }
                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO agent_sessions
                               (user_id, session_id, title, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?)""",
                            (uid, sid, title, r["last_at"], r["last_at"]),
                        )
                    except Exception:
                        pass
                conn.commit()
            # 消息计数（前端可比对本地条数决定是否懒加载）
            if out:
                sids = list(out.keys())
                marks = ",".join("?" * len(sids))
                cur.execute(
                    f"SELECT session_id, COUNT(*) AS c FROM agent_memory "
                    f"WHERE session_id IN ({marks}) GROUP BY session_id",
                    sids,
                )
                for r in cur.fetchall():
                    if r["session_id"] in out:
                        out[r["session_id"]]["msg_count"] = r["c"] or 0
            conn.close()
        except Exception as e:
            logger.warning(f"[memory] 会话列表读取失败 user_id={user_id}: {e}")
        return sorted(out.values(), key=lambda x: x["updated_ts"], reverse=True)

    def get_session_messages(self, session_id: str, user_id: int, limit: int = 400) -> List[Dict[str, Any]]:
        """会话全量消息（跨设备懒加载读侧）：agent_memory 与 agent_memory_archive
        的并集按时间正序（归档迁移保留原 created_at，30 天/窗口外消息不丢）。

        归属校验由路由层完成，这里再按 user_id 过滤一次双保险。
        images 列存在时一并返回；旧库缺列降级为内存窗口历史。
        """
        uid = int(user_id or 0)
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            cur.execute(
                """SELECT role, content, images FROM (
                       SELECT role, content, images, created_at, id, 0 AS pri FROM agent_memory
                        WHERE user_id=? AND session_id=? AND role IN ('user','agent')
                       UNION ALL
                       SELECT role, content, '' AS images, created_at, id, 1 AS pri
                         FROM agent_memory_archive
                        WHERE user_id=? AND session_id=? AND role IN ('user','agent')
                   ) ORDER BY created_at ASC, pri ASC, id ASC LIMIT ?""",
                (uid, session_id, uid, session_id, limit),
            )
            rows = cur.fetchall()
            conn.close()
            msgs = []
            for r in rows:
                m = {"role": r["role"], "content": r["content"]}
                imgs = self._load_json(r["images"] if "images" in r.keys() else "")
                if imgs:
                    m["images"] = imgs
                msgs.append(m)
            return msgs
        except Exception as e:
            logger.warning(f"[memory] 会话消息读取失败 session={session_id}: {e}，降级内存窗口")
            try:
                return self.get_history_messages(session_id, limit=limit)
            except Exception:
                return []

    def import_session(self, session_id: str, title: str, messages: List[Dict[str, Any]],
                       cap: str = "", client_id: Any = None, client_name: str = "",
                       docs: Any = None) -> Dict[str, Any]:
        """一次性迁移（方案A'）：把纯本地会话的消息补插落库。

        幂等策略 append-only：服务端已有 N 条则只补插第 N 条之后的尾部，
        重复调用不产生重复消息、不覆盖已有内容。返回 {imported, existing}。
        """
        uid = self._session_uid(session_id)
        inserted, existing = 0, 0
        try:
            conn = self._db_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM agent_memory WHERE user_id=? AND session_id=?",
                (uid, session_id),
            )
            existing = cur.fetchone()[0] or 0
            tail = messages[existing:] if existing < len(messages) else []
            for m in tail:
                role = "user" if m.get("role") == "user" else "agent"
                cur.execute(
                    "INSERT INTO agent_memory (user_id, session_id, role, content, images) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (uid, session_id, role, str(m.get("content") or "")[:4000],
                     self._dump_json(m.get("images"))),
                )
                inserted += 1
            # 先提交关闭本连接再写元数据：upsert_session_meta 会另开连接，
            # 持有未提交事务时嵌套开连会 database is locked（Windows/低并发同样会踩）
            conn.commit()
            conn.close()
            if inserted or not existing:
                self.upsert_session_meta(
                    session_id, title=title, cap=cap, client_id=client_id,
                    client_name=client_name, docs=docs,
                )
        except Exception as e:
            logger.warning(f"[memory] 会话迁移落库失败 session={session_id}: {e}")
        return {"imported": inserted, "existing": existing}


    def get_conversation_history(self, session_id: str) -> str:
        self._ensure_loaded(session_id)
        if session_id not in self._sessions:
            return "（这是第一次对话）"
        entries = self._sessions[session_id]["long_term"]
        if not entries:
            return "（这是第一次对话）"
        lines = ["【对话历史】"]
        for e in entries:
            role_label = "用户" if e.role == "user" else "助手"
            # 边界审计（2026-09-07）：助手回答 300→1500 字。方案/文档类回答动辄数千字，
            # 300 字只剩开头，"刚才那个方案的网络部分再细化一下"这类追问模型看不到正文。
            # 用户输入语义密度高，400 字足够。
            limit = 1500 if e.role == "agent" else 400
            content = e.content[:limit] + "..." if len(e.content) > limit else e.content
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
        if session_id in self._sessions:
            del self._sessions[session_id]
        self._loaded.discard(session_id)

    def get_stats(self, session_id: str) -> Dict[str, int]:
        if session_id not in self._sessions:
            return {"short_term": 0, "long_term": 0}
        return {
            "short_term": len(self._sessions[session_id]["short_term"]),
            "long_term": len(self._sessions[session_id]["long_term"]),
        }
