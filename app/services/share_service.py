"""
方案分享服务 - 生成只读分享链接与二维码所需的快照存储。

独立使用 data/share.db，不影响现有 usage_logs.db / users.db。
分享内容为前端传入的方案快照（JSON），匿名用户也可创建/查看。
"""
import sqlite3
import os
import json
import secrets
import logging
from typing import Optional, Dict, Any
from threading import Lock
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ShareService:
    """方案分享存储：短链 share_id -> 方案快照 payload"""

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data",
        )
        os.makedirs(data_dir, exist_ok=True)
        self.db_path = os.path.join(data_dir, "share.db")
        self._init_db()
        self._initialized = True

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error:
            pass
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shared_solutions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    share_id    TEXT UNIQUE NOT NULL,
                    title       TEXT,
                    payload     TEXT NOT NULL,
                    created_at  DATETIME DEFAULT (datetime('now', 'localtime')),
                    expires_at  DATETIME,
                    view_count  INTEGER DEFAULT 0
                )
            """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_shared_share_id ON shared_solutions(share_id)"
            )
            # 兼容旧库：早期版本没有 expires_at 列
            try:
                conn.execute("ALTER TABLE shared_solutions ADD COLUMN expires_at DATETIME")
            except Exception:
                pass

    def create_share(self, title: str, payload: Dict[str, Any]) -> Optional[str]:
        """保存一份方案快照，返回短链 share_id；失败返回 None。

        payload 约定字段（前端自主构造）：
            kind / title / demand / solution / industry / sources / competitor / created_at
        """
        try:
            self._purge_expired()
            share_id = secrets.token_urlsafe(8)  # 11 字符，url-safe，碰撞概率极低
            expires_at = datetime.now() + timedelta(days=30)
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO shared_solutions (share_id, title, payload, expires_at) VALUES (?, ?, ?, ?)",
                    (
                        share_id,
                        (title or "方案分享")[:120],
                        json.dumps(payload, ensure_ascii=False),
                        expires_at,
                    ),
                )
            logger.info(f"[分享] 已创建分享 share_id={share_id}")
            return share_id
        except Exception as e:
            logger.error(f"[分享] 创建失败: {e}")
            return None

    def get_share(self, share_id: str) -> Optional[Dict[str, Any]]:
        """读取分享内容并自增浏览计数；不存在返回 None。"""
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM shared_solutions WHERE share_id = ? "
                    "AND (expires_at IS NULL OR expires_at > datetime('now', 'localtime'))",
                    (share_id,)
                ).fetchone()
                if row is None:
                    return None
                conn.execute(
                    "UPDATE shared_solutions SET view_count = view_count + 1 WHERE share_id = ?",
                    (share_id,),
                )
                payload = json.loads(row["payload"]) if row["payload"] else {}
                return {
                    "share_id": row["share_id"],
                    "title": row["title"] or "方案分享",
                    "payload": payload,
                    "created_at": row["created_at"],
                    "view_count": (row["view_count"] or 0) + 1,
                }
        except Exception as e:
            logger.error(f"[分享] 读取失败: {e}")
            return None

    def _purge_expired(self):
        """删除过期分享，避免匿名分享无限占用 SQLite 磁盘。"""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "DELETE FROM shared_solutions "
                    "WHERE expires_at IS NOT NULL AND expires_at < datetime('now', 'localtime')"
                )
        except Exception as e:
            logger.warning(f"[分享] 清理过期数据失败: {e}")
