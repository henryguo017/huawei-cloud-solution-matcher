# -*- coding: utf-8 -*-
"""P2 生态交互：飞书长连接交互机器人（独立进程，与钉钉 bot 同构）。

背景：用户钉钉账号被学校组织管控（无法建应用/团队），飞书个人可自建团队
+开发者后台自助建应用，故飞书先行。结构照抄 dingtalk_bot.py：
  长连接收事件（免公网回调）→ 秒级 ack 回「已收到」→ 后台线程环调内部端点
  跑 Agent → 回富文本卡片（400 字导读 + 临时分享页链接）。

与钉钉的差异（都是飞书平台特性，不是设计分歧）：
  - 鉴权：App ID + App Secret（SDK 自动管 tenant_access_token），无 webhook 加签环节；
  - 回复：走 im/v1/messages API（chat_id 定位），不是 sessionWebhook；
  - 事件：im.message.receive_v1（群内 @机器人 触发）；
  - 白名单键：sender open_id（IM_BOT_WHITELIST 同一 env，值按平台各自填）。

运行：python -m app.services.feishu_bot   （凭证缺失打印指引干净退出 0）
"""

import os
import sys
import re
import json
import time
import logging
import threading
import urllib.request
import urllib.error
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("feishu_bot")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass

# 配置与钉钉 bot 同名同源（.env 一处配置，两个 bot 各自取用）
APP_ID = os.getenv("FEISHU_BOT_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_BOT_APP_SECRET", "")
API_BASE = os.getenv("IM_BOT_API_BASE", "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")
BOT_USER_ID = os.getenv("IM_BOT_USER_ID", "")
WHITELIST = {s.strip() for s in (os.getenv("IM_BOT_WHITELIST", "") or "").split(",") if s.strip()}
DAILY_LIMIT = int(os.getenv("IM_BOT_DAILY_LIMIT", "5"))
SITE_URL = os.getenv("SITE_URL", "https://cloudsol.cn").rstrip("/")

_API_TIMEOUT = 900

# 摘要清洗：飞书 post 富文本不渲染 Markdown，**、##、|---| 会原样露出（AI 味重），
# 发送前剥成干净纯文本。顺序敏感：表格分隔行要在竖线转全角之前删。
_MD_RULES = [
    (re.compile(r"^#{1,6}\s*", re.M), ""),               # 标题井号
    (re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}"), r"\1"),    # 粗体/斜体包裹（保留内文）
    (re.compile(r"__(.+?)__"), r"\1"),                   # 下划线粗体
    (re.compile(r"`{1,3}[^`\n]*`{1,3}"), ""),            # 行内代码/代码块标记
    (re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$", re.M), ""),  # 表格分隔行 |---|---|
    (re.compile(r"^\s*>\s?", re.M), ""),                 # 引用符
    (re.compile(r"^\s*[-*+]\s+", re.M), "· "),           # 无序列表符号
    (re.compile(r"\n{3,}"), "\n\n"),                     # 压缩连续空行
]


def _clean_digest(md: str, limit: int = 400) -> str:
    """把 Agent 终稿（Markdown）压成飞书 post 可读的纯文本摘要。

    超长时优先回退到行边界截断（避免切在表格行/半句话中间），加省略号。
    """
    text = (md or "").replace("\r\n", "\n")
    for pat, rep in _MD_RULES:
        text = pat.sub(rep, text)
    text = text.replace("|", "｜")                        # 残留表格列分隔转全角
    text = re.sub(r"^[ \t]*｜", "", text, flags=re.M)     # 去行首/行尾残留竖线
    text = re.sub(r"｜[ \t]*$", "", text, flags=re.M)
    text = re.sub(r"^[ \t]+", "", text, flags=re.M)       # 去行首残留空白（表格行首空格等）
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = text.strip()
    if len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        text = text[: cut if cut >= 120 else limit].rstrip() + "…"
    return text

# SDK 依赖：仅本服务运行环境需要；缺失时 main() 给指引
import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest, CreateMessageRequestBody,
    P2ImMessageReceiveV1,
)


