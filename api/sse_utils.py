"""
SSE 序列化工具（api/sse_utils.py）
=====================================================
2026-08-26 路由收拢：经典模式（routes.py）与 Agent 模式（agent_routes.py）
共用同一个 SSE JSON 序列化函数，抽到此共享模块避免两处复制。
"""
from datetime import datetime, date


def sse_json_default(obj):
    """SSE 事件 JSON 序列化兜底：优先 pydantic model_dump/dict，其次日期/集合/字节串。"""
    for attr in ("model_dump", "dict"):
        if hasattr(obj, attr):
            try:
                return getattr(obj, attr)()
            except Exception:
                pass
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", "replace")
    return str(obj)
