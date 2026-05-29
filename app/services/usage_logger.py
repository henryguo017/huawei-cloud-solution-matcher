"""
使用日志服务 - 记录系统操作日志，为Dashboard提供真实统计数据
"""
import sqlite3
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from threading import Lock

logger = logging.getLogger(__name__)

MAX_MATCH_HISTORY = 100  # 历史记录上限，超过时自动删除最老的

# 单例锁
_instance_lock = Lock()
_instance = None


class UsageLoggerService:
    """使用日志服务：记录每次匹配/分析操作到 SQLite"""

    def __init__(self, db_path: str = None):
        """
        初始化日志服务

        Args:
            db_path: SQLite 数据库路径，默认存储在 data/usage_logs.db
        """
        if db_path is None:
            data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "usage_logs.db")

        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        """获取数据库连接（每次新建连接以保证线程安全）"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表结构"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT    NOT NULL CHECK(action_type IN ('match', 'analyze')),
                    detail      TEXT,                        -- JSON 详情（如竞品名、行业）
                    created_at  DATETIME DEFAULT (datetime('now', 'localtime'))
                )
            """)
            # 为查询性能创建索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_type ON usage_logs(action_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_date ON usage_logs(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_type_date ON usage_logs(action_type, created_at)")

            # 匹配历史记录表（用于回溯和对比）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS match_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    demand_text TEXT    NOT NULL,              -- 原始需求描述
                    solution    TEXT    NOT NULL,              -- 完整方案内容（Markdown）
                    industry    TEXT,                          -- 识别出的行业
                    sources     TEXT,                          -- JSON 参考文档列表
                    created_at  DATETIME DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_date ON match_history(created_at)")
            conn.commit()
            logger.info(f"使用日志数据库已初始化: {self.db_path}")

    def log_match(self, demand_text: str = ""):
        """
        记录一次解决方案匹配操作

        Args:
            demand_text: 用户需求文本（可选，用于审计）
        """
        try:
            detail = {"demand_length": len(demand_text)} if demand_text else {}
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO usage_logs (action_type, detail) VALUES (?, ?)",
                    ("match", json.dumps(detail, ensure_ascii=False))
                )
                conn.commit()
        except Exception as e:
            logger.error(f"记录 match 日志失败: {e}")

    def log_analyze(self, competitor: str, industry: str):
        """
        记录一次竞品分析操作

        Args:
            competitor: 竞品名称
            industry: 行业名称
        """
        try:
            detail = {"competitor": competitor, "industry": industry}
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO usage_logs (action_type, detail) VALUES (?, ?)",
                    ("analyze", json.dumps(detail, ensure_ascii=False))
                )
                conn.commit()
        except Exception as e:
            logger.error(f"记录 analyze 日志失败: {e}")

    def get_total_counts(self) -> Dict[str, int]:
        """
        获取总操作次数统计

        Returns:
            {"match": int, "analyze": int}
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT action_type, COUNT(*) as count FROM usage_logs GROUP BY action_type"
                )
                result = {"match": 0, "analyze": 0}
                for row in cursor.fetchall():
                    result[row["action_type"]] = row["count"]
                return result
        except Exception as e:
            logger.error(f"获取总计数失败: {e}")
            return {"match": 0, "analyze": 0}

    def get_recent_counts(self, days: int = 7) -> Dict[str, int]:
        """
        获取最近 N 天的操作次数统计

        Args:
            days: 统计天数（默认7天）

        Returns:
            {"match": int, "analyze": int}
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(f"""
                    SELECT action_type, COUNT(*) as count
                    FROM usage_logs
                    WHERE date(created_at) >= date('now', 'localtime', '-{days-1} days')
                    GROUP BY action_type
                """)
                result = {"match": 0, "analyze": 0}
                for row in cursor.fetchall():
                    result[row["action_type"]] = row["count"]
                return result
        except Exception as e:
            logger.error(f"获取最近{days}天计数失败: {e}")
            return {"match": 0, "analyze": 0}

    def get_daily_trends(self, days: int = 5) -> List[Dict[str, Any]]:
        """
        获取最近 N 天的每日操作趋势

        Args:
            days: 天数（默认7天）

        Returns:
            [{"date": "MM-DD", "matches": int, "analyses": int}, ...]
        """
        try:
            with self._get_connection() as conn:
                # 生成日期范围
                today = datetime.now()
                results = []

                for i in range(days - 1, -1, -1):
                    date = today - timedelta(days=i)
                    date_str = date.strftime("%Y-%m-%d")
                    display_str = date.strftime("%m-%d")

                    cursor = conn.execute(
                        """
                        SELECT
                            SUM(CASE WHEN action_type = 'match' THEN 1 ELSE 0 END) as matches,
                            SUM(CASE WHEN action_type = 'analyze' THEN 1 ELSE 0 END) as analyses
                        FROM usage_logs
                        WHERE date(created_at) = date(?)
                        """,
                        (date_str,)
                    )
                    row = cursor.fetchone()
                    results.append({
                        "date": display_str,
                        "matches": row["matches"] or 0,
                        "analyses": row["analyses"] or 0
                    })

                return results
        except Exception as e:
            logger.error(f"获取每日趋势失败: {e}")
            return []

    def get_competitor_frequency(self) -> Dict[str, int]:
        """
        获取各竞品被分析的次数统计

        Returns:
            {"竞品名": 次数, ...}
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT detail FROM usage_logs WHERE action_type = 'analyze'"
                )
                freq = {}
                for row in cursor.fetchall():
                    try:
                        detail = json.loads(row["detail"])
                        competitor = detail.get("competitor", "未知")
                        freq[competitor] = freq.get(competitor, 0) + 1
                    except (json.JSONDecodeError, AttributeError):
                        continue
                return freq
        except Exception as e:
            logger.error(f"获取竞品频次失败: {e}")
            return {}

    def get_growth_rates(self, days: int = 7) -> Dict[str, Optional[float]]:
        """
        获取最近N天 vs 前N天的环比增长率（7日环比）

        - 最近N天：today - (N-1) ~ today
        - 前N天：   today - (2N-1) ~ today - N

        Returns:
            {
                "match_growth":    float or None,  # 百分比，如 25.0 表示 +25%
                "analyze_growth":  float or None   # None 表示前一区间无数据（新增长）
            }
        """
        try:
            with self._get_connection() as conn:
                # 最近N天（含今天）
                cursor = conn.execute(f"""
                    SELECT
                        SUM(CASE WHEN action_type = 'match'   THEN 1 ELSE 0 END) AS matches,
                        SUM(CASE WHEN action_type = 'analyze' THEN 1 ELSE 0 END) AS analyses
                    FROM usage_logs
                    WHERE date(created_at) >= date('now', 'localtime', '-{days-1} days')
                """)
                recent = cursor.fetchone()

                # 前N天
                cursor = conn.execute(f"""
                    SELECT
                        SUM(CASE WHEN action_type = 'match'   THEN 1 ELSE 0 END) AS matches,
                        SUM(CASE WHEN action_type = 'analyze' THEN 1 ELSE 0 END) AS analyses
                    FROM usage_logs
                    WHERE date(created_at) >= date('now', 'localtime', '-{days*2-1} days')
                      AND date(created_at) <= date('now', 'localtime', '-{days} days')
                """)
                previous = cursor.fetchone()

                match_recent  = recent["matches"]  or 0
                match_prev    = previous["matches"] or 0
                analyze_recent = recent["analyses"]  or 0
                analyze_prev   = previous["analyses"] or 0

                # match 涨幅
                if match_prev > 0:
                    match_growth = round((match_recent - match_prev) / match_prev * 100, 1)
                elif match_recent > 0:
                    match_growth = None   # 前一区间为0，新增长
                else:
                    match_growth = 0.0    # 两个区间都是0

                # analyze 涨幅
                if analyze_prev > 0:
                    analyze_growth = round((analyze_recent - analyze_prev) / analyze_prev * 100, 1)
                elif analyze_recent > 0:
                    analyze_growth = None   # 前一区间为0，新增长
                else:
                    analyze_growth = 0.0

                return {
                    "match_growth":   match_growth,
                    "analyze_growth": analyze_growth
                }

        except Exception as e:
            logger.error(f"获取增长率失败: {e}")
            return {"match_growth": None, "analyze_growth": None}

    def get_recent_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的日志记录（用于调试）"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM usage_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取最近日志失败: {e}")
            return []

    # ========== 历史记录（方案匹配回溯 & 对比） ==========

    def save_match_history(self, demand_text: str, solution: str, industry: str = "", sources: List[Dict[str, Any]] = None) -> Optional[int]:
        """
        保存一次匹配方案到历史记录

        Returns:
            新记录 id，保存失败返回 None
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "INSERT INTO match_history (demand_text, solution, industry, sources) VALUES (?, ?, ?, ?)",
                    (
                        demand_text,
                        solution,
                        industry,
                        json.dumps(sources or [], ensure_ascii=False)
                    )
                )
                conn.commit()
                self._trim_match_history(conn)
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"保存匹配历史记录失败: {e}")
            return None

    def update_match_history_solution(self, record_id: int, solution: str) -> bool:
        """
        更新指定历史记录的方案内容（用于追问优化后保存最终版）
        Returns:
            更新成功返回 True，失败返回 False
        """
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE match_history SET solution = ? WHERE id = ?",
                    (solution, record_id)
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新匹配历史方案失败(id={record_id}): {e}")
            return False

    def _trim_match_history(self, conn):
        """
        清理超限的历史记录（保留最新的 MAX_MATCH_HISTORY 条）
        在 save_match_history 的同一事务中调用，自动提交
        """
        try:
            cursor = conn.execute("SELECT COUNT(*) AS cnt FROM match_history")
            row = cursor.fetchone()
            if row is None:
                return
            count = row["cnt"]
            if count > MAX_MATCH_HISTORY:
                # 删除最老的（保留最新 MAX_MATCH_HISTORY 条）
                conn.execute("""
                    DELETE FROM match_history
                    WHERE id NOT IN (
                        SELECT id FROM match_history
                        ORDER BY created_at DESC
                        LIMIT ?
                    )
                """, (MAX_MATCH_HISTORY,))
                logger.info(f"历史记录自动清理：{count} → {MAX_MATCH_HISTORY} 条")
        except Exception as e:
            logger.warning(f"历史记录清理失败（不影响保存）: {e}")

    def get_match_history_list(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取匹配历史记录列表（按时间倒序）"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT id, demand_text, industry, created_at
                    FROM match_history
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,)
                )
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    results.append({
                        "id": row["id"],
                        "demand_text": row["demand_text"],
                        "industry": row["industry"] or "",
                        "created_at": row["created_at"]
                    })
                return results
        except Exception as e:
            logger.error(f"获取匹配历史列表失败: {e}")
            return []

    def get_match_history_by_id(self, history_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 获取单条匹配历史记录（含完整方案内容）"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM match_history WHERE id = ?",
                    (history_id,)
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return {
                    "id": row["id"],
                    "demand_text": row["demand_text"],
                    "solution": row["solution"],
                    "industry": row["industry"] or "",
                    "sources": json.loads(row["sources"]) if row["sources"] else [],
                    "created_at": row["created_at"]
                }
        except Exception as e:
            logger.error(f"获取匹配历史记录失败: {e}")
            return None


def get_usage_logger() -> UsageLoggerService:
    """获取 UsageLoggerService 单例"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = UsageLoggerService()
    return _instance
