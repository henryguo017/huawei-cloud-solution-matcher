"""
Agent 澄清会话存储（交互式澄清 · 阶段 2.5）

用途：
- Agent 在 ReAct 循环中判断「前置信息不足」时，通过 harness 发出 Clarify 事件并暂停；
- 把当前循环状态（prompt / step 计数 / 原始需求 / 会话维度）暂存到这里，分配 clarify_id；
- 前端弹出提问卡，用户作答后带着 clarify_id + 答案调 /api/agent/clarify；
- 后端用 clarify_id 取回状态，把答案作为 Observation 接回，继续跑（不是重头再来）。

设计：
- 纯进程内字典 + TTL（默认 30 分钟），无需外部存储；
- 带线程锁，生产环境多 worker 下若跨进程则需改为共享存储，当前单进程 uvicorn 足够；
- 与现有 ReAct 只读工具零耦合，不引入任何执行风险。
"""

import time
import threading
from typing import Dict, Any, Optional

# 澄清会话有效期：30 分钟（用户作答通常秒级完成，留足余量应对中途离开）
_TTL = 30 * 60


class ClarifySessionStore:
    _store: Dict[str, Dict[str, Any]] = {}
    _lock = threading.Lock()

    @classmethod
    def put(cls, clarify_id: str, state: Dict[str, Any]) -> None:
        """存入一条澄清会话状态"""
        with cls._lock:
            state = dict(state)
            state["_created"] = time.time()
            cls._store[clarify_id] = state
            cls._cleanup()

    @classmethod
    def get(cls, clarify_id: str) -> Optional[Dict[str, Any]]:
        """取回澄清会话状态；不存在或已过期返回 None"""
        with cls._lock:
            s = cls._store.get(clarify_id)
            if s is None:
                return None
            if time.time() - s.get("_created", 0) > _TTL:
                cls._store.pop(clarify_id, None)
                return None
            return s

    @classmethod
    def delete(cls, clarify_id: str) -> None:
        with cls._lock:
            cls._store.pop(clarify_id, None)

    @classmethod
    def _cleanup(cls) -> None:
        """惰性清理过期条目"""
        now = time.time()
        expired = [k for k, v in cls._store.items() if now - v.get("_created", 0) > _TTL]
        for k in expired:
            cls._store.pop(k, None)
