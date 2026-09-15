"""情报订阅服务（定时自动化，2026-09-09）。

调度模型：api/main.py startup 挂 asyncio 循环（60s 轮询）→ due_subscriptions()
→ execute_subscription()（非流式跑 Agent + 联网搜索）→ 推飞书（复用 notify）+ 落库。
next_run_at 持久化在 DB，服务重启自动恢复；错过超 2 小时的周期任务直接跳到下一周期。
"""
import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta

from app.utils.db_init import get_db_connection

logger = logging.getLogger(__name__)

FREQ_WEEKLY = "weekly_mon_9"   # 每周一 09:00
FREQ_DAILY = "daily_9"         # 每天 09:00
FREQ_ONCE = "once"             # 指定时间一次性
FREQ_WHITELIST = (FREQ_WEEKLY, FREQ_DAILY, FREQ_ONCE)
MAX_PER_USER = 10
EXEC_TIMEOUT = 420             # Agent 执行硬超时（秒），与 chat 主链路一致
STALE_SKIP_SECONDS = 2 * 3600  # 错过超 2 小时的周期任务跳到下一周期


def _now():
    return datetime.now()


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse_dt(s):
    if not s:
        return None
    s = str(s).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _compute_next_run(frequency, scheduled_at, now=None):
    """返回下一次运行时间字符串；once 用完（或已过期）返回 None。"""
    now = now or _now()
    if frequency == FREQ_ONCE:
        sched = _parse_dt(scheduled_at)
        if not sched or sched <= now:
            return None
        return _fmt(sched)
    if frequency == FREQ_DAILY:
        candidate = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return _fmt(candidate)
    if frequency == FREQ_WEEKLY:
        days_ahead = (0 - now.weekday()) % 7   # 0=Monday
        candidate = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=7)
        return _fmt(candidate)
    return None


def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    try:
        d["competitors"] = json.loads(d.get("competitors") or "[]")
    except (TypeError, ValueError):
        d["competitors"] = []
    return d


def create_subscription(user_id, industry, competitors, frequency, prompt_extra="", scheduled_at=None,
                        name="", prompt=""):
    if frequency not in FREQ_WHITELIST:
        raise ValueError("不支持的订阅频率")
    prompt = str(prompt or "").strip()
    industry = str(industry or "").strip()
    name = str(name or "").strip()
    if not isinstance(competitors, list):
        competitors = []
    competitors = [str(c).strip() for c in competitors if str(c).strip()][:10]
    if prompt:
        # 通用自动化任务：自由任务描述；名称缺省取任务描述前 20 字
        name = name or prompt[:20]
    else:
        # 情报模板：行业必填；名称缺省「{行业}情报」
        if not industry:
            raise ValueError("行业不能为空")
        name = name or f"{industry}情报"
    sched_str = None
    if frequency == FREQ_ONCE:
        sched = _parse_dt(scheduled_at)
        if not sched or sched <= _now():
            raise ValueError("请选择未来的执行时间")
        sched_str = _fmt(sched)
    with get_db_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()["n"]
        if count >= MAX_PER_USER:
            raise ValueError(f"每人最多 {MAX_PER_USER} 条订阅")
        next_run = _compute_next_run(frequency, sched_str)
        conn.execute(
            "INSERT INTO subscriptions (user_id, name, prompt, industry, competitors, frequency, scheduled_at, prompt_extra, enabled, next_run_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (user_id, name[:60], prompt[:2000], industry, json.dumps(competitors, ensure_ascii=False), frequency, sched_str,
             str(prompt_extra or "").strip(), next_run),
        )
        row = conn.execute("SELECT * FROM subscriptions WHERE id = last_insert_rowid()").fetchone()
    return _row_to_dict(row)


def list_subscriptions(user_id):
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user_id,)
        ).fetchall()
        out = [_row_to_dict(r) for r in rows]
        for sub in out:
            lr = conn.execute(
                "SELECT ok, summary, created_at FROM subscription_runs WHERE subscription_id = ? "
                "ORDER BY id DESC LIMIT 1", (sub["id"],)
            ).fetchone()
            sub["last_run"] = dict(lr) if lr else None
    return out


def get_subscription(user_id, sub_id):
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE id = ? AND user_id = ?", (sub_id, user_id)
        ).fetchone()
    return _row_to_dict(row)


def toggle_subscription(user_id, sub_id, enabled):
    enabled = 1 if enabled else 0
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ? AND user_id = ?", (sub_id, user_id)).fetchone()
        if row is None:
            return None
        next_run = None
        if enabled:
            d = _row_to_dict(row)
            next_run = _compute_next_run(d["frequency"], d.get("scheduled_at"))
        conn.execute("UPDATE subscriptions SET enabled = ?, next_run_at = ? WHERE id = ?", (enabled, next_run, sub_id))
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
    return _row_to_dict(row)


def delete_subscription(user_id, sub_id):
    with get_db_connection() as conn:
        cur = conn.execute("DELETE FROM subscriptions WHERE id = ? AND user_id = ?", (sub_id, user_id))
        removed = cur.rowcount > 0
        if removed:
            conn.execute("DELETE FROM subscription_runs WHERE subscription_id = ?", (sub_id,))
    return removed


