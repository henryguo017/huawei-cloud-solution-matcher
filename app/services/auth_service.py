from datetime import datetime, timedelta
from typing import Optional
import sqlite3
import os
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
    RESET_TOKEN_EXPIRE_MINUTES
)
import logging

logger = logging.getLogger(__name__)

class AuthService:
    
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
        忘记密码：根据邮箱生成重置 token
        不管邮箱是否存在都返回成功（防邮箱探测）
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # 查找用户
            cursor.execute("SELECT id, username, email FROM users WHERE email = ?", (email,))
            user = cursor.fetchone()
            
            if not user:
                # 邮箱不存在，返回成功（静默）
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
            email_sent = send_reset_email(email, token)
            
            if email_sent:
                logger.info(f"✅ 密码重置邮件已发送到 {email}")
            else:
                logger.error(f"❌ 密码重置邮件发送失败: {email}")
                # 不返回错误，避免暴露邮箱是否存在
            
            return {"success": True, "message": "如果该邮箱已注册，重置链接已发送"}
            
        except Exception as e:
            logger.error(f"❌ 忘记密码处理失败: {e}")
            return {"success": True, "message": "如果该邮箱已注册，重置链接已发送"}
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
