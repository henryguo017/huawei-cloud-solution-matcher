from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.models.user_models import (
    UserCreate, UserLogin, HistoryCreate, FavoriteCreate,
    PasswordChange,
    ForgotPassword, ResetPassword
)
from app.services.auth_service import AuthService
from app.utils.captcha_utils import generate_captcha
from app.utils.auth_utils import create_access_token
from api.auth_dependencies import get_current_user
from api.dependencies import get_achievement_service_dep
from typing import Optional

router = APIRouter(prefix="/auth", tags=["认证"])

@router.post("/register")
async def register(user_data: UserCreate):
    result = AuthService.register(user_data)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )
    
    # 注册成功后，在后台为新用户复制默认知识库
    user_id = result["user_id"]
    try:
        from app.services.knowledge_base import KnowledgeBaseService
        import asyncio
        loop = asyncio.get_event_loop()
        # 在 executor 中执行，避免阻塞主线程
        await loop.run_in_executor(None, KnowledgeBaseService.copy_from_default, user_id)
    except Exception as e:
        # 复制失败不阻塞注册，用户可以后续手动重建
        import logging
        logging.getLogger(__name__).warning(f"[注册] 用户{user_id}知识库复制失败（不阻塞注册）: {e}")
    
    return {"message": result["message"], "user_id": result["user_id"]}

@router.post("/login")
async def login(login_data: UserLogin):
    result = AuthService.login(login_data)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result["message"]
        )
    
    # 登录成功，触发成就检查
    newly_unlocked = []
    try:
        achievement_svc = get_achievement_service_dep()
        newly_unlocked = achievement_svc.check_after_login(result["user"]["id"])
    except Exception:
        pass  # 成就检查失败不影响登录
    
    return {
        "access_token": result["access_token"],
        "token_type": result["token_type"],
        "expires_in": result["expires_in"],
        "user": result["user"],
        "newly_unlocked": newly_unlocked
    }

@router.get("/captcha")
async def get_captcha():
    captcha_key, captcha_value, captcha_image = generate_captcha()
    
    return {
        "captcha_key": captcha_key,
        "captcha_image": f"data:image/png;base64,{captcha_image}"
    }

@router.get("/me", response_model=dict)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "email": current_user["email"],
        "role": current_user["role"],
        "status": current_user["status"],
        "created_at": current_user["created_at"],
        "last_login": current_user["last_login"]
    }

@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    result = AuthService.logout(current_user["id"])
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result["message"]
        )
    return {"message": result["message"]}

@router.post("/refresh")
async def refresh_token(current_user: dict = Depends(get_current_user)):
    """
    滑动续期：用当前【仍有效】的 token 换发一个新 token，有效期重置为完整时长。
    安全性由 get_current_user 保证 —— 仅当原 token 未过期且 token_version 校验通过时才放行；
    过期或已登出（token_version 递增）的 token 会被依赖直接拒为 401，无法续期。
    """
    token, expires_in = create_access_token(
        current_user["id"],
        current_user["username"],
        current_user["role"],
        current_user.get("token_version", 1)
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": {
            "id": current_user["id"],
            "username": current_user["username"],
            "email": current_user.get("email"),
            "role": current_user["role"],
            "status": current_user["status"],
        }
    }

class EmailChangeRequest(BaseModel):
    new_email: str


class EmailChangeConfirm(BaseModel):
    new_email: str
    code: str


@router.post("/email/change-request")
async def email_change_request(
    body: EmailChangeRequest,
    current_user: dict = Depends(get_current_user)
):
    """邮箱改绑第一步：向新邮箱发送 6 位验证码（60s 冷却，15 分钟有效）。"""
    result = AuthService.request_email_change(current_user["id"], body.new_email)
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS if result.get("retry_after") else status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )
    return {"message": result["message"]}


@router.post("/email/change-confirm")
async def email_change_confirm(
    body: EmailChangeConfirm,
    current_user: dict = Depends(get_current_user)
):
    """邮箱改绑第二步：校验验证码并正式改绑。"""
    result = AuthService.confirm_email_change(current_user["id"], body.new_email, body.code)
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )
    return {"message": result["message"], "email": result.get("email", "")}

@router.post("/change-password")
async def change_password(
    password_data: PasswordChange,
    current_user: dict = Depends(get_current_user)
):
    result = AuthService.change_password(
        current_user["id"],
        password_data.old_password,
        password_data.new_password
    )
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )
    return {"message": result["message"]}

@router.post("/forgot-password")
async def forgot_password(data: ForgotPassword):
    """
    忘记密码：输入邮箱，发送重置邮件
    不管邮箱是否存在都返回成功（防邮箱探测）
    """
    result = AuthService.forgot_password(data.email)
    return {"message": result["message"]}

@router.post("/reset-password")
async def reset_password(data: ResetPassword):
    """
    重置密码：输入 token + 新密码
    """
    result = AuthService.reset_password(data.token, data.new_password)
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )
    return {"message": result["message"]}

@router.get("/stats")
async def get_user_stats(current_user: dict = Depends(get_current_user)):
    stats = AuthService.get_user_stats(current_user["id"])
    return stats

# ===== 历史记录子路由（支持无尾部斜杠访问） =====
router_history = APIRouter(prefix="/history", tags=["历史记录"])

@router_history.post("")
async def add_history(
    history_data: HistoryCreate,
    current_user: dict = Depends(get_current_user)
):
    result = AuthService.add_history(current_user["id"], history_data)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )

    return {"message": result["message"]}

@router_history.get("")
async def get_history(
    query_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(get_current_user)
):
    history = AuthService.get_history(
        current_user["id"], 
        query_type=query_type,
        page=page,
        page_size=page_size
    )
    
    return {"history": history, "total": len(history)}

# ===== 收藏子路由（支持无尾部斜杠访问） =====
router_favorites = APIRouter(prefix="/favorites", tags=["收藏"])

@router_favorites.post("")
async def add_favorite(
    favorite_data: FavoriteCreate,
    current_user: dict = Depends(get_current_user)
):
    result = AuthService.add_favorite(current_user["id"], favorite_data)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )

    return {"message": result["message"]}

@router_favorites.get("")
async def get_favorites(
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(get_current_user)
):
    favorites = AuthService.get_favorites(
        current_user["id"],
        page=page,
        page_size=page_size
    )
    
    return {"favorites": favorites, "total": len(favorites)}

@router_favorites.delete("/{favorite_id}")
async def remove_favorite(
    favorite_id: int,
    current_user: dict = Depends(get_current_user)
):
    result = AuthService.remove_favorite(current_user["id"], favorite_id)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )
    
    return {"message": result["message"]}

# 将子路由挂载到主 auth router 下
router.include_router(router_history)
router.include_router(router_favorites)
