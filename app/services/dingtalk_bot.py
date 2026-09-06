# -*- coding: utf-8 -*-
"""P2 生态交互：钉钉 Stream 模式交互机器人（独立进程，独立 systemd 服务）。

定位：群里 @机器人 发需求 → 立即回"生成中" → 后台调 API 内部端点跑 Agent
→ 完成后回卡片（临时分享页链接，匿名可读 30 天）。通知是单向广播，
本服务把钉钉从"接收通知"升级为"对话入口"。

架构要点（与拍板设计一致）：
  - Stream 模式：官方 dingtalk-stream SDK，出站长连接，免公网回调/免开端口/免验签暴露；
  - 独立进程：不进 huawei-cloud-api 主服务，挂了互相不拖累（隔离铁律）；
  - 经 127.0.0.1:8000 环回调 /api/agent/chat-internal（X-Internal-Token 鉴权），
    Agent 引擎仍单例跑在主服务进程内（MCP 客户端/长程记忆/单例状态全复用）；
  - 秒级 ack：IM 平台要求快速响应，重活丢后台线程，process() 立即返回 ACK；
  - 白名单 + 每日限次：senderStaffId 白名单（空=不限）+ 每人每日 IM_BOT_DAILY_LIMIT 次；
  - v1 单账号绑定：所有请求以 IM_BOT_USER_ID 身份执行。

运行：python -m app.services.dingtalk_bot   （项目根目录；凭证缺失则打印指引并退出 0）
"""

import os
import sys
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
logger = logging.getLogger("dingtalk_bot")

# SDK 依赖：仅本服务运行环境需要（server venv 已进 requirements.txt）；缺失时 main() 会给出指引
import dingtalk_stream
from dingtalk_stream import AckMessage

# 项目根目录（本文件位于 app/services/ 下，回退两级）+ 加载 .env（不 import app.config，零重依赖）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass

# ── 配置（与 app/config.py 同名变量保持一致；此处独立读取避免拉起 numpy/chromadb 依赖链） ──
CLIENT_ID = os.getenv("DINGTALK_BOT_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DINGTALK_BOT_CLIENT_SECRET", "")
API_BASE = os.getenv("IM_BOT_API_BASE", "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")
BOT_USER_ID = os.getenv("IM_BOT_USER_ID", "")
WHITELIST = {s.strip() for s in (os.getenv("IM_BOT_WHITELIST", "") or "").split(",") if s.strip()}
DAILY_LIMIT = int(os.getenv("IM_BOT_DAILY_LIMIT", "50"))
SITE_URL = os.getenv("SITE_URL", "https://cloudsol.cn").rstrip("/")

# 环回调用超时：Agent 单次 2-5 分钟，放宽到 15 分钟（含排队/重规划）
_API_TIMEOUT = 900


