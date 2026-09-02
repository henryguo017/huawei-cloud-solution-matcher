# -*- coding: utf-8 -*-
"""P1 飞书 / 钉钉群机器人通知适配器（纯标准库，零新依赖）。

设计要点（与项目铁律对齐）：
  - 零新依赖：仅用标准库 urllib / hmac / hashlib / base64 / asyncio，不引入 requests 等第三方包；
  - 默认关：FEISHU_WEBHOOK / DINGTALK_WEBHOOK 任一为空则该平台 no-op，两个都空则整体零副作用；
  - 失败吞掉：任何网络/签名异常只记 warning，绝不向上抛，不拖垮主链路（稳定性铁律）；
  - fire-and-forget：notify_match_complete / notify_agent_result 为同步入口，内部用 safe_fire
    调度到事件循环（或后台线程），不阻塞调用方（经典 match_stream / Agent run_agent 均为异步上下文）；
  - 签名：飞书/钉钉同公式 HMAC-SHA256(timestamp + "\\n" + secret) → base64。

调用方（已读真实代码定位）：
  - 经典：app/services/solution_matcher.py:385（match_stream 的 type:result 入队后）
  - Agent：api/agent_routes.py:95（get_agent().run() 返回、success 为真时）
"""

import os
import json
import time
import hmac
import hashlib
import base64
import logging
import asyncio
import threading
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# 站点入口（通知里点击进 cloudsol 看全文）
SITE_URL = os.getenv("SITE_URL", "https://cloudsol.cn")

# 从环境变量读取（与 config.py 同变量名，单一事实来源=环境变量）
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")
FEISHU_SECRET = os.getenv("FEISHU_SECRET", "")
DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

_HTTP_TIMEOUT = 5.0


# ----------------------------------------------------------------------------
# 底层工具
# ----------------------------------------------------------------------------
def _sign(secret: str):
    """飞书/钉钉通用签名：HMAC-SHA256(timestamp + "\\n" + secret) → base64。

    返回 (timestamp_str, sign_b64)。secret 为空时返回空签名（部分机器人可不开签）。
    """
    ts = str(int(time.time() * 1000))
    if not secret:
        return ts, ""
    string_to_sign = ts + "\n" + secret
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return ts, base64.b64encode(hmac_code).decode("utf-8")


def _post_json(url: str, payload: dict) -> str:
    """同步 POST JSON（供 asyncio.to_thread 调用），异常向上抛由调用方吞。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def _build_markdown(demand: str, industry: str = "", title: str = "", url: str = "") -> str:
    """拼装 Markdown 正文（飞书 interactive card / 钉钉 markdown 均支持）。"""
    lines = []
    if demand:
        lines.append(f"**需求**：{demand}")
    if industry:
        lines.append(f"**行业**：{industry}")
    if title:
        lines.append(f"**方案**：{title}")
    lines.append("cloudsol 已生成方案，可在 PC 端查看完整内容。")
    if url:
        lines.append(f"[点此在 cloudsol 查看全文]({url})")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 平台推送（异步，内部用 to_thread 不阻塞事件循环）
# ----------------------------------------------------------------------------
async def _notify_feishu(title: str, text: str) -> None:
    ts, sign = _sign(FEISHU_SECRET)
    payload = {
        "msg_type": "interactive",
        "timestamp": ts,
        "sign": sign,
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "red",
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": [{"tag": "markdown", "content": text}],
        },
    }
    await asyncio.to_thread(_post_json, FEISHU_WEBHOOK, payload)
    logger.info("[notify] 飞书推送成功")


async def _notify_dingtalk(title: str, text: str) -> None:
    ts, sign = _sign(DINGTALK_SECRET)
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "timestamp": ts,
        "sign": sign,
    }
    await asyncio.to_thread(_post_json, DINGTALK_WEBHOOK, payload)
    logger.info("[notify] 钉钉推送成功")


async def _push_all(text: str, title: str = "cloudsol 方案完成") -> None:
    """对启用平台逐一推送（任一失败仅记 warning，不中断其它平台）。"""
    targets = []
    if FEISHU_WEBHOOK:
        targets.append(("飞书", _notify_feishu(title, text)))
    if DINGTALK_WEBHOOK:
        targets.append(("钉钉", _notify_dingtalk(title, text)))
    for name, coro in targets:
        try:
            await coro
        except Exception as e:
            logger.warning("[notify] %s 推送失败（已忽略）: %s", name, e)


# ----------------------------------------------------------------------------
# 调度（fire-and-forget，不阻塞调用方）
# ----------------------------------------------------------------------------
def _run_coro_blocking(coro):
    try:
        asyncio.run(coro)
    except Exception as e:  # pragma: no cover - 防御性
        logger.warning("[notify] 后台线程执行异常（已忽略）: %s", e)


def safe_fire(coro):
    """把协程调度到运行中的事件循环；无循环则后台线程执行。绝不抛到调用方。"""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        threading.Thread(target=_run_coro_blocking, args=(coro,), daemon=True).start()


# ----------------------------------------------------------------------------
# 公开入口（同步，供经典/Agent 主链路直接调用）
# ----------------------------------------------------------------------------
def notify_match_complete(demand: str, industry: str = "", title: str = "", url: str = "") -> None:
    """经典 match 完成通知。demand/industry 来自 solution_matcher.match_stream。"""
    if not (FEISHU_WEBHOOK or DINGTALK_WEBHOOK):
        return
    text = _build_markdown(demand, industry, title, url or SITE_URL)
    safe_fire(_push_all(text, title="cloudsol 方案匹配完成"))


def notify_agent_result(message: str, answer: str = "", url: str = "") -> None:
    """Agent 生成成功通知。message 为用户输入需求。"""
    if not (FEISHU_WEBHOOK or DINGTALK_WEBHOOK):
        return
    # 取用户输入作为需求摘要；answer 较长不进 IM，仅提示去站点看全文
    text = _build_markdown(message, title="", url=url or SITE_URL)
    safe_fire(_push_all(text, title="cloudsol Agent 方案完成"))