def due_subscriptions(now=None):
    now = now or _now()
    stale_line = now - timedelta(seconds=STALE_SKIP_SECONDS)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM subscriptions WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?",
            (_fmt(now),),
        ).fetchall()
        out = []
        for r in rows:
            d = _row_to_dict(r)
            nxt = _parse_dt(d.get("next_run_at"))
            if d["frequency"] != FREQ_ONCE and nxt and nxt < stale_line:
                # 停机错过太久：跳到下一周期，不补跑（避免重启轰炸）
                conn.execute("UPDATE subscriptions SET next_run_at = ? WHERE id = ?",
                             (_compute_next_run(d["frequency"], None, now), d["id"]))
                continue
            out.append(d)
    return out


def record_run(sub_id, ok, summary, elapsed):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO subscription_runs (subscription_id, ok, summary, elapsed) VALUES (?, ?, ?, ?)",
            (sub_id, 1 if ok else 0, str(summary or "")[:6000], float(elapsed or 0)),
        )


def mark_executed(sub_id, frequency, scheduled_at, ok):
    """更新 last_run_at 与下一次运行时间；once（或反复失败的一次性）执行后停用。"""
    now = _now()
    next_run = _compute_next_run(frequency, scheduled_at, now)
    with get_db_connection() as conn:
        if frequency == FREQ_ONCE or next_run is None:
            conn.execute(
                "UPDATE subscriptions SET last_run_at = ?, next_run_at = NULL, enabled = 0 WHERE id = ?",
                (_fmt(now), sub_id),
            )
        else:
            conn.execute(
                "UPDATE subscriptions SET last_run_at = ?, next_run_at = ? WHERE id = ?",
                (_fmt(now), next_run, sub_id),
            )


def build_prompt(sub):
    custom = str(sub.get("prompt") or "").strip()
    if custom:
        # 通用自动化任务：用户自由描述 + 通用输出约束
        return (
            custom
            + "\n\n（执行要求：如需最新信息请联网检索；输出结构化结果，要点式呈现；"
              "引用外部信息时附来源链接；总长度控制在 1500 字以内。本次为无人值守自动执行，"
              "不要反问、不要请求确认，基于已有信息直接给出结果。）"
        )
    competitors = "、".join(sub.get("competitors") or [])
    prompt = (
        f"请联网搜索并汇总近 7 天「{sub['industry']}」行业"
        + (f"及竞品（{competitors}）" if competitors else "")
        + "的重要动态，覆盖：产品发布或更新、价格调整、中标项目、重要合作与行业新闻。"
        + "输出要点清单（不超过 10 条），每条一句话概括并附来源链接；最后用一段话给出对华为云售前的启示。"
    )
    if sub.get("prompt_extra"):
        prompt += "\n补充要求：" + sub["prompt_extra"]
    return prompt


async def execute_subscription(sub):
    """执行一条订阅：非流式跑 Agent（联网开）→ 落库 → 推飞书。失败重试 1 次。"""
    sub_id = sub["id"]
    user_id = sub["user_id"]
    ok, summary, elapsed = False, "", 0.0
    for attempt in range(2):
        t0 = time.time()
        try:
            if isinstance(user_id, int) and user_id > 0:
                from app.services.knowledge_base import set_kb_user_context
                set_kb_user_context(user_id)
            from app.agent import get_agent
            result = await asyncio.wait_for(
                get_agent().run(
                    build_prompt(sub),
                    session_id=f"sub_{sub_id}_{int(time.time())}",
                    extra_context="",
                    event_callback=None,
                    user_id=user_id,
                ),
                timeout=EXEC_TIMEOUT,
            )
            ok = bool(result.get("success"))
            summary = result.get("answer", "") or ""
            elapsed = time.time() - t0
            if ok:
                break
            logger.warning("[订阅] 第 %s 次执行未成功 sub=%s", attempt + 1, sub_id)
        except Exception as e:
            elapsed = time.time() - t0
            summary = f"执行异常: {e}"
            logger.warning("[订阅] 第 %s 次执行异常 sub=%s: %s", attempt + 1, sub_id, e)
    record_run(sub_id, ok, summary or "（空结果）", elapsed)
    mark_executed(sub_id, sub["frequency"], sub.get("scheduled_at"), ok)

    # 推送（未绑定飞书则仅存站内）：成功推摘要，失败也推通知
    task_name = sub.get("name") or sub.get("industry") or "自动化任务"
    title = "[自动化] " + task_name + ("" if ok else " · 本次执行失败")
    push_text = (summary or "执行失败，请查看站内结果")[:2500]
    try:
        from app.services.notify import notify_for_user
        await asyncio.to_thread(
            notify_for_user, user_id,
            **{"demand": push_text, "industry": sub.get("industry") or "", "title": title,
               "url": "https://cloudsol.cn/"},
        )
    except Exception as e:
        logger.warning("[订阅] 推送失败（忽略，结果已落库） sub=%s: %s", sub_id, e)
    return {"ok": ok, "summary": summary, "elapsed": elapsed}
