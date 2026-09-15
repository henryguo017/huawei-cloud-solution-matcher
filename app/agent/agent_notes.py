# -*- coding: utf-8 -*-
"""L4-P2-4 自写记忆（agent_notes）：模型在**任务进行中**主动记录/检索可复用知识。

与 memory_profiles（情景记忆）的分工 —— 二者互补，不重复：
  memory_profiles : 宿主在任务**结束后**自动编码 (需求, 终稿)，是"经历"；
  agent_notes     : 模型在任务**进行中**用工具主动写入的**结论/事实/口径**，是"它决定要记住的东西"。

scope 三档与注入纪律：
  session → 仅同会话后续轮次可见（临时工作笔记）；
  client  → 绑定 client_id 的客户事实（必须带 client_id，否则拒绝 —— 防多客户串味）；
  global  → 用户级方法论/口径（如"我司报价一律含 3 年维保"），跨会话注入。

反幻觉铁律：memory_write 的返回值是**宿主确认的落库结果**，并纳入 verify.py 完成态核验
—— 模型不得声称"已记住"而实际没落库（与"声称已建档实则没落库"是同一类事故）。
"""
import contextvars
import json
import logging
from typing import Any, Dict, List, Optional

from app.utils.db_init import get_db_connection
from app.models.llm import get_embedding_vector

logger = logging.getLogger(__name__)

# ===== 本次 Agent 运行的上下文（供 memory_write/memory_search 工具无参读取） =====
# 与 knowledge_base.set_kb_user_context 同一机制：contextvars 沿 await 链自然传播，
# FC 运行时与 legacy 路径的 tool.execute 都在同任务内，无需改 Tool.execute 签名。
_current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("agent_notes_session", default="")
_current_client_id: contextvars.ContextVar[int] = contextvars.ContextVar("agent_notes_client", default=0)


def set_run_context(session_id: str, client_id: Optional[int] = None) -> None:
    """在 harness.run() 启动时设置，本次运行内的工具调用均可读取。"""
    _current_session_id.set(str(session_id or ""))
    _current_client_id.set(int(client_id) if isinstance(client_id, int) and client_id > 0 else 0)


def get_run_context() -> Dict[str, Any]:
    """返回 {"user_id", "session_id", "client_id"}；user_id 来自 kb 用户上下文（API 层已设置）。"""
    from app.services.knowledge_base import get_kb_user_context
    uid = get_kb_user_context()
    cid = _current_client_id.get()
    return {
        "user_id": uid if uid and uid > 0 else None,
        "session_id": _current_session_id.get() or "",
        "client_id": cid if cid > 0 else None,
    }

SCOPES = ("session", "client", "global")
TITLE_MAX = 120
CONTENT_MAX = 4000
TAGS_MAX = 8
SEARCH_TOP_K = 5
INJECT_TOP_K = 5
INJECT_MAX_CHARS = 1200


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def save_note(user_id: int, session_id: str, scope: str, title: str, content: str,
              tags: Optional[List[str]] = None, client_id: Optional[int] = None) -> Dict[str, Any]:
    """写入一条笔记。返回 {"ok": bool, "note_id": int|None, "message": str} —— **宿主确认的落库结果**。"""
    scope = (scope or "").strip().lower()
    title = (title or "").strip()[:TITLE_MAX]
    content = (content or "").strip()[:CONTENT_MAX]
    if scope not in SCOPES:
        return {"ok": False, "note_id": None,
                "message": f"scope 必须是 {'/'.join(SCOPES)} 之一，收到 {scope!r}"}
    if not title or not content:
        return {"ok": False, "note_id": None, "message": "title 与 content 均不能为空"}
    if scope == "client" and not (isinstance(client_id, int) and client_id > 0):
        return {"ok": False, "note_id": None,
                "message": "scope=client 必须提供有效的 client_id（客户档案 ID），否则会造成多客户信息串味"}
    tags = [str(t).strip()[:24] for t in (tags or []) if str(t).strip()][:TAGS_MAX]

    try:
        emb = get_embedding_vector(f"{title}\n{content}")
    except Exception as e:  # noqa: BLE001 - 编码失败不阻断落库（退化为不可检索，但内容已保存）
        logger.warning("[agent_notes] 向量编码失败（笔记仍落库，但检索不可用）: %s", e)
        emb = None

    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO agent_notes(user_id, session_id, scope, client_id, title, content,"
                " tags_json, embedding_json) VALUES(?,?,?,?,?,?,?,?)",
                (int(user_id), session_id, scope, client_id if scope == "client" else None,
                 title, content, json.dumps(tags, ensure_ascii=False),
                 json.dumps(emb) if emb else None),
            )
            conn.commit()
            note_id = cur.lastrowid
        finally:
            conn.close()
        logger.info("[agent_notes] 落库 OK id=%s user=%s scope=%s title=%s", note_id, user_id, scope, title)
        return {"ok": True, "note_id": note_id,
                "message": f"已记录（#{note_id}，scope={scope}，标题：{title}）"}
    except Exception as e:  # noqa: BLE001
        logger.warning("[agent_notes] 落库失败: %s", e)
        return {"ok": False, "note_id": None, "message": f"落库失败：{e}"}


