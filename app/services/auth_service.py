from datetime import datetime, timedelta
from typing import Optional
import sqlite3
from app.utils.db_init import get_db_connection
from app.utils.auth_utils import hash_password, verify_password, create_access_token
from app.utils.captcha_utils import verify_captcha
from app.models.user_models import (
    UserCreate, UserLogin, UserResponse, Token,
    HistoryCreate, HistoryResponse,
    FavoriteCreate, FavoriteResponse
)
from app.config import (
    MAX_LOGIN_ATTEMPTS, 
    LOCK_DURATION_MINUTES,
    MAX_FAVORITES_PER_USER
)

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
                user_dict['role']
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
