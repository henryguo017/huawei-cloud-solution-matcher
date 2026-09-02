# -*- coding: utf-8 -*-
"""P1 飞书 / 钉钉群机器人通知适配器（纯标准库，零新依赖）。

设计要点（与项目铁律对齐）：
  - 零新依赖：仅用标准库 urllib / hmac / hashlib / base64 / asyncio，不引入 requests 等第三方包；
  - 多用户绑定：每个账号可在前端绑定自己的飞书/钉钉（user_notify_bindings 表）；
    触发时按当前 user_id 查该用户绑定，分别推到他自己的群；
  - 全局兜底：服务器 .env 的 FEISHU_/DINGTALK_WEBHOOK 作为运营级兜底，
    仅在该用户未个人绑定对应平台时补发，避免运营者自己重复收到；
  - 默认关：某用户两个平台都未绑定、且全局 webhook 也为空 → 整体零副作用；
  - 失败吞掉：任何网络/签名异常只记 warning，绝不向上抛，不拖垮主链路（稳定性铁律）；
  - fire-and-forget：notify_for_user / notify_match_complete / notify_agent_result 为同步入口，
    内部用 safe_fire 调度到事件循环（或后台线程），不阻塞调用方；
  - 签名：飞书/钉钉同公式 HMAC-SHA256(timestamp + "\\n" + secret) → base64；
  - secret 明文存 DB，但所有查询/列表接口均不回传原文（仅返启用态 + 脱敏 webhook）。

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
import sqlite3
import urllib.request
import urllib.error
import urllib.parse

logger = logging.getLogger(__name__)

# 站点入口（通知里点击进 cloudsol 看全文）
SITE_URL = os.getenv("SITE_URL", "https://cloudsol.cn")

# 全局兜底（运营级，来自环境变量；单一事实来源=环境变量）
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


def _mask_webhook(webhook: str) -> str:
    """脱敏：保留前缀与末尾 token，中间打码，绝不回传完整地址。"""
    if not webhook:
        return ""
    if len(webhook) <= 16:
        return "****"
    return webhook[:12] + "****" + webhook[-4:]


# ----------------------------------------------------------------------------
# DB 访问（用户级绑定）
# ----------------------------------------------------------------------------
def _db_conn():
    from app.utils.db_init import get_db_connection
    return get_db_connection()


def get_user_bindings(user_id) -> list:
    """返回该用户已启用的绑定列表：[{platform, webhook, secret}, ...]。"""
    if not user_id:
        return []
    try:
        conn = _db_conn()
        rows = conn.execute(
            "SELECT platform, webhook, secret FROM user_notify_bindings "
            "WHERE user_id=? AND enabled=1",
            (user_id,),
        ).fetchall()
        return [
            {"platform": r["platform"], "webhook": r["webhook"], "secret": r["secret"]}
            for r in rows
        ]
    except Exception as e:  # pragma: no cover - 防御性
        logger.warning("[notify] 读取用户绑定失败（跳过）: %s", e)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_user_bindings(user_id) -> list:
    """列表（脱敏，供前端设置页）：[{platform, enabled, webhook_masked}, ...]。"""
    if not user_id:
        return []
    try:
        conn = _db_conn()
        rows = conn.execute(
            "SELECT platform, webhook, enabled FROM user_notify_bindings WHERE user_id=?",
            (user_id,),
        ).fetchall()
        return [
            {
                "platform": r["platform"],
                "enabled": bool(r["enabled"]),
                "webhook_masked": _mask_webhook(r["webhook"]),
            }
            for r in rows
        ]
    except Exception as e:  # pragma: no cover
        logger.warning("[notify] 列出用户绑定失败: %s", e)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def save_user_binding(user_id, platform: str, webhook: str, secret: str, enabled: int = 1) -> None:
    """绑定 / 更新（幂等 upsert）。platform ∈ {feishu, dingtalk}。"""
    if not user_id or platform not in ("feishu", "dingtalk") or not webhook:
        raise ValueError("invalid binding params")
    conn = _db_conn()
    try:
        conn.execute(
            "INSERT INTO user_notify_bindings (user_id, platform, webhook, secret, enabled, updated_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now','localtime')) "
            "ON CONFLICT(user_id, platform) DO UPDATE SET "
            "webhook=excluded.webhook, secret=excluded.secret, "
            "enabled=excluded.enabled, updated_at=datetime('now','localtime')",
            (user_id, platform, webhook, secret or "", enabled),
        )
        conn.commit()
    finally:
        conn.close()


def delete_user_binding(user_id, platform: str) -> None:
    """解绑（删除该平台绑定）。"""
    if not user_id or platform not in ("feishu", "dingtalk"):
        return
    conn = _db_conn()
    try:
        conn.execute(
            "DELETE FROM user_notify_bindings WHERE user_id=? AND platform=?",
            (user_id, platform),
        )
        conn.commit()
    finally:
        conn.close()


def set_user_binding_enabled(user_id, platform: str, enabled: int) -> None:
    """切换启用状态。"""
    if not user_id or platform not in ("feishu", "dingtalk"):
        return
    conn = _db_conn()
    try:
        conn.execute(
            "UPDATE user_notify_bindings SET enabled=?, updated_at=datetime('now','localtime') "
            "WHERE user_id=? AND platform=?",
            (1 if enabled else 0, user_id, platform),
        )
        conn.commit()
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# 平台推送（异步，内部用 to_thread 不阻塞事件循环）
# ----------------------------------------------------------------------------
def _build_request(platform: str, webhook: str, secret: str, title: str, text: str):
    """构造飞书/钉钉推送请求，返回 (最终 url, body)。

    关键平台差异（这是 310000 签名错误的根因）：
      - 飞书 interactive card：timestamp/sign 放在 JSON body；
      - 钉钉自定义机器人：timestamp/sign 必须拼到 URL 查询串，且 sign 需 urlencode。
        钉钉服务端只认 URL 上的签名，body 里的会被无视 → 一直报 310000。
    """
    ts, sign = _sign(secret)
    if platform == "feishu":
        body = {
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
        return webhook, body
    # dingtalk：签名拼到 URL 查询串（secret 为空表示未开加签，直接原样 URL）
    if secret:
        sep = "&" if "?" in webhook else "?"
        url = webhook + sep + "timestamp=" + ts + "&sign=" + urllib.parse.quote_plus(sign)
    else:
        url = webhook
    body = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }
    return url, body


async def _notify_feishu(webhook: str, secret: str, title: str, text: str) -> None:
    url, payload = _build_request("feishu", webhook, secret, title, text)
    resp_text = await asyncio.to_thread(_post_json, url, payload)
    try:
        resp = json.loads(resp_text)
        if resp.get("code") not in (None, 0):
            logger.warning("[notify] 飞书拒绝: code=%s, msg=%s", resp.get("code"), resp.get("msg", ""))
            return
    except Exception:
        pass
    logger.info("[notify] 飞书推送成功")


async def _notify_dingtalk(webhook: str, secret: str, title: str, text: str) -> None:
    url, payload = _build_request("dingtalk", webhook, secret, title, text)
    resp_text = await asyncio.to_thread(_post_json, url, payload)
    try:
        resp = json.loads(resp_text)
        if resp.get("errcode") not in (None, 0):
            logger.warning("[notify] 钉钉拒绝: errcode=%s, errmsg=%s", resp.get("errcode"), resp.get("errmsg", ""))
            return
    except Exception:
        pass
    logger.info("[notify] 钉钉推送成功")


async def _push_targets(targets: list, title: str, text: str) -> None:
    """对一组目标（{platform, webhook, secret}）逐一推送，任一失败仅记 warning。"""
    for t in targets:
        platform = t.get("platform")
        webhook = t.get("webhook")
        secret = t.get("secret", "")
        if not webhook:
            continue
        try:
            if platform == "feishu":
                await _notify_feishu(webhook, secret, title, text)
            elif platform == "dingtalk":
                await _notify_dingtalk(webhook, secret, title, text)
        except Exception as e:
            logger.warning("[notify] %s 推送失败（已忽略）: %s", platform, e)


def _global_targets() -> list:
    """运营级全局兜底目标（来自 .env）。"""
    t = []
    if FEISHU_WEBHOOK:
        t.append({"platform": "feishu", "webhook": FEISHU_WEBHOOK, "secret": FEISHU_SECRET})
    if DINGTALK_WEBHOOK:
        t.append({"platform": "dingtalk", "webhook": DINGTALK_WEBHOOK, "secret": DINGTALK_SECRET})
    return t


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
# 公开入口
# ----------------------------------------------------------------------------
def notify_for_user(user_id, demand: str = "", industry: str = "", title: str = "",
                    share_payload: dict = None, url: str = "") -> None:
    """按用户推送：个人绑定优先；该用户未绑定的平台才补全局兜底（避免运营者重复收）。

    链接策略（用户决策）：传了 share_payload 就生成「临时分享页」链接
    （/share.html?id=...，匿名可读、不暴露账号），点开即看方案全文；
    否则用 url 或站点首页兜底。这样钉钉/飞书卡片点开是一个可临时打开的
    只读页面，而非登录墙后的工作台首页。
    """
    if user_id:
        personal = get_user_bindings(user_id)
        personal_platforms = {b["platform"] for b in personal}
        targets = list(personal)
        for g in _global_targets():
            if g["platform"] not in personal_platforms:
                targets.append(g)
    else:
        targets = _global_targets()
    if not targets:
        return
    link = url or SITE_URL
    if share_payload:
        try:
            from app.services.share_service import ShareService
            sid = ShareService().create_share(
                title or (demand or "cloudsol 方案")[:60], share_payload
            )
            if sid:
                link = SITE_URL + "/share.html?id=" + sid
        except Exception as e:
            logger.warning("[notify] 生成分享链接失败，回退站点首页: %s", e)
    text = _build_markdown(demand, industry, title, link)
    safe_fire(_push_targets(targets, "cloudsol 方案完成", text))


def notify_match_complete(demand: str, industry: str = "", title: str = "", url: str = "") -> None:
    """向后兼容：仅全局兜底（无 user_id 上下文时）。"""
    targets = _global_targets()
    if not targets:
        return
    text = _build_markdown(demand, industry, title, url or SITE_URL)
    safe_fire(_push_targets(targets, "cloudsol 方案匹配完成", text))


def notify_agent_result(message: str, answer: str = "", url: str = "") -> None:
    """向后兼容：仅全局兜底（无 user_id 上下文时）。"""
    targets = _global_targets()
    if not targets:
        return
    text = _build_markdown(message, title="", url=url or SITE_URL)
    safe_fire(_push_targets(targets, "cloudsol Agent 方案完成", text))


def test_user_binding(user_id, platform: str):
    """向该用户指定平台绑定发一条测试消息并返回 (ok, error)。

    同步发送（非 fire-and-forget），便于前端测试按钮即时反馈成败。
    """
    if platform not in ("feishu", "dingtalk") or not user_id:
        return False, "参数非法"
    try:
        conn = _db_conn()
        row = conn.execute(
            "SELECT webhook, secret FROM user_notify_bindings WHERE user_id=? AND platform=? AND enabled=1",
            (user_id, platform),
        ).fetchone()
    except Exception as e:
        logger.warning("[notify] 测试读取绑定失败: %s", e)
        return False, "读取绑定失败"
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not row or not row["webhook"]:
        return False, "该平台未绑定或未启用"
    try:
        url, payload = _build_request(platform, row["webhook"], row["secret"], "cloudsol 通知测试",
                                      _build_markdown("这是一条测试消息", url=SITE_URL))
        resp_text = _post_json(url, payload)
        # 解析平台返回，检查业务错误码（钉钉 errcode / 飞书 code），
        # 否则 HTTP 200 + errcode!=0 会被误判为成功。
        try:
            resp = json.loads(resp_text)
        except Exception:
            return True, ""
        if platform == "dingtalk":
            err = resp.get("errcode")
            if err not in (None, 0):
                return False, "钉钉拒绝: errcode=%s, errmsg=%s" % (err, resp.get("errmsg", ""))
        elif platform == "feishu":
            code = resp.get("code")
            if code not in (None, 0):
                return False, "飞书拒绝: code=%s, msg=%s" % (code, resp.get("msg", ""))
        return True, ""
    except Exception as e:
        logger.warning("[notify] 测试推送失败: %s", e)
        return False, str(e)