def search_notes(user_id: int, query: str, scope: Optional[str] = None,
                 client_id: Optional[int] = None, session_id: Optional[str] = None,
                 top_k: int = SEARCH_TOP_K) -> List[Dict[str, Any]]:
    """向量检索该用户（及可选 client/session）的笔记，返回 [{note_id, scope, title, content, tags, score}]。"""
    query = (query or "").strip()
    if not query:
        return []
    try:
        qv = get_embedding_vector(query)
    except Exception as e:  # noqa: BLE001
        logger.warning("[agent_notes] 查询向量编码失败: %s", e)
        return []

    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            if scope in SCOPES:
                cur.execute(
                    "SELECT id, session_id, scope, client_id, title, content, tags_json, embedding_json"
                    " FROM agent_notes WHERE user_id=? AND scope=? ORDER BY id DESC LIMIT 200",
                    (int(user_id), scope),
                )
            else:
                cur.execute(
                    "SELECT id, session_id, scope, client_id, title, content, tags_json, embedding_json"
                    " FROM agent_notes WHERE user_id=? ORDER BY id DESC LIMIT 200",
                    (int(user_id),),
                )
            rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[agent_notes] 检索失败: %s", e)
        return []

    out: List[Dict[str, Any]] = []
    for r in rows or []:
        nid, sid, sc, cid, title, content, tags_json, emb_json = (list(r) + [None] * 8)[:8]
        # 作用域过滤：client 笔记只对同客户可见；session 笔记只对同会话可见
        if sc == "client" and client_id and cid and int(cid) != int(client_id):
            continue
        if sc == "session" and session_id and sid and str(sid) != str(session_id):
            continue
        try:
            emb = json.loads(emb_json) if emb_json else None
        except Exception:  # noqa: BLE001
            emb = None
        score = _cosine(qv, emb) if emb else 0.0
        try:
            tags = json.loads(tags_json) if tags_json else []
        except Exception:  # noqa: BLE001
            tags = []
        out.append({"note_id": nid, "scope": sc, "title": title, "content": content,
                    "tags": tags or [], "score": round(float(score), 4)})
    out.sort(key=lambda d: d["score"], reverse=True)
    return out[:max(1, min(int(top_k or SEARCH_TOP_K), 20))]


def build_notes_context(user_id: Optional[int], session_id: str,
                        client_id: Optional[int] = None) -> str:
    """任务启动时注入的「我的笔记」块（global + 本客户 + 本会话），带来源标注。"""
    if not (isinstance(user_id, int) and user_id > 0):
        return ""
    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, scope, title, content, tags_json FROM agent_notes"
                " WHERE user_id=? AND (scope='global' OR (scope='client' AND client_id=?)"
                " OR (scope='session' AND session_id=?))"
                " ORDER BY id DESC LIMIT 40",
                (int(user_id), client_id if isinstance(client_id, int) and client_id > 0 else -1,
                 session_id),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[agent_notes] 注入上下文读取失败（忽略）: %s", e)
        return ""
    if not rows:
        return ""

    SCOPE_LABEL = {"global": "全局口径", "client": "客户事实", "session": "本会话笔记"}
    lines = []
    for nid, sc, title, content, tags_json in rows[:INJECT_TOP_K]:
        try:
            tags = json.loads(tags_json) if tags_json else []
        except Exception:  # noqa: BLE001
            tags = []
        tag_s = f"（标签：{'、'.join(tags)}）" if tags else ""
        lines.append(f"- [{SCOPE_LABEL.get(sc, sc)}] {title}{tag_s}：{(content or '')[:300]}（笔记 #{nid}）")
    if not lines:
        return ""
    block = "\n".join(lines)[:INJECT_MAX_CHARS]
    return (
        "【我的笔记（用户此前让我记住的内容，属于**可信的口径与事实**，可直接使用并注明「据我的记录」）】\n"
        + block
    )


def count_notes(user_id: int) -> int:
    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(1) FROM agent_notes WHERE user_id=?", (int(user_id),))
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return 0
