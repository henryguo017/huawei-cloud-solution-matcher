# -*- coding: utf-8 -*-
"""API Key 服务（2026-09-15）：cloudsol CLI 公开分发的认证与配额地基。

设计要点：
  - key 明文形如 `ck_<48hex>`，只在签发响应里返回一次；库中仅存 sha256 哈希；
  - 配额按自然日计数（api_keys.daily_date/daily_count），仅约束 API Key 身份的
    Agent 调用（agent/chat），网页 JWT 用户与只读查询接口不受限；
  - 上限读 env `API_KEY_DAILY_LIMIT`（默认 20），商业化时分档只改配置；
  - 轻依赖：stdlib + db_init.get_db_connection，不 import app.config（与
    dingtalk_bot 的独立读取风格一致，避免拉起重依赖链）。

运行环境：FastAPI 主服务进程内（api/auth_dependencies.py 与 api/agent_routes.py 调用）。
"""
import hashlib
import logging
import os
import secrets
import sqlite3
import time
from datetime import datetime

from app.utils.db_init import get_db_connection

logger = logging.getLogger(__name__)

KEY_PREFIX_TAG = "ck_"
DEFAULT_DAILY_LIMIT = 20


class ApiKeyService:
    """API Key 的签发 / 认证 / 配额 / 吊销。全部静态方法，无实例状态。"""

    @staticmethod
    def _daily_limit() -> int:
        try:
            return max(1, int(os.getenv("API_KEY_DAILY_LIMIT", str(DEFAULT_DAILY_LIMIT))))
        except (TypeError, ValueError):
            return DEFAULT_DAILY_LIMIT

    @staticmethod
    def _hash_key(plain: str) -> str:
        return hashlib.sha256(plain.encode("utf-8")).hexdigest()

    @staticmethod
    def issue_key(user_id: int, name: str = "") -> dict:
        """签发新 key：明文仅在返回值中出现一次。"""
        if not isinstance(user_id, int) or user_id <= 0:
            return {"success": False, "message": "无效的用户身份"}
        plain = KEY_PREFIX_TAG + secrets.token_hex(24)
        prefix = plain[:11]  # ck_ + 8 hex，展示用
        name = (name or "").strip()[:50]
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO api_keys (user_id, key_hash, key_prefix, name) VALUES (?, ?, ?, ?)",
                (user_id, ApiKeyService._hash_key(plain), prefix, name),
            )
            conn.commit()
            key_id = cursor.lastrowid
            logger.info("[apikey] 签发 user_id=%s key_id=%s prefix=%s", user_id, key_id, prefix)
            return {"success": True, "id": key_id, "key": plain,
                    "key_prefix": prefix, "daily_limit": ApiKeyService._daily_limit()}
        except sqlite3.Error as e:
            logger.warning("[apikey] 签发失败 user_id=%s: %s", user_id, e)
            return {"success": False, "message": "签发失败，请重试"}
        finally:
            conn.close()

    @staticmethod
    def list_keys(user_id: int) -> list:
        """列出本人全部 key（脱敏，无明文）。"""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, key_prefix, name, created_at, revoked, daily_date, daily_count "
                "FROM api_keys WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            )
            today = time.strftime("%Y-%m-%d")
            rows = []
            for r in cursor.fetchall():
                used = r["daily_count"] if r["daily_date"] == today else 0
                rows.append({
                    "id": r["id"], "key_prefix": r["key_prefix"], "name": r["name"],
                    "created_at": r["created_at"], "revoked": bool(r["revoked"]),
                    "today_used": used, "daily_limit": ApiKeyService._daily_limit(),
                })
            return rows
        finally:
            conn.close()

    @staticmethod
    def revoke_key(user_id: int, key_id: int) -> bool:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE api_keys SET revoked = 1 WHERE id = ? AND user_id = ? AND revoked = 0",
                (key_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def authenticate(plain_key: str) -> "dict | None":
        """校验明文 key → {"key_id", "user_id", "key_prefix"}；无效/吊销/过期返回 None。"""
        if not plain_key or not plain_key.startswith(KEY_PREFIX_TAG):
            return None
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, user_id, key_prefix, expires_at FROM api_keys "
                "WHERE key_hash = ? AND revoked = 0",
                (ApiKeyService._hash_key(plain_key),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            if row["expires_at"]:
                try:
                    if datetime.fromisoformat(str(row["expires_at"])) < datetime.now():
                        return None
                except ValueError:
                    pass
            return {"key_id": row["id"], "user_id": row["user_id"], "key_prefix": row["key_prefix"]}
        finally:
            conn.close()

    @staticmethod
    def consume_quota(key_id: int) -> "tuple[bool, int, int]":
        """消费一次今日配额：返回 (allowed, used_after, limit)。

        只应在真正要跑 Agent 引擎的入口调用（agent/chat）；查询类接口不计数。
        """
        limit = ApiKeyService._daily_limit()
        today = time.strftime("%Y-%m-%d")
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT daily_date, daily_count, revoked FROM api_keys WHERE id = ?",
                (key_id,),
            )
            row = cursor.fetchone()
            if not row or row["revoked"]:
                return (False, 0, limit)
            used = row["daily_count"] if row["daily_date"] == today else 0
            if used >= limit:
                return (False, used, limit)
            new_used = used + 1
            cursor.execute(
                "UPDATE api_keys SET daily_date = ?, daily_count = ? WHERE id = ?",
                (today, new_used, key_id),
            )
            conn.commit()
            return (True, new_used, limit)
        except sqlite3.Error as e:
            # 配额检查本身故障时放行（可用性优先），但记录告警
            logger.warning("[apikey] 配额检查异常 key_id=%s（放行）: %s", key_id, e)
            return (True, -1, limit)
        finally:
            conn.close()