class CloudsolChatbotHandler(dingtalk_stream.ChatbotHandler):
    """钉钉机器人消息处理器（继承 SDK ChatbotHandler，register_callback_handler 要求）。"""

    def __init__(self):
        super().__init__()  # SDK ChatbotHandler.__init__(self) 无参数（0.24.0 实测签名）
        self._daily = {}  # staff_id -> (date_str, count)，进程内计数（重启清零可接受）

    # ── SDK 入口：必须快速返回 ACK，重活全部丢后台线程 ──
    async def process(self, callback_message):
        try:
            data = callback_message.data or {}
            text = ((data.get("text") or {}).get("content") or "").strip()
            staff_id = data.get("senderStaffId") or ""
            webhook = data.get("sessionWebhook") or ""
            convo = data.get("conversationId") or ""
            logger.info("[msg] staff=%s convo=%s text=%.60s", staff_id, convo, text)

            if not text or not webhook:
                return AckMessage.STATUS_OK, "empty message"

            # 防自环：@机器人 消息里常带机器人名前缀，去掉常见形态
            if text.startswith("@"):
                text = text.split(" ", 1)[-1].strip() if " " in text else text.lstrip("@").strip()

            # 防自环：@机器人 消息里常带机器人名前缀，去掉常见形态
            for prefix in ("@" + "云方案助手", "@云方案助手"):
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()

            # 白名单（配置为空 = 不限制）
            if WHITELIST and staff_id not in WHITELIST:
                self._reply(webhook, "你暂不在本机器人的可用名单内，请联系管理员添加。")
                return dingtalk_stream.AckMessage.STATUS_OK, "not in whitelist"

            # 每日限次
            if not self._allow(staff_id):
                self._reply(webhook, f"今日生成次数已达上限（{DAILY_LIMIT} 次/人/天），明天再来吧。")
                return dingtalk_stream.AckMessage.STATUS_OK, "rate limited"

            if not INTERNAL_TOKEN:
                self._reply(webhook, "机器人后端未配置内部令牌（INTERNAL_API_TOKEN），暂时无法处理请求。")
                return dingtalk_stream.AckMessage.STATUS_OK, "internal token missing"

            self._reply(webhook, "已收到需求，正在生成方案（约 2-4 分钟），完成后我会把可打开的方案链接发到群里。")
            threading.Thread(
                target=self._process_heavy, args=(text, webhook, staff_id), daemon=True
            ).start()
        except Exception as e:
            logger.exception("[msg] 处理异常（已吞掉，不影响 Stream 连接）: %s", e)
        return dingtalk_stream.AckMessage.STATUS_OK, "OK"

    # ── 限次（进程内，按自然日重置） ──
    def _allow(self, staff_id: str) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        cnt_day, cnt = self._daily.get(staff_id, ("", 0))
        if cnt_day != today:
            cnt_day, cnt = today, 0
        if cnt >= DAILY_LIMIT:
            self._daily[staff_id] = (cnt_day, cnt)
            return False
        self._daily[staff_id] = (cnt_day, cnt + 1)
        return True

    # ── 重活：环回调内部端点跑 Agent → 回卡片 ──
    def _process_heavy(self, text: str, webhook: str, staff_id: str):
        try:
            payload = json.dumps({
                "message": text,
                "session_id": f"imbot_dingtalk_{staff_id}_{int(time.time())}",
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
            self._reply(webhook, f"生成失败（服务返回 {e.code}）：{detail or '请稍后重试'}")
            return
        except Exception as e:
            logger.exception("[heavy] 调用失败: %s", e)
            self._reply(webhook, "生成失败：后端服务暂不可用，请稍后重试。")
            return

        if not result.get("success"):
            self._reply(webhook, "这次没能生成有效方案，请换个更具体的需求描述再试（行业+场景+规模）。")
            return

        answer = result.get("answer", "") or ""
        share_id = result.get("share_id")
        link = f"{SITE_URL}/share.html?id={share_id}" if share_id else SITE_URL
        # 群卡片只放导读（前 400 字）+ 链接，全文走分享页
        digest = answer[:400].strip() + ("…" if len(answer) > 400 else "")
        md = (
            f"### ✅ 方案已生成\n\n"
            f"**需求**：{text[:80]}\n\n"
            f"{digest}\n\n"
            f"[👉 点此查看完整方案]({link})\n\n"
            f"（链接为临时分享页，匿名可读、30 天有效；耗时 {result.get('elapsed') or '-'} 秒）"
        )
        self._reply_markdown(webhook, "cloudsol 方案已生成", md)

    # ── 回复：sessionWebhook 单向推送（无需额外 API 权限） ──
    def _reply(self, webhook: str, text: str):
        self._reply_markdown(webhook, "cloudsol 机器人", text)

    def _reply_markdown(self, webhook: str, title: str, text: str):
        try:
            body = json.dumps({
                "msgtype": "markdown",
                "markdown": {"title": title, "text": text},
            }).encode("utf-8")
            req = urllib.request.Request(
                webhook, data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as e:
            logger.warning("[reply] webhook 回复失败（已忽略）: %s", e)


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        logger.error(
            "钉钉机器人凭证未配置（DINGTALK_BOT_CLIENT_ID / DINGTALK_BOT_CLIENT_SECRET 为空）。\n"
            "配置步骤见 docs/dingtalk-bot-setup.md；不使用机器人时可停用本服务："
            "systemctl disable --now cloudsol-im-bot"
        )
        return 0  # 干净退出：systemd 不重启，主 API 不受影响
    if not INTERNAL_TOKEN:
        logger.error("INTERNAL_API_TOKEN 未配置：机器人无法调用后端，退出（配置后 systemctl restart cloudsol-im-bot）")
        return 0

    credential = dingtalk_stream.Credential(CLIENT_ID, CLIENT_SECRET)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC, CloudsolChatbotHandler()
    )
    logger.info("[boot] 钉钉 Stream 机器人启动（白名单=%s 限次=%s/天 API=%s）",
                "开启" if WHITELIST else "未配置(不限)", DAILY_LIMIT, API_BASE)
    client.start_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