class CloudsolFeishuHandler:
    """飞书 im.message.receive_v1 事件处理（白名单/限次/ack/重活与钉钉版同逻辑）。"""

    def __init__(self, client: lark.Client):
        self.client = client
        self._daily = {}  # open_id -> (date_str, count)

    # ── SDK 回调入口：快速返回，重活丢后台线程 ──
    def _on_receive(self, data: P2ImMessageReceiveV1) -> None:
        try:
            msg = data.event.message
            chat_id = msg.chat_id or ""
            chat_type = getattr(msg, "chat_type", "") or ""
            open_id = (data.event.sender.sender_id.open_id if data.event.sender else "") or ""
            try:
                raw_text = json.loads(msg.content or "{}").get("text", "")
            except Exception:
                raw_text = ""
            text = (raw_text or "").strip()
            # 群内 @机器人：文本前缀是 @名字，剥掉第一个 @token
            if text.startswith("@"):
                text = text.split(" ", 1)[-1].strip() if " " in text else text.lstrip("@").strip()
            logger.info("[msg] open_id=%s chat=%s(%s) text=%.60s", open_id, chat_id, chat_type, text)

            if not text or not chat_id:
                return

            if WHITELIST and open_id not in WHITELIST:
                self._send_text(chat_id, "你暂不在本机器人的可用名单内，请联系管理员添加。")
                return
            if not self._allow(open_id):
                self._send_text(chat_id, f"今日生成次数已达上限（{DAILY_LIMIT} 次/人/天），明天再来吧。")
                return
            if not INTERNAL_TOKEN:
                self._send_text(chat_id, "机器人后端未配置内部令牌（INTERNAL_API_TOKEN），暂时无法处理请求。")
                return

            self._send_text(chat_id, "已收到需求，正在生成方案（约 2-4 分钟），完成后我会把可打开的方案链接发到群里。")
            threading.Thread(target=self._process_heavy, args=(text, chat_id, open_id), daemon=True).start()
        except Exception as e:
            logger.exception("[msg] 处理异常（已吞掉，不影响长连接）: %s", e)

    def _allow(self, open_id: str) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        d, cnt = self._daily.get(open_id, ("", 0))
        if d != today:
            d, cnt = today, 0
        if cnt >= DAILY_LIMIT:
            self._daily[open_id] = (d, cnt)
            return False
        self._daily[open_id] = (d, cnt + 1)
        return True

    def _process_heavy(self, text: str, chat_id: str, open_id: str):
        try:
            payload = json.dumps({
                "message": text,
                "session_id": f"imbot_feishu_{open_id}_{int(time.time())}",
            }).encode("utf-8")
            req = urllib.request.Request(
                API_BASE + "/api/agent/chat-internal",
                data=payload,
                headers={"Content-Type": "application/json", "X-Internal-Token": INTERNAL_TOKEN},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=_API_TIMEOUT) as resp:
                result = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode("utf-8", "replace")).get("detail", "")
            except Exception:
                pass
            logger.warning("[heavy] API 返回 %s: %s", e.code, detail)
            self._send_text(chat_id, f"生成失败（服务返回 {e.code}）：{detail or '请稍后重试'}")
            return
        except Exception as e:
            logger.exception("[heavy] 调用失败: %s", e)
            self._send_text(chat_id, "生成失败：后端服务暂不可用，请稍后重试。")
            return

        if not result.get("success"):
            self._send_text(chat_id, "这次没能生成有效方案，请换个更具体的需求描述再试（行业+场景+规模）。")
            return

        answer = result.get("answer", "") or ""
        share_id = result.get("share_id")
        link = f"{SITE_URL}/share.html?id={share_id}" if share_id else SITE_URL
        digest = _clean_digest(answer)
        # 富文本 post：标题 + 导读段落 + 蓝色链接
        content = {
            "post": {
                "zh_cn": {
                    "title": "✅ 方案已生成",
                    "content": [
                        [{"tag": "text", "text": f"需求：{text[:80]}\n"}],
                        [{"tag": "text", "text": f"{digest}\n"}],
                        [{"tag": "a", "text": "👉 点此查看完整方案", "href": link}],
                        [{"tag": "text", "text": f"\n（临时分享页，匿名可读、30 天有效；耗时 {result.get('elapsed') or '-'} 秒）"}],
                    ],
                }
            }
        }
        self._send(chat_id, "post", json.dumps(content, ensure_ascii=False))

    # ── 发送：优先 reply 到原消息线程；失败降级为按 chat_id 直接发 ──
    def _send_text(self, chat_id: str, text: str):
        self._send(chat_id, "text", json.dumps({"text": text}, ensure_ascii=False))

    def _send(self, chat_id: str, msg_type: str, content_json: str):
        try:
            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(CreateMessageRequestBody.builder()
                              .receive_id(chat_id)
                              .msg_type(msg_type)
                              .content(content_json)
                              .build()) \
                .build()
            response = self.client.im.v1.message.create(request)
            if not response.success():
                logger.warning("[send] 飞书拒绝: code=%s msg=%s", response.code, response.msg)
        except Exception as e:
            logger.warning("[send] 发送失败（已忽略）: %s", e)


def main():
    if not APP_ID or not APP_SECRET:
        logger.error(
            "飞书机器人凭证未配置（FEISHU_BOT_APP_ID / FEISHU_BOT_APP_SECRET 为空）。\n"
            "配置步骤见 docs/feishu-bot-setup.md；不使用时可停用：systemctl disable --now cloudsol-im-feishu"
        )
        return 0
    if not INTERNAL_TOKEN:
        logger.error("INTERNAL_API_TOKEN 未配置：机器人无法调用后端，退出（配置后 systemctl restart cloudsol-im-feishu）")
        return 0

    client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()
    handler = CloudsolFeishuHandler(client)

    event_handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(handler._on_receive) \
        .build()

    import lark_oapi.ws as ws
    # ⚠️ log_level 必须传 SDK 枚举 lark_oapi.core.enum.LogLevel（内部取 .value），
    # 传标准 logging 的 int 会 AttributeError 崩溃。默认值即 LogLevel.INFO，直接省略最稳。
    ws_client = ws.Client(APP_ID, APP_SECRET,
                          event_handler=event_handler)
    logger.info("[boot] 飞书长连接机器人启动（白名单=%s 限次=%s/天 API=%s）",
                "开启" if WHITELIST else "未配置(不限)", DAILY_LIMIT, API_BASE)
    ws_client.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
