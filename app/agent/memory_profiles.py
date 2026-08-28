# -*- coding: utf-8 -*-
"""P2-2 长程记忆：情景记忆(agent_episodes) + 用户画像(user_profile)。

- save_episode：方案类意图成功完成后，把 (需求, 终稿) 编码为 BGE 向量存入 agent_episodes。
- build_memory_context：新任务启动时用 BGE 对历史记忆做余弦检索 top-k，注入 extra_context。
- build_profile_context：读取 user_profile 画像，注入 extra_context。
- clear_episodes / count_episodes：管理接口。

DB 表 agent_episodes / user_profile 由 app/utils/db_init.py 的 init_database() 创建。

⚠️ 本文件为 git 对象损坏后，依据工作记忆 P2-2 片段（TOP_K=3 / MAX_INJECT_CHARS=600 /
summary≥30 字符 / 首轮仅注入一次）重建。若你有原始版本请直接覆盖。
"""
import json
import logging
from typing import List, Optional

from app.utils.db_init import get_db_connection
from app.models.llm import get_embedding_vector

logger = logging.getLogger(__name__)

TOP_K = 3
MAX_INJECT_CHARS = 600
SUMMARY_MIN_CHARS = 30


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def save_episode(user_id: int, session_id: str, demand: str, answer: str) -> None:
    """保存一条情景记忆（同步；调用方已用 asyncio.to_thread 包裹，不阻塞主流程）。

    answer 为终稿摘要（harness 传入 answer[:400]）。summary 过短（<30 字符）不存储。
    """
    try:
        summary = (answer or "").strip()
        if len(summary) < SUMMARY_MIN_CHARS:
            return
        text = f"{demand or ''}\n{answer or ''}".strip()
        vec = get_embedding_vector(text)
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO agent_episodes "
                "(user_id, session_id, demand, summary, embedding_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))",
                (user_id, session_id, (demand or "")[:500], summary[:500],
                 json.dumps(vec, ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()
        logger.debug(f"[memory] saved episode user_id={user_id} session={session_id}")
    except Exception as e:
        logger.warning(f"[memory] save_episode 失败(忽略): {e}")


def _retrieve(user_id: int, query: str, top_k: int = TOP_K) -> List[dict]:
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT id, demand, summary, embedding_json FROM agent_episodes "
                "WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return []
        qvec = get_embedding_vector(query)
        scored = []
        for r in rows:
            try:
                ev = json.loads(r["embedding_json"]) if r["embedding_json"] else None
            except Exception:
                ev = None
            if not ev:
                continue
            sim = _cosine(qvec, ev)
            scored.append((sim, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"id": r["id"], "demand": r["demand"], "summary": r["summary"], "score": s}
            for s, r in scored[:top_k]
        ]
    except Exception as e:
        logger.warning(f"[memory] retrieve 失败(忽略): {e}")
        return []


def build_memory_context(user_id: int, query: str) -> str:
    """构造情景记忆上下文（top-k 相关历史方案），截断到 MAX_INJECT_CHARS。"""
    if not user_id or not query:
        return ""
    eps = _retrieve(user_id, query)
    if not eps:
        return ""
    lines = []
    for e in eps:
        lines.append(f"- 历史需求：{e['demand']}\n  历史方案摘要：{e['summary']}")
    block = "【相关历史方案记忆】\n" + "\n".join(lines)
    return block[:MAX_INJECT_CHARS]


def build_profile_context(user_id: int) -> str:
    """读取用户画像(user_profile)，返回可读上下文。"""
    if not user_id:
        return ""
    try:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT profile_json FROM user_profile WHERE user_id = ?", (user_id,)
            ).fetchone()
        finally:
            conn.close()
        if not row or not row["profile_json"]:
            return ""
        return "【用户画像】\n" + row["profile_json"]
    except Exception as e:
        logger.warning(f"[memory] build_profile_context 失败(忽略): {e}")
        return ""


def clear_episodes(user_id: int) -> int:
    """清空该用户全部情景记忆，返回删除条数。"""
    try:
        conn = get_db_connection()
        try:
            cur = conn.execute("DELETE FROM agent_episodes WHERE user_id = ?", (user_id,))
            n = cur.rowcount
            conn.commit()
        finally:
            conn.close()
        return n or 0
    except Exception as e:
        logger.warning(f"[memory] clear_episodes 失败(忽略): {e}")
        return 0


def count_episodes(user_id: int) -> int:
    try:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM agent_episodes WHERE user_id = ?", (user_id,)
            ).fetchone()
        finally:
            conn.close()
        return int(row["c"]) if row else 0
    except Exception as e:
        logger.warning(f"[memory] count_episodes 失败(忽略): {e}")
        return 0
