from datetime import datetime, timedelta
from typing import Optional
import sqlite3
import os
import re
import time
import secrets
from app.utils.db_init import get_db_connection
from app.utils.auth_utils import hash_password, verify_password, create_access_token
from app.utils.captcha_utils import verify_captcha
from app.models.user_models import (
    UserCreate, UserLogin, HistoryCreate, FavoriteCreate
)
from app.config import (
    MAX_LOGIN_ATTEMPTS,
    LOCK_DURATION_MINUTES,
    MAX_FAVORITES_PER_USER,
    RESET_TOKEN_EXPIRE_MINUTES,
    EMAIL_CODE_EXPIRE_MINUTES,
    EMAIL_CODE_RESEND_COOLDOWN
)
import logging

logger = logging.getLogger(__name__)

class AuthService:

    # 邮箱改绑发码冷却（内存级，user_id -> monotonic 时间戳；重启清零，个人部署够用）
    _email_change_last: dict = {}

    @staticmethod
    def register(user_data: UserCreate) -> dict:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT id FROM users WHERE username = ?", (user_data.username,))
            if cursor.fetchone():
                return {"success": False, "message": "用户名已存在"}
            
            if user_data.email:
                cursor.execute("SELECT id FROM users WHERE email = ?", (user_data.email,))
                if cursor.fetchone():
                    return {"success": False, "message": "邮箱已被注册"}
            
            password_hash = hash_password(user_data.password)
            
            cursor.execute("""
                INSERT INTO users (username, email, password_hash, role, status)
                VALUES (?, ?, ?, 'user', 'active')
            """, (user_data.username, user_data.email, password_hash))
            
            user_id = cursor.lastrowid
            conn.commit()
            
            return {
                "success": True,
                "message": "注册成功",
                "user_id": user_id
            }
            
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": f"注册失败: {str(e)}"}
        finally:
            conn.close()
    
    @staticmethod
    def login(login_data: UserLogin) -> dict:
        if not verify_captcha(login_data.captcha_key, login_data.captcha_value):
            return {"success": False, "message": "验证码错误"}
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM users WHERE username = ?", (login_data.username,))
            user = cursor.fetchone()
            
            if not user:
                return {"success": False, "message": "用户名或密码错误"}
            
            user_dict = dict(user)
            
            if user_dict['status'] == 'locked':
                locked_until = user_dict['locked_until']
                if locked_until and datetime.fromisoformat(locked_until) > datetime.now():
                    return {"success": False, "message": f"账户已锁定，请{LOCK_DURATION_MINUTES}分钟后再试"}
                else:
                    cursor.execute("""
                        UPDATE users SET status = 'active', failed_login_count = 0, locked_until = NULL
                        WHERE id = ?
                    """, (user_dict['id'],))
                    conn.commit()
                    user_dict['status'] = 'active'
            
            if not verify_password(login_data.password, user_dict['password_hash']):
                failed_count = user_dict['failed_login_count'] + 1
                
                if failed_count >= MAX_LOGIN_ATTEMPTS:
                    locked_until = datetime.now() + timedelta(minutes=LOCK_DURATION_MINUTES)
                    cursor.execute("""
                        UPDATE users SET status = 'locked', failed_login_count = ?, locked_until = ?
                        WHERE id = ?
                    """, (failed_count, locked_until, user_dict['id']))
                    conn.commit()
                    return {"success": False, "message": f"登录失败次数过多，账户已锁定{LOCK_DURATION_MINUTES}分钟"}
                else:
                    cursor.execute("""
                        UPDATE users SET failed_login_count = ?
                        WHERE id = ?
                    """, (failed_count, user_dict['id']))
                    conn.commit()
                    return {"success": False, "message": f"用户名或密码错误，还剩{MAX_LOGIN_ATTEMPTS - failed_count}次机会"}
            
            access_token, expires_in = create_access_token(
                user_dict['id'],
                user_dict['username'],
                user_dict['role'],
                user_dict.get('token_version', 1)
            )
            
            cursor.execute("""
                UPDATE users SET 
                    last_login = ?,
                    failed_login_count = 0,
                    locked_until = NULL
                WHERE id = ?
            """, (datetime.now(), user_dict['id']))
            
            conn.commit()
            
            return {
                "success": True,
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": expires_in,
                "user": {
                    "id": user_dict['id'],
                    "username": user_dict['username'],
                    "email": user_dict['email'],
                    "role": user_dict['role'],
                    "status": user_dict['status']
                }
            }
            
        except Exception as e:
            return {"success": False, "message": f"登录失败: {str(e)}"}
        finally:
            conn.close()
    
    @staticmethod
    def get_user_by_id(user_id: int) -> Optional[dict]:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return dict(user)
        return None
    
    @staticmethod
    def logout(user_id: int) -> dict:
        """登出：递增 token_version 使该用户所有旧 JWT 立即失效"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE users SET token_version = token_version + 1 WHERE id = ?",
                (user_id,)
            )
            conn.commit()
            return {"success": True, "message": "已退出登录"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": f"登出失败: {str(e)}"}
        finally:
            conn.close()
    
    @staticmethod
    def add_history(user_id: int, history_data: HistoryCreate) -> dict:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO history (user_id, query_type, query_content, result_content)
                VALUES (?, ?, ?, ?)
            """, (user_id, history_data.query_type, history_data.query_content, history_data.result_content))
            
            conn.commit()
            return {"success": True, "message": "历史记录保存成功"}
        except Exception as e:
            return {"success": False, "message": f"保存失败: {str(e)}"}
        finally:
            conn.close()
    
    @staticmethod
    def get_history(user_id: int, query_type: Optional[str] = None, page: int = 1, page_size: int = 20) -> list:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        offset = (page - 1) * page_size
        
        if query_type:
            cursor.execute("""
                SELECT * FROM history 
                WHERE user_id = ? AND query_type = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (user_id, query_type, page_size, offset))
        else:
            cursor.execute("""
                SELECT * FROM history 
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (user_id, page_size, offset))
        
        history = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return history
    
    @staticmethod
    def add_favorite(user_id: int, favorite_data: FavoriteCreate) -> dict:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT COUNT(*) as count FROM favorites WHERE user_id = ?", (user_id,))
            count = cursor.fetchone()['count']
            
            if count >= MAX_FAVORITES_PER_USER:
                return {"success": False, "message": f"收藏数量已达上限（{MAX_FAVORITES_PER_USER}个）"}
            
            cursor.execute("""
                INSERT INTO favorites (user_id, solution_name, solution_content, industry)
                VALUES (?, ?, ?, ?)
            """, (user_id, favorite_data.solution_name, favorite_data.solution_content, favorite_data.industry))
            
            conn.commit()
            return {"success": True, "message": "收藏成功"}
        except sqlite3.IntegrityError:
            return {"success": False, "message": "该方案已收藏"}
        except Exception as e:
            return {"success": False, "message": f"收藏失败: {str(e)}"}
        finally:
            conn.close()
    
    @staticmethod
    def get_favorites(user_id: int, page: int = 1, page_size: int = 20) -> list:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        offset = (page - 1) * page_size
        
        cursor.execute("""
            SELECT * FROM favorites
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (user_id, page_size, offset))
        
        favorites = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return favorites

    @staticmethod
    def remove_favorite(user_id: int, favorite_id: int) -> dict:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM favorites WHERE id=? AND user_id=?", (favorite_id, user_id))
            if cursor.rowcount == 0:
                return {"success": False, "message": "收藏不存在或无权操作"}
            conn.commit()
            return {"success": True, "message": "已取消收藏"}
        except Exception as e:
            return {"success": False, "message": f"取消收藏失败: {str(e)}"}
        finally:
            conn.close()
    
    @staticmethod
    def update_profile(user_id: int, email: str) -> dict:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT id FROM users WHERE email = ? AND id != ?", (email, user_id))
            if cursor.fetchone():
                return {"success": False, "message": "邮箱已被其他用户注册"}
            
            cursor.execute("UPDATE users SET email = ? WHERE id = ?", (email, user_id))
            conn.commit()
            
            return {"success": True, "message": "资料更新成功"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": f"更新失败: {str(e)}"}
        finally:
            conn.close()

    # ===== 邮箱改绑（两步验证码流程，2026-09-06 审计缺口①修复）=====
    # 旧 PATCH /profile 直接写 email 无归属验证，已从路由层移除；改绑一律走：
    #   request_email_change（向新邮箱发 6 位码）→ confirm_email_change（输码确认）

    _EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @staticmethod
    def request_email_change(user_id: int, new_email: str) -> dict:
        """第一步：向新邮箱发送 6 位验证码。发信成功才落库 pending_email/email_code。"""
        new_email = (new_email or "").strip().lower()
        if not AuthService._EMAIL_RE.fullmatch(new_email):
            return {"success": False, "message": "邮箱格式不正确"}

        # 冷却限流：同一账号 60s 内不可重复发码（内存级，重启清零）
        now = time.monotonic()
        last = AuthService._email_change_last.get(user_id, 0.0)
        wait = int(EMAIL_CODE_RESEND_COOLDOWN - (now - last))
        if wait > 0:
            return {"success": False, "message": f"发送太频繁，请 {wait} 秒后再试", "retry_after": wait}

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM users WHERE email = ? AND id != ?", (new_email, user_id))
            if cursor.fetchone():
                return {"success": False, "message": "该邮箱已被其他账号使用"}

            code = f"{secrets.randbelow(1000000):06d}"
            expiry = datetime.now() + timedelta(minutes=EMAIL_CODE_EXPIRE_MINUTES)

            # 先发信，成功才写 pending（避免"提示已发送但邮件没出去"）
            from app.utils.email_utils import send_email_code, smtp_configured
            if not smtp_configured():
                logger.error("[email-change] SMTP 未配置，改绑验证码无法发送")
                return {"success": False, "message": "邮件服务未配置，请联系管理员"}
            if not send_email_code(new_email, code, EMAIL_CODE_EXPIRE_MINUTES):
                return {"success": False, "message": "邮件发送失败，请稍后重试"}

            cursor.execute("""
                UPDATE users SET pending_email = ?, email_code = ?, email_code_expiry = ?
                WHERE id = ?
            """, (new_email, code, expiry, user_id))
            conn.commit()
            AuthService._email_change_last[user_id] = now

            logger.info(f"✅ 用户 {user_id} 邮箱改绑验证码已发送至 {new_email}")
            return {"success": True,
                    "message": f"验证码已发送至 {new_email}，{EMAIL_CODE_EXPIRE_MINUTES} 分钟内有效"}
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ 邮箱改绑请求失败: {e}")
            return {"success": False, "message": "服务暂不可用，请稍后重试"}
        finally:
            conn.close()

    @staticmethod
    def confirm_email_change(user_id: int, new_email: str, code: str) -> dict:
        """第二步：校验验证码，通过则正式改绑并清理 pending 字段。"""
        new_email = (new_email or "").strip().lower()
        code = (code or "").strip()

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT pending_email, email_code, email_code_expiry FROM users WHERE id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            if not row or not row["pending_email"]:
                return {"success": False, "message": "请先获取验证码"}
            if row["pending_email"] != new_email:
                return {"success": False, "message": "邮箱与验证码请求不一致，请重新获取"}

            expiry = row["email_code_expiry"]
            if not expiry or datetime.fromisoformat(str(expiry)) < datetime.now():
                cursor.execute(
                    "UPDATE users SET pending_email = NULL, email_code = NULL, email_code_expiry = NULL WHERE id = ?",
                    (user_id,)
                )
                conn.commit()
                return {"success": False, "message": "验证码已过期，请重新获取"}

            if (row["email_code"] or "") != code:
                return {"success": False, "message": "验证码错误"}

            # 二次唯一性校验（拿码到输码之间邮箱可能被他人抢注）
            cursor.execute("SELECT id FROM users WHERE email = ? AND id != ?", (new_email, user_id))
            if cursor.fetchone():
                return {"success": False, "message": "该邮箱已被其他账号使用"}

            cursor.execute("""
                UPDATE users
                SET email = ?, pending_email = NULL, email_code = NULL, email_code_expiry = NULL
                WHERE id = ?
            """, (new_email, user_id))
            conn.commit()

            logger.info(f"✅ 用户 {user_id} 邮箱已改绑为 {new_email}")
            return {"success": True, "message": "邮箱绑定成功", "email": new_email}
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ 邮箱改绑确认失败: {e}")
            return {"success": False, "message": "服务暂不可用，请稍后重试"}
        finally:
            conn.close()

    @staticmethod
    def change_password(user_id: int, old_password: str, new_password: str) -> dict:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "message": "用户不存在"}
            
            password_hash = row['password_hash']
            
            if not verify_password(old_password, password_hash):
                return {"success": False, "message": "原密码错误"}
            
            new_hash = hash_password(new_password)
            cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
            conn.commit()
            
            return {"success": True, "message": "密码修改成功"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": f"修改失败: {str(e)}"}
        finally:
            conn.close()

    @staticmethod
    def get_user_stats(user_id: int) -> dict:
        stats = {"match_count": 0, "analyze_count": 0, "history_count": 0, "favorites_count": 0}
        
        usage_db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "usage_logs.db")
        
        if os.path.exists(usage_db_path):
            try:
                usage_conn = sqlite3.connect(usage_db_path, timeout=10)
                usage_conn.row_factory = sqlite3.Row
                cursor = usage_conn.cursor()
                
                cursor.execute("SELECT COUNT(*) as cnt FROM usage_logs WHERE action_type='match' AND user_id=?", (user_id,))
                stats["match_count"] = cursor.fetchone()["cnt"]
                
                cursor.execute("SELECT COUNT(*) as cnt FROM usage_logs WHERE action_type='analyze' AND user_id=?", (user_id,))
                stats["analyze_count"] = cursor.fetchone()["cnt"]
                
                cursor.execute("SELECT COUNT(*) as cnt FROM match_history WHERE user_id=?", (user_id,))
                stats["history_count"] = cursor.fetchone()["cnt"]
                
                usage_conn.close()
            except Exception:
                pass
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT COUNT(*) as cnt FROM favorites WHERE user_id=?", (user_id,))
            stats["favorites_count"] = cursor.fetchone()["cnt"]
        except Exception:
            pass
        finally:
            conn.close()
        
        return stats

    @staticmethod
    def forgot_password(email: str) -> dict:
        """
        忘记密码：根据邮箱生成重置 token。

        语义（2026-09-06 收紧）：
        - SMTP 未配置 → 查库【前】统一失败（对所有请求一致，不泄露邮箱是否存在）；
          旧版此处静默成功，用户空等邮件（审计缺口②）。
        - 邮箱不存在 → 统一成功文案（防邮箱探测）。
        - 发送失败/异常 → 显式失败，不再静默成功。
          （注：发送失败仅发生在邮箱已注册时，理论上存在故障期探测面，
          个人部署下诚实报错优先；日志留痕。）
        """
        from app.utils.email_utils import smtp_configured
        if not smtp_configured():
            logger.error("[forgot] SMTP 未配置，忘记密码请求被拒绝（请在 .env 配置 SMTP_USER/SMTP_PASS 后重启）")
            return {"success": False, "message": "邮件服务未配置，请联系管理员"}

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # 查找用户
            cursor.execute("SELECT id, username, email FROM users WHERE email = ?", (email,))
            user = cursor.fetchone()

            if not user:
                # 邮箱不存在，返回成功（静默，防探测）
                return {"success": True, "message": "如果该邮箱已注册，重置链接已发送"}

            # 生成重置 token
            token = secrets.token_urlsafe(32)
            expiry = datetime.now() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)

            # 保存 token 到数据库
            cursor.execute("""
                UPDATE users SET reset_token = ?, reset_token_expiry = ?
                WHERE id = ?
            """, (token, expiry, user['id']))
            conn.commit()

            # 发送重置邮件
            from app.utils.email_utils import send_reset_email
            if send_reset_email(email, token):
                logger.info(f"✅ 密码重置邮件已发送到 {email}")
                return {"success": True, "message": "如果该邮箱已注册，重置链接已发送"}

            logger.error(f"❌ 密码重置邮件发送失败: {email}")
            return {"success": False, "message": "邮件发送失败，请稍后重试；若持续失败请联系管理员"}

        except Exception as e:
            logger.error(f"❌ 忘记密码处理失败: {e}")
            return {"success": False, "message": "服务暂不可用，请稍后重试"}
        finally:
            conn.close()

    @staticmethod
    def reset_password(token: str, new_password: str) -> dict:
        """
        重置密码：验证 token 并设置新密码
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # 查找 token
            cursor.execute("""
                SELECT id, username, reset_token_expiry
                FROM users
                WHERE reset_token = ?
            """, (token,))
            user = cursor.fetchone()
            
            if not user:
                return {"success": False, "message": "无效的重置链接"}
            
            # 检查是否过期
            expiry = user['reset_token_expiry']
            if not expiry or datetime.fromisoformat(expiry) < datetime.now():
                return {"success": False, "message": "重置链接已过期，请重新申请"}
            
            # 重置密码
            new_hash = hash_password(new_password)
            cursor.execute("""
                UPDATE users
                SET password_hash = ?, reset_token = NULL, reset_token_expiry = NULL
                WHERE id = ?
            """, (new_hash, user['id']))
            conn.commit()
            
            logger.info(f"✅ 用户 {user['username']} 密码已重置")
            return {"success": True, "message": "密码已重置，请登录"}
            
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ 重置密码失败: {e}")
            return {"success": False, "message": f"重置失败: {str(e)}"}
        finally:
            conn.close()
