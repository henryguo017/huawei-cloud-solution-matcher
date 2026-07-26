"""
方案分享路由：生成只读分享链接 / 读取分享内容。
匿名可用（get_current_user_optional），不暴露任何用户身份或后台入口。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

from api.auth_dependencies import get_current_user_optional
from app.services.share_service import ShareService

router = APIRouter()
_share_service = ShareService()


class ShareCreateRequest(BaseModel):
    title: Optional[str] = None
    payload: Dict[str, Any]


class ShareResponse(BaseModel):
    share_id: str
    url: str  # 相对路径，前端用 location.origin 拼接成完整链接


@router.post("/share", response_model=ShareResponse)
async def create_share(req: ShareCreateRequest, user=Depends(get_current_user_optional)):
    share_id = _share_service.create_share(req.title, req.payload)
    if not share_id:
        raise HTTPException(status_code=500, detail="创建分享失败，请稍后重试")
    return ShareResponse(share_id=share_id, url=f"/share?id={share_id}")


@router.get("/share/{share_id}")
async def get_share(share_id: str):
    data = _share_service.get_share(share_id)
    if not data:
        raise HTTPException(status_code=404, detail="分享不存在或已失效")
    return data
