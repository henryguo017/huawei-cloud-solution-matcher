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


def save_episode(user_id: int, session_id: str, demand: str, answer: str,
                 client_id: Optional[int] = None, success: int = 1,
                 rerun_count: int = 0, plan_json: str = "[]",
                 trajectory_json: str = "[]") -> None:
    """保存一条情景记忆（同步；调用方已用 asyncio.to_thread 包裹，不阻塞主流程）。

    answer 为终稿摘要（harness 传入 answer[:400]）。summary 过短（<30 字符）不存储。
    client_id：客户上下文对话时携带，实现客户级记忆隔离（None=通用对话记忆）。

    L4-P1/T2.1 质量信号扩展（向后兼容，缺省即旧行为）：
    - success：合成成功信号（result.success 且 rerun<=1）
    - rerun_count：Plan 单步重跑/反思重试次数（失败经验 = 教训来源）
    - plan_json/trajectory_json：计划与工具轨迹快照（经验注入讲"怎么做的"）
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
                "(user_id, session_id, demand, summary, embedding_json, client_id, "
                " success, feedback, rerun_count, plan_json, trajectory_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, datetime('now','localtime'))",
                (user_id, session_id, (demand or "")[:500], summary[:500],
                 json.dumps(vec, ensure_ascii=False), client_id,
                 1 if success else 0, int(rerun_count or 0),
                 plan_json or "[]", trajectory_json or "[]"),
            )
            conn.commit()
        finally:
            conn.close()
        logger.info(f"[memory] saved episode user_id={user_id} session={session_id} "
                    f"client={client_id} success={success} rerun={rerun_count}")
    except Exception as e:
        logger.warning(f"[memory] save_episode 失败(忽略): {e}")


def _retrieve(user_id: int, query: str, top_k: int = TOP_K,
              client_id: Optional[int] = None) -> List[dict]:
    try:
        conn = get_db_connection()
        try:
            _cols = "id, demand, summary, embedding_json, success, rerun_count"
            if client_id:
                # 客户上下文对话：只检索该客户自己的情景记忆（跨客户隔离）
                rows = conn.execute(
                    f"SELECT {_cols} FROM agent_episodes "
                    "WHERE user_id = ? AND client_id = ? ORDER BY created_at DESC",
                    (user_id, client_id),
                ).fetchall()
            else:
                # 通用对话：只检索不带客户标记的通用记忆，防止客户方案摘要串入
                rows = conn.execute(
                    f"SELECT {_cols} FROM agent_episodes "
                    "WHERE user_id = ? AND client_id IS NULL ORDER BY created_at DESC",
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
            if sim < 0.60:
                continue  # L4-P1/T2.3：低于相似度阈值的经验是噪声，不注入
            scored.append((sim, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"id": r["id"], "demand": r["demand"], "summary": r["summary"],
             "score": s,
             "success": r["success"] if "success" in r.keys() else 1,
             "rerun_count": r["rerun_count"] if "rerun_count" in r.keys() else 0}
            for s, r in scored[:top_k]
        ]
    except Exception as e:
        logger.warning(f"[memory] retrieve 失败(忽略): {e}")
        return []


def build_memory_context(user_id: int, query: str,
                         client_id: Optional[int] = None) -> str:
    """构造情景记忆上下文（top-k 相关历史方案），截断到 MAX_INJECT_CHARS。

    client_id 隔离语义：客户对话只看该客户记忆；通用对话只看无客户标记记忆。

    L4-P1/T2.3 经验注入升级：
    - 优先注入 success=1 且 feedback>=0 的成功经验（讲"怎么做的"）；
    - 附带至多 1 条 feedback=-1 的失败教训（讲"哪里踩过坑"），帮 Agent 避免重蹈覆辙；
    - 每条带成功/失败标记与重跑次数，让模型能区分可信度。
    """
    if not user_id or not query:
        return ""
    eps = _retrieve(user_id, query, client_id=client_id)
    if not eps:
        return ""
    lines = []
    for e in eps:
        mark = "成功" if e.get("success", 1) else "失败"
        rerun = e.get("rerun_count") or 0
        rerun_note = f"，重跑{rerun}次" if rerun else ""
        lines.append(
            f"- 历史需求：{e['demand']}\n  做法与结果（{mark}{rerun_note}）：{e['summary']}"
        )
    block = "【相关历史任务经验（含做法与教训，供参考复用）】\n" + "\n".join(lines)

    # 截断预算分段（L4-P2/T2.4 修复）：经验块、教训、打法各自独立预算。
    # 此前整体截断 [:900] 会把排在最后的打法块切掉（本地全链测试实锤）。
    block = block[:MAX_INJECT_CHARS]

    # 失败教训附录：最近一条明确点踩的同域经验（与当前需求相似度不要求高，警示价值优先）
    try:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT demand, summary FROM agent_episodes "
                "WHERE user_id = ? AND feedback = -1 AND client_id IS ? "
                "ORDER BY id DESC LIMIT 1",
                (user_id, client_id),
            ).fetchone()
        finally:
            conn.close()
        if row:
            block += (
                f"\n【教训警示】用户曾对类似需求「{(row['demand'] or '')[:80]}」的结果明确不满，"
                f"该次摘要：{(row['summary'] or '')[:150]}——避免重蹈同类做法。"
            )
    except Exception as e:
        logger.warning(f"[memory] 教训检索失败(忽略): {e}")

    # L4-P2/T2.4：可复用打法注入（从成功经验蒸馏，相似度门控，独立预算 400 字）
    try:
        pb = build_playbooks_block(user_id, query)
        if pb:
            block += "\n" + pb[:400]
    except Exception as e:
        logger.warning(f"[memory] 打法注入失败(忽略): {e}")

    return block


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


def set_episode_feedback(user_id: int, session_id: str, value: int) -> bool:
    """L4-P1/T2.2：回写该会话最近一条 episode 的用户反馈（1 点赞 / -1 点踩 / 0 清除）。

    经验注入的信任度来源——点踩的经验会以「教训警示」形式参与后续检索。
    """
    if value not in (1, -1, 0):
        return False
    try:
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "UPDATE agent_episodes SET feedback = ? WHERE id = ("
                "  SELECT id FROM agent_episodes WHERE user_id = ? AND session_id = ?"
                "  ORDER BY id DESC LIMIT 1)",
                (value, user_id, session_id),
            )
            conn.commit()
            return (cur.rowcount or 0) > 0
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[memory] set_episode_feedback 失败(忽略): {e}")
        return False


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


# ==================== L4-P2/T2.4 打法库（playbook 提炼与注入） ====================

PLAYBOOK_TOP_K = 2
PLAYBOOK_MIN_SIM = 0.60
_PLAYBOOK_MIN_EPISODES = 3   # 少于 3 条成功经验不提炼（样本不足，防 LLM 编造）
_PLAYBOOK_MAX_EPISODES = 40  # 每次蒸馏最多读取的最近成功经验条数（控 token）


async def refresh_playbooks(user_id: int) -> dict:
    """从该用户最近的**成功**经验中蒸馏可复用打法（全量重建，幂等）。

    流程：拉最近 N 条 success=1 的 episode → LLM 提炼 0~3 条打法（JSON）→
    逐条 BGE 编码（pattern+trigger）→ DELETE+INSERT 全量重建。
    任何异常只记日志不抛出（best-effort，不影响主链路）。

    返回: {"status": "ok"|"skip"|"error", "playbooks": n, "episodes": m, "reason": str}
    """
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT demand, summary, rerun_count FROM agent_episodes "
                "WHERE user_id = ? AND success = 1 "
                "ORDER BY id DESC LIMIT ?",
                (user_id, _PLAYBOOK_MAX_EPISODES),
            ).fetchall()
        finally:
            conn.close()
        if not rows or len(rows) < _PLAYBOOK_MIN_EPISODES:
            return {"status": "skip", "playbooks": 0, "episodes": len(rows or []),
                    "reason": f"成功经验不足 {_PLAYBOOK_MIN_EPISODES} 条，暂不提炼（防编造）"}

        # 经验清单（截断控 token：每条 需求 60 字 + 做法 150 字）
        items = []
        for i, r in enumerate(rows, 1):
            rerun = r["rerun_count"] if "rerun_count" in r.keys() else 0
            items.append(
                f"{i}. 需求：{(r['demand'] or '')[:60]}\n"
                f"   做法：{(r['summary'] or '')[:150]}{'（重跑' + str(rerun) + '次）' if rerun else ''}"
            )
        from app.models.llm import get_llm_response
        prompt = (
            "你是售前打法提炼器。以下是同一位售前近期成功完成的经验摘要。"
            "请提炼 0~3 条**可复用的打法**（确实重复出现或具普适性的有效工作模式），"
            "每条格式：\n"
            '{"pattern": "打法名(不超过20字)", "trigger": "什么需求时适用(不超过40字)", '
            '"steps": ["步骤1", "步骤2", "…"]}\n'
            "只输出一个 JSON 数组，最多 3 条；没有值得提炼的就输出 []。不要编造、不要泛泛而谈。\n\n"
            "经验清单：\n" + "\n".join(items)
        )
        raw = await get_llm_response(prompt)
        playbooks = _extract_json_array(raw)
        if not isinstance(playbooks, list):
            return {"status": "error", "playbooks": 0, "episodes": len(rows),
                    "reason": "LLM 输出解析失败"}
        # 清洗：最多 3 条，字段齐全且非空
        cleaned = []
        for p in playbooks[:3]:
            if not isinstance(p, dict):
                continue
            pattern = str(p.get("pattern", "")).strip()
            steps = p.get("steps") or []
            if not pattern or not isinstance(steps, list) or not steps:
                continue
            cleaned.append({
                "pattern": pattern[:30],
                "trigger": str(p.get("trigger", "")).strip()[:80],
                "steps": [str(s)[:60] for s in steps[:6]],
            })
        if not cleaned:
            return {"status": "skip", "playbooks": 0, "episodes": len(rows),
                    "reason": "LLM 判定无可提炼的重复模式"}

        # 全量重建（幂等）
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM agent_playbooks WHERE user_id = ?", (user_id,))
            for p in cleaned:
                text = f"{p['pattern']} {p['trigger']}"
                vec = get_embedding_vector(text)
                conn.execute(
                    "INSERT INTO agent_playbooks "
                    "(user_id, pattern, trigger, steps, source_count, embedding_json) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, p["pattern"], p["trigger"],
                     json.dumps(p["steps"], ensure_ascii=False), len(rows),
                     json.dumps(vec, ensure_ascii=False)),
                )
            conn.commit()
        finally:
            conn.close()
        logger.info(f"[memory] playbooks refreshed user_id={user_id} n={len(cleaned)} "
                    f"from {len(rows)} episodes")
        return {"status": "ok", "playbooks": len(cleaned), "episodes": len(rows)}
    except Exception as e:
        logger.warning(f"[memory] refresh_playbooks 失败(忽略): {e}")
        return {"status": "error", "playbooks": 0, "episodes": 0, "reason": str(e)[:120]}


def _extract_json_array(raw: str):
    """从 LLM 输出中稳健提取 JSON 数组（容忍 ```json 围栏 / 前后缀文本）。"""
    if not raw:
        return None
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    # 去掉 markdown 代码围栏后再试
    import re as _re
    m = _re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, _re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            pass
    # 首个 [ 到最后一个 ] 之间
    i, j = raw.find("["), raw.rfind("]")
    if 0 <= i < j:
        try:
            return json.loads(raw[i:j + 1])
        except Exception:  # noqa: BLE001
            return None
    return None


def build_playbooks_block(user_id: int, query: str,
                          top_k: int = PLAYBOOK_TOP_K) -> str:
    """检索可复用打法（BGE 相似度 ≥0.60，top-2），返回注入块（无则空串）。"""
    if not user_id or not query:
        return ""
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT pattern, trigger, steps, source_count, embedding_json "
                "FROM agent_playbooks WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return ""
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
            if sim >= PLAYBOOK_MIN_SIM:
                scored.append((sim, r))
        if not scored:
            return ""
        scored.sort(key=lambda x: x[0], reverse=True)
        lines = []
        for _, r in scored[:top_k]:
            try:
                steps = json.loads(r["steps"] or "[]")
            except Exception:
                steps = []
            step_str = "→".join(steps) if steps else ""
            lines.append(
                f"- 打法「{r['pattern']}」（适用：{r['trigger'] or '同类需求'}）"
                + (f"：{step_str}" if step_str else "")
                + f"（源自{r['source_count']}次成功经验）"
            )
        return "【可复用打法（从你的历史成功经验中提炼，可直接套用或变通）】\n" + "\n".join(lines)
    except Exception as e:
        logger.warning(f"[memory] build_playbooks_block 失败(忽略): {e}")
        return ""


def list_playbooks(user_id: int) -> List[dict]:
    """列出该用户全部打法（管理/前端展示用，不含向量）。"""
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT id, pattern, trigger, steps, source_count, created_at "
                "FROM agent_playbooks WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            try:
                steps = json.loads(r["steps"] or "[]")
            except Exception:
                steps = []
            out.append({
                "id": r["id"], "pattern": r["pattern"], "trigger": r["trigger"],
                "steps": steps, "source_count": r["source_count"],
                "created_at": r["created_at"],
            })
        return out
    except Exception as e:
        logger.warning(f"[memory] list_playbooks 失败(忽略): {e}")
        return []
