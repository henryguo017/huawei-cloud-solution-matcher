# -*- coding: utf-8 -*-
"""
L4 灰度观测（2026-09-14，task #228）：FC 运行指标逐轮落库 + 每日聚合。

设计要点：
- 独立表 fc_gray_runs（usage_logs.db），不碰 usage_logs（其 action_type 有 CHECK 约束）。
- 纯 stdlib sqlite3，不 import 任何 app 模块（与 mcp_server_crm 同构，DB 路径由 __file__ 推导，
  可用 AGENT_METRICS_DB 环境变量覆盖，便于测试隔离）。
- record_fc_gray_run() 由 harness._make_result 统一收口处调用：fire-and-forget，
  任何异常只打日志、绝不影响交付链路。
- 每轮运行（无论 runtime）都落一行：legacy 行用于计算「FC 尝试后回退率」与灰度期总流量。

观测指标对应关系（S4/架构文档口径）：
- 回退率   = attempted 且最终 runtime=legacy 的运行 / attempted
- A11      = FC 运行中 plan_steps>0 且 plan_open_at_final==0 的占比（计划收敛率）
- stopped_by 分布 = model/turns/tokens/wall（model=模型自主终止为健康信号）
- drift_rejections / plan_open_at_final / heal_events 均来自 fc_meta 透传
"""
import json
import logging
import os
import sqlite3
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _db_path() -> str:
    env = (os.getenv("AGENT_METRICS_DB") or "").strip()
    if env:
        return env
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data"
    )
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "usage_logs.db")


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fc_gray_runs (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at         DATETIME DEFAULT (datetime('now', 'localtime')),
            user_id            INTEGER,
            session_id         TEXT,
            intent             TEXT,
            runtime            TEXT DEFAULT 'legacy',
            success            INTEGER DEFAULT 0,
            attempted          INTEGER DEFAULT 0,
            failed             INTEGER DEFAULT 0,
            fail_reason        TEXT,
            turns              INTEGER,
            stopped_by         TEXT,
            compactions        INTEGER,
            plan_updates       INTEGER,
            plan_steps         INTEGER,
            tokens             INTEGER,
            token_budget       INTEGER,
            drift_rejections   INTEGER,
            plan_open_at_final INTEGER,
            heal_events        TEXT,
            elapsed_s          REAL,
            skill_packs        TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fcgray_date ON fc_gray_runs(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fcgray_runtime ON fc_gray_runs(runtime)")
    # 2026-09-16 迁移：存量库补 skill_packs 列（CREATE IF NOT EXISTS 不会改已有表）
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(fc_gray_runs)").fetchall()}
        if "skill_packs" not in cols:
            conn.execute("ALTER TABLE fc_gray_runs ADD COLUMN skill_packs TEXT")
    except sqlite3.Error:
        pass


def record_fc_gray_run(
    user_id: Optional[int] = None,
    session_id: str = "",
    intent: str = "",
    runtime: str = "legacy",
    success: bool = False,
    elapsed_s: float = 0.0,
    fc_meta: Optional[Dict[str, Any]] = None,
) -> bool:
    """一次 Agent 运行落一行。任何异常都被吞掉（观测绝不影响交付）。"""
    try:
        m = fc_meta or {}
        # attempted：显式标记，或本轮实际由 FC 引擎产出（成功路径 fc_meta 不带 attempted 键）
        attempted = 1 if (m.get("attempted") or runtime == "fc") else 0
        failed = 1 if m.get("failed") else 0
        conn = _get_connection()
        try:
            _init_db(conn)
            conn.execute(
                """INSERT INTO fc_gray_runs
                   (user_id, session_id, intent, runtime, success, attempted, failed, fail_reason,
                    turns, stopped_by, compactions, plan_updates, plan_steps, tokens, token_budget,
                    drift_rejections, plan_open_at_final, heal_events, elapsed_s, skill_packs)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id if isinstance(user_id, int) and user_id > 0 else None,
                    (session_id or "")[:80],
                    (intent or "")[:40],
                    runtime if runtime in ("fc", "legacy") else "legacy",
                    1 if success else 0,
                    attempted,
                    failed,
                    str(m.get("reason") or "")[:120],
                    _int(m.get("turns")), str(m.get("stopped_by") or "")[:20],
                    _int(m.get("compactions")), _int(m.get("plan_updates")), _int(m.get("plan_steps")),
                    _int(m.get("tokens")), _int(m.get("token_budget")),
                    _int(m.get("drift_rejections")), _int(m.get("plan_open_at_final")),
                    json.dumps(m.get("heal_events") or [], ensure_ascii=False)[:2000],
                    round(float(elapsed_s or 0), 2),
                    # 技能包挂载记录（slug 列表，2026-09-16）：挂载率×交付质量分析源
                    json.dumps(_pack_slugs(m.get("skill_packs")), ensure_ascii=False)[:500],
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 - 观测失败绝不影响交付
        logger.warning(f"[gray-metrics] 落库失败（忽略）: {e}")
        return False


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _pack_slugs(v) -> list:
    """fc_meta.skill_packs 容错归一：仅保留非空字符串 slug。"""
    if not isinstance(v, (list, tuple)):
        return []
    return [str(s).strip() for s in v if str(s or "").strip()][:10]


def skill_pack_summary(date: str = "") -> Dict[str, int]:
    """技能包挂载统计（date 为空=今天）：包 slug → 挂载次数。供挂载率×质量分析。"""
    conn = _get_connection()
    try:
        _init_db(conn)
        if date:
            rows = conn.execute(
                "SELECT skill_packs FROM fc_gray_runs WHERE date(created_at) = ?", [date]
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT skill_packs FROM fc_gray_runs WHERE date(created_at) = date('now', 'localtime')"
            ).fetchall()
    finally:
        conn.close()
    dist: Dict[str, int] = {}
    for r in rows:
        for slug in _safe_loads(r["skill_packs"]):
            dist[slug] = dist.get(slug, 0) + 1
    return dict(sorted(dist.items(), key=lambda kv: -kv[1]))


def daily_summary(date: str = "") -> Dict[str, Any]:
    """按天聚合灰度观测指标（date 为空=今天，格式 YYYY-MM-DD）。

    返回给 /api/agent/gray-summary 与 CLI；字段含义见模块 docstring。
    """
    conn = _get_connection()
    try:
        _init_db(conn)
        where = "WHERE date(created_at) = ?"
        params: list = [date] if date else ["date('now', 'localtime')"]
        if not date:
            where = "WHERE date(created_at) = date('now', 'localtime')"
            params = []
        rows = conn.execute(f"SELECT * FROM fc_gray_runs {where}", params).fetchall()
    finally:
        conn.close()

    total = len(rows)
    fc_runs = [r for r in rows if r["runtime"] == "fc"]
    attempted = [r for r in rows if r["attempted"]]
    fallbacks = [r for r in attempted if r["runtime"] != "fc"]
    with_plan = [r for r in fc_runs if _int(r["plan_steps"]) > 0]
    closed = [r for r in with_plan if _int(r["plan_open_at_final"]) == 0]

    stopped_by: Dict[str, int] = {}
    for r in fc_runs:
        k = r["stopped_by"] or "unknown"
        stopped_by[k] = stopped_by.get(k, 0) + 1

    def _avg(vals):
        vals = [v for v in vals if v is not None and v > 0]
        return round(sum(vals) / len(vals), 1) if vals else None

    return {
        "date": date or "today",
        "total_runs": total,
        "fc_runs": len(fc_runs),
        "legacy_runs": total - len(fc_runs),
        "fc_attempted": len(attempted),
        "fallbacks": len(fallbacks),
        "fallback_rate": round(len(fallbacks) / len(attempted), 3) if attempted else None,
        "stopped_by": stopped_by,
        "drift_rejections_total": sum(_int(r["drift_rejections"]) for r in fc_runs),
        "runs_with_drift": sum(1 for r in fc_runs if _int(r["drift_rejections"]) > 0),
        "a11_with_plan": len(with_plan),
        "a11_closed": len(closed),
        "a11_rate": round(len(closed) / len(with_plan), 3) if with_plan else None,
        "runs_open_at_final": sum(1 for r in fc_runs if _int(r["plan_open_at_final"]) > 0),
        "heal_events_total": sum(
            len(_safe_loads(r["heal_events"])) for r in fc_runs
        ),
        "avg_turns_fc": _avg([_int(r["turns"]) or None for r in fc_runs]),
        "avg_tokens_fc": _avg([_int(r["tokens"]) or None for r in fc_runs]),
        "avg_elapsed_fc": _avg([r["elapsed_s"] for r in fc_runs]),
        "success_rate_fc": (
            round(sum(1 for r in fc_runs if r["success"]) / len(fc_runs), 3) if fc_runs else None
        ),
        # 技能包观测（2026-09-16）：挂载运行数 + 包分布（15 包从"存在"到"可度量"）
        "skill_pack_mounted_runs": sum(
            1 for r in rows if _safe_loads(r["skill_packs"])
        ),
        "skill_pack_usage": skill_pack_summary(date or ""),
    }


def _safe_loads(s) -> list:
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


if __name__ == "__main__":
    import sys

    d = sys.argv[1] if len(sys.argv) > 1 else ""
    print(json.dumps(daily_summary(d), ensure_ascii=False, indent=2))
