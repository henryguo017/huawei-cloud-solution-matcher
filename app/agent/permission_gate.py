"""工具执行权限闸门（human-in-the-loop）。

Agent 在即将执行「高风险」工具（如生成文档、读取用户文件、联网检索）前，
通过 request_permission() 向前端发起一次 permission_request SSE 事件并阻塞等待；
前端用户点击「允许 / 拒绝」后，POST /api/agent/permission/{request_id} 调 resolve_permission()
唤醒对应 Future，Agent 据此继续或跳过。

进程内以 request_id 为键维护挂起的 Future（FastAPI 协程同事件循环，安全）。
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# request_id -> asyncio.Future[str]，str ∈ {"allow", "deny"}
_PENDING: "dict[str, asyncio.Future]" = {}
_PERMISSION_TIMEOUT = 120  # 秒：用户未响应则默认拒绝，避免 SSE 连接悬挂


def _new_future() -> asyncio.Future:
    return asyncio.get_running_loop().create_future()


async def request_permission(
    request_id: str,
    tool: str,
    tool_input: dict,
    reason: str,
    timeout: int = _PERMISSION_TIMEOUT,
) -> str:
    """阻塞等待用户决策，返回 'allow' 或 'deny'。超时 / 异常返回 'deny'。"""
    fut: asyncio.Future = _new_future()
    _PENDING[request_id] = fut
    try:
        decision = await asyncio.wait_for(asyncio.shield(fut), timeout)
        return decision if decision in ("allow", "deny") else "deny"
    except asyncio.TimeoutError:
        logger.warning("[permission] 超时未决，默认拒绝 tool=%s request_id=%s", tool, request_id)
        return "deny"
    except Exception as e:  # noqa: BLE001
        logger.warning("[permission] 等待异常（默认拒绝）: %s", e)
        return "deny"
    finally:
        _PENDING.pop(request_id, None)


def resolve_permission(request_id: str, decision: str) -> bool:
    """前端回传决策，唤醒挂起 Future。返回是否命中一个等待中的请求。"""
    fut = _PENDING.get(request_id)
    if fut is None:
        return False
    if fut.done():
        return True
    try:
        fut.set_result("allow" if decision == "allow" else "deny")
        return True
    except Exception:  # noqa: BLE001
        return False
