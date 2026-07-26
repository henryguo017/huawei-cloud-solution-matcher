"""
方案分享路由：生成只读分享链接 / 读取分享内容。
匿名可用（get_current_user_optional），不暴露任何用户身份或后台入口。
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from api.auth_dependencies import get_current_user_optional
from app.services.share_service import ShareService
from app.services.achievement_service import get_achievement_service

logger = logging.getLogger(__name__)

router = APIRouter()
_share_service = ShareService()


class ShareCreateRequest(BaseModel):
    title: Optional[str] = None
    payload: Dict[str, Any]


class ShareResponse(BaseModel):
    share_id: str
    url: str  # 相对路径，前端用 location.origin 拼接成完整链接
    newly_unlocked: List[Dict[str, Any]] = []  # 分享解锁的成就（如"分享达人"），匿名用户为空


@router.post("/share", response_model=ShareResponse)
async def create_share(req: ShareCreateRequest, user=Depends(get_current_user_optional)):
    share_id = _share_service.create_share(req.title, req.payload)
    if not share_id:
        raise HTTPException(status_code=500, detail="创建分享失败，请稍后重试")
    # 已登录用户首次分享触发"分享达人"成就（check_page_view 内解锁 first_share）
    # 匿名用户不触发成就（成就归属账号）；usage_logs 表 action_type 有 CHECK 约束不可直接记 share，故走成就检测解锁
    newly_unlocked = []
    if user:
        try:
            svc = get_achievement_service()
            newly_unlocked = svc.check_page_view(user["id"], "share")
            logger.info(f"[Share] user_id={user.get('id')} 成就检测结果: {len(newly_unlocked)} 个解锁 ({[a.get('id') for a in newly_unlocked]})")
        except Exception as e:
            logger.warning(f"[Share] 成就检测失败: {e}", exc_info=True)
    return ShareResponse(
        share_id=share_id,
        url=f"/share.html?id={share_id}",
        newly_unlocked=newly_unlocked,
    )


@router.get("/share/{share_id}")
async def get_share(share_id: str):
    data = _share_service.get_share(share_id)
    if not data:
        raise HTTPException(status_code=404, detail="分享不存在或已失效")
    return data
