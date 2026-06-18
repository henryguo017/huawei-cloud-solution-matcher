"""
成就勋章 API 路由
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from pydantic import BaseModel

from api.models import (
    AchievementListResponse, AchievementUnlockNotification,
)
from app.services.achievement_service import get_achievement_service
from api.dependencies import get_current_user_optional, get_current_user
from api.auth_dependencies import get_current_user as get_current_user_auth

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)


class PageViewRequest(BaseModel):
    page: str  # knowledge / dashboard / share


@router.get(
    "/achievements",
    response_model=AchievementListResponse,
    tags=["成就勋章"],
    summary="获取用户成就列表",
)
async def get_achievements(
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    获取当前用户的成就列表。
    - 已解锁的成就显示完整信息
    - 未解锁的隐藏成就显示 ??? 占位符
    - 未登录用户返回空列表
    """
    if not current_user:
        return AchievementListResponse(
            items=[], total=0, unlocked=0,
            hidden_total=0, hidden_unlocked=0, percent=0,
        )

    user_id = current_user["id"]
    svc = get_achievement_service()
    items = svc.get_user_achievements(user_id)
    stats = svc.get_user_stats(user_id)

    return AchievementListResponse(
        items=items,
        total=stats["total"],
        unlocked=stats["unlocked"],
        hidden_total=stats["hidden_total"],
        hidden_unlocked=stats["hidden_unlocked"],
        percent=stats["percent"],
    )


@router.post(
    "/achievements/page-view",
    tags=["成就勋章"],
    summary="页面访问触发成就检测",
)
async def trigger_page_view_achievement(
    request: PageViewRequest,
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """前端访问知识库/仪表盘/分享时调用，触发对应成就"""
    if not current_user:
        return {"newly_unlocked": []}

    svc = get_achievement_service()
    newly = svc.check_page_view(current_user["id"], request.page)
    return {"newly_unlocked": newly}


@router.get(
    "/achievements/notifications",
    response_model=List[AchievementUnlockNotification],
    tags=["成就勋章"],
    summary="获取待推送的成就解锁通知",
)
async def get_pending_notifications(
    current_user: dict = Depends(get_current_user_auth),
):
    """
    前端在收到业务操作响应后调用此接口，
    获取本轮新解锁的成就列表（用于弹窗提示）。
    实际解锁逻辑在业务路由中同步完成，此接口仅用于查询。
    """
    # 通知由业务端记录在内存/Redis，此处简化为返回空
    # 前端直接从业务响应中获取 newly_unlocked 字段
    return []
