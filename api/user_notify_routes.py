# -*- coding: utf-8 -*-
"""用户级 IM 通知绑定路由（飞书 / 钉钉，按账号隔离）。

所有接口需登录；secret 永不回传前端（列表仅返脱敏 webhook + 启用态）。
依赖 app.services.notify 的 DB 访问函数与 app.utils.db_init 的表结构。
"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth_dependencies import get_current_user
from app.services import notify

router = APIRouter(prefix="/user/notify", tags=["用户通知绑定"])


def _uid(user: dict):
    return user.get("id") or user.get("user_id")


class BindReq(BaseModel):
    platform: str          # 'feishu' | 'dingtalk'
    webhook: str
    secret: str = ""
    enabled: int = 1


class PlatformReq(BaseModel):
    platform: str


@router.get("/bindings")
async def get_bindings(user: dict = Depends(get_current_user)):
    """列出当前用户已绑定的平台（脱敏）。"""
    return {"bindings": notify.list_user_bindings(_uid(user))}


@router.post("/bind")
async def bind(req: BindReq, user: dict = Depends(get_current_user)):
    """绑定 / 更新某平台（幂等 upsert）。"""
    if req.platform not in ("feishu", "dingtalk"):
        return {"success": False, "error": "platform 仅支持 feishu / dingtalk"}
    if not req.webhook:
        return {"success": False, "error": "webhook 不能为空"}
    try:
        notify.save_user_binding(_uid(user), req.platform, req.webhook, req.secret, int(bool(req.enabled)))
    except Exception as e:  # pragma: no cover
        return {"success": False, "error": str(e)}
    return {"success": True, "bindings": notify.list_user_bindings(_uid(user))}


@router.post("/unbind")
async def unbind(req: PlatformReq, user: dict = Depends(get_current_user)):
    """解绑某平台。"""
    if req.platform not in ("feishu", "dingtalk"):
        return {"success": False, "error": "platform 仅支持 feishu / dingtalk"}
    notify.delete_user_binding(_uid(user), req.platform)
    return {"success": True, "bindings": notify.list_user_bindings(_uid(user))}


@router.post("/test")
async def test(req: PlatformReq, user: dict = Depends(get_current_user)):
    """向该平台绑定发测试消息，即时返回成败（便于前端反馈）。"""
    if req.platform not in ("feishu", "dingtalk"):
        return {"success": False, "error": "platform 仅支持 feishu / dingtalk"}
    ok, err = notify.test_user_binding(_uid(user), req.platform)
    return {"success": ok, "error": err}
