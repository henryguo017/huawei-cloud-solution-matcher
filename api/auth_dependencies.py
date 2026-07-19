from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import logging
from app.utils.auth_utils import decode_access_token
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    token = credentials.credentials
    
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("user_id")
    token_version = payload.get("token_version", 1)
    user = AuthService.get_user_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 验证 token_version：如果 Token 中的版本低于数据库中的版本，说明用户已登出过
    db_token_version = user.get('token_version', 1)
    if token_version < db_token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if user['status'] != 'active':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用或锁定"
        )
    
    return user

async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))
) -> Optional[dict]:
    if not credentials:
        return None
    
    try:
        token = credentials.credentials
        payload = decode_access_token(token)
        
        if not payload:
            return None
        
        user_id = payload.get("user_id")
        token_version = payload.get("token_version", 1)
        user = AuthService.get_user_by_id(user_id)
        
        if not user or user['status'] != 'active':
            return None
        
        # 验证 token_version：与 get_current_user() 保持一致
        db_token_version = user.get('token_version', 1)
        if token_version < db_token_version:
            return None
        
        return user
    except:
        return None

async def require_login(request: Request) -> dict:
    """
    强制登录依赖（用于智能匹配等需要持久化记忆的接口）。

    - 匿名访问（无 Authorization 令牌）→ 401「请先登录后再使用智能匹配」
    - 有令牌但失效/过期 → 沿用 get_current_user 的 401 文案（令牌已失效，请重新登录等）
    """
    auth_header = request.headers.get('Authorization', '')
    # 诊断日志：记录后端实际收到的 Authorization 头（排查"浏览器未带 token"问题）
    if auth_header:
        logger.warning(
            '[AUTH-DEBUG] require_login 收到 Authorization: 前缀=%r 长度=%d 前20位=%r',
            auth_header[:7], len(auth_header), auth_header[:20]
        )
    else:
        logger.warning(
            '[AUTH-DEBUG] require_login 未收到 Authorization 头! 全部headers=%s',
            dict(request.headers)
        )

    if not auth_header.startswith('Bearer '):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录后再使用智能匹配",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[len('Bearer '):]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id")
    token_version = payload.get("token_version", 1)
    user = AuthService.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    db_token_version = user.get('token_version', 1)
    if token_version < db_token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user['status'] != 'active':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用或锁定"
        )
    return user


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user['role'] != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限"
        )
    return current_user
