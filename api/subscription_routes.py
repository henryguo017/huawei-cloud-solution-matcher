"""情报订阅 API（2026-09-09）：增删查 / 启停 / 立即运行。全部登录态 + 按用户隔离。"""
import logging
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from api.auth_dependencies import get_current_user
from api.dependencies import rate_limit
from app.services import subscription_service as ss

logger = logging.getLogger(__name__)

router = APIRouter()


class SubscriptionCreate(BaseModel):
    industry: str
    competitors: List[str] = []
    frequency: str = "weekly_mon_9"
    prompt_extra: str = ""
    scheduled_at: Optional[str] = None   # frequency=once 时必填，YYYY-MM-DDTHH:MM


@router.get("/subscriptions", tags=["情报订阅"])
async def list_subscriptions(user: dict = Depends(get_current_user), _: None = Depends(rate_limit(30, 60))):
    uid = user.get("id") or user.get("user_id")
    return {"ok": True, "subscriptions": ss.list_subscriptions(uid)}


@router.post("/subscriptions", tags=["情报订阅"])
async def create_subscription(body: SubscriptionCreate, user: dict = Depends(get_current_user),
                              _: None = Depends(rate_limit(10, 60))):
    uid = user.get("id") or user.get("user_id")
    try:
        sub = ss.create_subscription(
            uid, body.industry, body.competitors, body.frequency,
            prompt_extra=body.prompt_extra, scheduled_at=body.scheduled_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("[订阅] 创建 sub_id=%s user=%s freq=%s industry=%s", sub["id"], uid, body.frequency, body.industry)
    return {"ok": True, "subscription": sub}


@router.post("/subscriptions/{sub_id}/toggle", tags=["情报订阅"])
async def toggle_subscription(sub_id: int, user: dict = Depends(get_current_user),
                              _: None = Depends(rate_limit(30, 60))):
    uid = user.get("id") or user.get("user_id")
    sub = ss.toggle_subscription(uid, sub_id, True)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return {"ok": True, "subscription": sub}


@router.delete("/subscriptions/{sub_id}", tags=["情报订阅"])
async def delete_subscription(sub_id: int, user: dict = Depends(get_current_user),
                              _: None = Depends(rate_limit(30, 60))):
    uid = user.get("id") or user.get("user_id")
    removed = ss.delete_subscription(uid, sub_id)
    if not removed:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return {"ok": True}


@router.post("/subscriptions/{sub_id}/run-now", tags=["情报订阅"])
async def run_subscription_now(sub_id: int, user: dict = Depends(get_current_user),
                               _: None = Depends(rate_limit(2, 60))):
    """手动立即执行（限流 2 次/分钟，便于测试与演示）。同步等待执行结果。"""
    uid = user.get("id") or user.get("user_id")
    sub = ss.get_subscription(uid, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    try:
        result = await ss.execute_subscription(sub)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="执行超时（420s），请稍后查看运行记录")
    return {"ok": True, "result": result}
