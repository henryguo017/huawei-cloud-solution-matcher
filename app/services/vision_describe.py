"""图片视觉理解预处理（2026-09-09）。

spike 结论（2026-09-08 实测）：
  - deepseek-v4-flash / deepseek-v4-pro 不支持图片输入：flash 静默丢弃（谎称无图），
    pro 直接幻觉编造图片内容——绝不能带图直调。
  - deepseek-v4-flash-vision-exp 正常识别截图（prompt_tokens 含图片计费）。

因此采用"视觉预处理"方案：带图请求先用 vision-exp 把图片转成结构化文字描述，
再把描述注入 Agent 消息——工具循环 / RAG / 记忆链路全部保持原 flash 架构零改动。
"""
import base64
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_VISION_MODEL = os.getenv("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp")
_DESCRIBE_INSTRUCTION = (
    "请详尽描述这张图（或多张图）的全部内容：所有文字、数字、表格结构、架构关系、"
    "标注与痛点信息。不要遗漏任何文字，不要添加图中不存在的内容。"
    "直接输出图片内容描述本身，不要评价或建议。"
)


def describe_images(data_urls, timeout_seconds=90):
    """把 1-4 张图片（data URL）交给 vision 模型提取完整文字内容。

    返回描述文本；失败抛异常（调用方决定是否降级）。
    """
    if not data_urls:
        raise ValueError("data_urls 为空")
    api_key = (os.getenv("DEEPSEEK_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")
    base_url = (os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1") or "").rstrip("/")

    content = [{"type": "text", "text": _DESCRIBE_INSTRUCTION}]
    for url in data_urls[:4]:
        content.append({"type": "image_url", "image_url": {"url": url}})

    body = {
        "model": _VISION_MODEL,
        "max_tokens": 1500,
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": content}],
    }
    req = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        data = json.loads(resp.read())
    usage = data.get("usage", {})
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    logger.info(
        "[Vision] 图片描述完成: images=%s prompt_tokens=%s completion_tokens=%s",
        len(data_urls), usage.get("prompt_tokens"), usage.get("completion_tokens"),
    )
    if not (text or "").strip():
        raise RuntimeError("vision 模型返回空描述")
    return text.strip()
