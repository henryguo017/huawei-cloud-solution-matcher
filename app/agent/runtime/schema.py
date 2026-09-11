# -*- coding: utf-8 -*-
"""L4-P2 Agent Runtime · 工具接口层（schema.py）

职责（单一）：把宿主的能力注册表**翻译成模型可读的结构化接口**，并把模型的
结构化输出**翻译成合法的对话消息**。本模块不含任何任务决策、不发起 LLM 调用。

设计要点：
  - Tool.parameters 本就是 JSON Schema 形状 → 包一层 function 即完成 schema 化，
    零改造现有 10 个内置工具 / dyn_* / mcp__*。
  - arguments 始终以**字符串**形态在传输层流转，解析失败不抛异常，
    而是产出结构化错误 observation 回填给模型（C3：失败恢复归模型）。
  - 只读工具集用于并行分流；高风险工具一律串行，逐个走权限闸门。
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 单条 observation 回填上限（字符）：防一次检索撑爆上下文窗口
OBSERVATION_MAX_CHARS = 6000

# ── 只读工具集：可与同轮其它只读调用并发执行 ──
# 判定原则：无副作用、无外发写、无用户确认需求。
# 注意 register_dynamic_tool 不在其中 —— 它会改注册表，必须串行。
READONLY_TOOL_NAMES = {
    "analyze_demand",
    "search_kb",
    "search_competitor",
    "list_dir",
    "web_search",
    "web_extract",
    "mcp__crm__client_list",
    "mcp__crm__match_history",
    "mcp__cost__cost_reference_list",
    "mcp__cost__cost_calc",
}
# 注意：read_customer_file 属只读但**默认 ask 权限**（每次需用户确认），
# 放进并行集会导致多个确认弹窗同时挂起；故此处排除，让它走串行等用户决策。


def is_readonly(tool_name: str) -> bool:
    """该工具是否属于只读集（可并发）。dyn_* 由白名单只读原语组合而成，天然只读。"""
    if not tool_name:
        return False
    if tool_name.startswith("dyn_"):
        return True
    return tool_name in READONLY_TOOL_NAMES


def to_function_schema(tool) -> Optional[Dict[str, Any]]:
    """Tool → OpenAI function schema。字段缺失/形状异常时返回 None（调用方跳过该工具）。"""
    try:
        name = getattr(tool, "name", "") or ""
        if not name:
            return None
        params = getattr(tool, "parameters", None)
        if not isinstance(params, dict) or not params:
            # 无参数工具也必须给合法 schema（部分实现拒绝缺 parameters 的定义）
            params = {"type": "object", "properties": {}}
        else:
            params = dict(params)
            params.setdefault("type", "object")
            params.setdefault("properties", {})
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": getattr(tool, "description", "") or name,
                "parameters": params,
            },
        }
    except Exception as e:  # noqa: BLE001 - schema 构造失败不应阻断整个运行
        logger.warning("[runtime.schema] 工具 schema 构造失败（跳过）: %s", e)
        return None


def build_tool_schemas(registry, extra: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """把整个注册表翻译为 function schema 列表（+ 运行时自带工具，如 update_plan）。

    **不按步切分工具集** —— 这正是 C1（控制流在模型）的直接落地：
    模型看到全部能力，自己决定用哪个、用几次。
    """
    schemas: List[Dict[str, Any]] = []
    names = set()
    try:
        tools = registry.list_tools()
    except Exception as e:  # noqa: BLE001
        logger.warning("[runtime.schema] 枚举工具失败: %s", e)
        tools = []
    for t in tools:
        s = to_function_schema(t)
        if not s:
            continue
        nm = s["function"]["name"]
        if nm in names:      # dyn_ 同名覆盖等极端情况去重
            continue
        names.add(nm)
        schemas.append(s)
    for s in (extra or []):
        if isinstance(s, dict) and s.get("function", {}).get("name") not in names:
            names.add(s["function"]["name"])
            schemas.append(s)
    return schemas


def parse_tool_arguments(raw: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """解析 tool_calls[].function.arguments。

    返回 (args, err)：args 为 dict 表示成功；err 为面向模型的中文错误说明。
    arguments 为空串/None → 视为无参数调用（{}）。
    """
    if raw is None or raw == "":
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    if not isinstance(raw, str):
        return None, f"参数格式不受支持（期望 JSON 字符串，实际 {type(raw).__name__}）"
    text = raw.strip()
    if not text:
        return {}, None
    try:
        val = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"参数不是合法 JSON（{e.msg}，位置 {e.pos}）。请修正后重新调用，例如 {{\"query\": \"关键词\"}}"
    if not isinstance(val, dict):
        return None, f"参数必须是 JSON 对象，实际是 {type(val).__name__}"
    return val, None


def to_assistant_message(content: str, tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构造 assistant 消息（含 tool_calls）。content 统一为字符串，避免部分实现要求非 null。"""
    return {
        "role": "assistant",
        "content": content or "",
        "tool_calls": [
            {
                "id": tc.get("id"),
                "type": "function",
                "function": {
                    "name": (tc.get("function") or {}).get("name", ""),
                    "arguments": (tc.get("function") or {}).get("arguments", "{}"),
                },
            }
            for tc in (tool_calls or [])
        ],
    }


def to_tool_message(call_id: str, observation: str, max_chars: int = OBSERVATION_MAX_CHARS) -> Dict[str, Any]:
    """构造 tool 消息（回填 observation）。超长截断并显式标注，模型据此可知信息不完整。"""
    obs = observation if isinstance(observation, str) else json.dumps(observation, ensure_ascii=False, default=str)
    if len(obs) > max_chars:
        obs = obs[:max_chars] + f"\n…（结果过长已截断，保留前 {max_chars} 字；如需其余部分请缩小检索范围或换关键词重试）"
    return {"role": "tool", "tool_call_id": call_id or "", "content": obs}


def sanitize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """发送前兜底：保证每条消息具备协议必需字段（防止 400 不重试的请求侧错误）。"""
    out = []
    for m in (messages or []):
        if not isinstance(m, dict):
            continue
        role = m.get("role") or ""
        if role == "assistant":
            m2 = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                m2["tool_calls"] = m["tool_calls"]
            out.append(m2)
        elif role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id") or "",
                "content": m.get("content") if isinstance(m.get("content"), str) else str(m.get("content") or ""),
            })
        elif role in ("system", "user"):
            out.append({"role": role, "content": m.get("content") if isinstance(m.get("content"), str) else str(m.get("content") or "")})
        else:
            # 未知角色丢弃，不把非法结构送到 API
            logger.warning("[runtime.schema] 丢弃未知角色消息: %r", role)
    return out
