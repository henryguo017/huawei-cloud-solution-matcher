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

# 远端 MCP 工具名前缀：由外部 Server 提供，能力不可信，默认走 human-in-the-loop 确认
MCP_TOOL_PREFIX = "mcp__"


def resolve_tool_policy(
    tool_name: str,
    user_overrides: "dict | None" = None,
    default_policy: "dict | None" = None,
) -> "str | None":
    """解析某工具应执行的权限策略（纯函数，便于单测，不依赖重链 import）。

    优先级：用户覆盖 > 远端 MCP 工具(mcp__)默认 ask > 内置默认策略。
    返回 "allow" / "ask" / "deny" 之一；返回 None 表示无显式策略（放行）。
    """
    overrides = user_overrides or {}
    if tool_name in overrides:
        return overrides[tool_name]
    # 远端工具（mcp__<label>__<tool>）由外部 Server 提供，能力不可信，
    # 默认要求用户确认，避免越权调用或产生副作用（安全硬门槛，P0）。
    if tool_name.startswith(MCP_TOOL_PREFIX):
        return "ask"
    default_policy = default_policy or {}
    return default_policy.get(tool_name)


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
