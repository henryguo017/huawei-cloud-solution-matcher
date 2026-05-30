from fastapi import APIRouter, Depends, HTTPException, status
from app.models.user_models import (
    UserCreate, UserLogin, UserResponse, Token,
    HistoryCreate, HistoryResponse,
    FavoriteCreate, FavoriteResponse,
    ProfileUpdate, PasswordChange
)
from app.services.auth_service import AuthService
from app.utils.captcha_utils import generate_captcha
from api.auth_dependencies import get_current_user, get_current_user_optional
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
    
    return {"message": result["message"], "user_id": result["user_id"]}

@router.post("/login")
async def login(login_data: UserLogin):
    result = AuthService.login(login_data)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result["message"]
        )
    
    return {
        "access_token": result["access_token"],
        "token_type": result["token_type"],
        "expires_in": result["expires_in"],
        "user": result["user"]
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
    return {"message": "已退出登录"}

@router.patch("/profile")
async def update_profile(
    profile_data: ProfileUpdate,
    current_user: dict = Depends(get_current_user)
):
    if profile_data.email is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未提供需要更新的字段"
        )
    result = AuthService.update_profile(current_user["id"], profile_data.email)
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )
    return {"message": result["message"]}

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

@router.get("/stats")
async def get_user_stats(current_user: dict = Depends(get_current_user)):
    stats = AuthService.get_user_stats(current_user["id"])
    return stats

router_history = APIRouter(prefix="/history", tags=["历史记录"])

@router_history.post("/")
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

@router_history.get("/")
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

router_favorites = APIRouter(prefix="/favorites", tags=["收藏"])

@router_favorites.post("/")
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

@router_favorites.get("/")
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
