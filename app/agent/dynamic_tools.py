"""
L4-P1/T1.2 动态工具注册（pipeline DSL 组合式）

目标：让 Agent 在执行任务时能"按需制造工具"——把现有原语按流水线组合成一个
新工具（如 dyn_kb_tco：先 analyze_demand 抽关键词 → 再 search_kb 检索），
复用于本任务内的多次调用，减少 ReAct 循环步数（对应 L4 指标 A2 工具组合深度）。

安全边界（硬约束，与 L4 方案书 §WS1 一致）：
1. 只接受 pipeline DSL（组合已有工具），不接受/不执行任意代码——代码生成能力
   已由 P0 的 run_python 沙箱承担，两者不混用；
2. 可组合的原语仅限 SAFE_BASE_TOOLS 白名单：全部是本地只读检索类工具，默认
   allow 权限。凡默认 ask 的工具（run_python / read_customer_file / generate_doc）
   与 mcp__ 远端工具一律禁止组合——动态工具在 Tool.execute 层执行原语，不经过
   harness._gate_tool 闸门，若放开 ask 类工具等于绕过用户确认（安全漏洞）；
3. 工具名强制 dyn_ 前缀 + 单任务 TTL：harness.run() 每轮开始清除全部 dyn_*
   （防注册表跨任务/跨会话污染）；
4. 注册即校验：名称/描述/参数/流水线步数/别名全部白名单校验，不合法直接拒绝，
   拒绝信息回喂 LLM 引导修正。

DSL 规范（spec）：
{
  "name": "dyn_kb_search_twice",
  "description": "先做需求分析再检索知识库",
  "params": {"topic": "要检索的主题"},
  "pipeline": [
    {"tool": "analyze_demand", "args": {"raw_input": "$topic"}, "as": "demand"},
    {"tool": "search_kb", "args": {"query": "$demand.keywords"}, "as": "kb"}
  ]
}
参数取值引用语法：
- "$topic"           → 输入参数 topic
- "$kb"              → 上游别名 kb 的完整结果
- "$kb.keywords"     → 上游别名 kb 结果中的字段（结果为 JSON 时解析字段路径，取不到则原样传字符串）
"""

import re
import json
import logging
from typing import Any, Dict, Optional, Tuple

from app.agent.tools import Tool, ToolRegistry

logger = logging.getLogger(__name__)

# ── 安全白名单：仅本地只读检索原语（默认 allow，无副作用、无外发、无文件写入）──
SAFE_BASE_TOOLS = {
    "analyze_demand",
    "search_kb",
    "search_competitor",
    "list_dir",
}

_NAME_RE = re.compile(r"^dyn_[a-z][a-z0-9_]{2,39}$")
_ALIAS_RE = re.compile(r"^[a-z_][a-z0-9_]{0,30}$")
_PARAM_RE = re.compile(r"^[a-z_][a-z0-9_]{0,30}$")

MAX_PARAMS = 8
MAX_STEPS = 5
MAX_ARGS_PER_STEP = 8
STEP_RESULT_MAX_CHARS = 1500  # 每步结果回填上限（控制上下文膨胀）


def _truncate(text: str, limit: int = STEP_RESULT_MAX_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "…(已截断)"


def _dig(result: str, path: str) -> Any:
    """从上游结果中按 'a.b.c' 路径取字段；结果为 JSON 时解析字典路径，
    解析失败或字段缺失时返回 None（调用方回退为整段字符串）。"""
    cur: Any = result
    # 先尝试 JSON 解析根
    try:
        parsed = json.loads(result)
        if isinstance(parsed, (dict, list)):
            cur = parsed
    except Exception:  # noqa: BLE001
        cur = result
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
            cur = cur[int(key)]
        else:
            return None
    return cur


def _resolve_value(value: Any, params: Dict[str, Any], results: Dict[str, str]) -> Any:
    """解析单个参数值：'$xxx' 引用 → 字面量原样透传。"""
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    ref = value[1:].strip()
    if not ref:
        return value
    # 输入参数优先
    if ref in params:
        return params[ref]
    if "." in ref:
        alias, path = ref.split(".", 1)
        if alias in results:
            dug = _dig(results[alias], path)
            if dug is not None:
                return dug
            return results[alias]  # 取不到字段 → 回退整段结果
    if ref in results:
        return results[ref]
    # 引用不存在 → 空字符串（LLM 会在注册校验阶段被引导，运行期兜底）
    return ""


def validate_spec(spec: Any) -> Tuple[bool, str]:
    """校验动态工具 spec。返回 (ok, 错误信息)。错误信息面向 LLM，可直接回喂修正。"""
    if not isinstance(spec, dict):
        return False, "spec 必须是 JSON 对象（含 name/description/params/pipeline）"
    name = str(spec.get("name", "")).strip()
    if not _NAME_RE.match(name):
        return False, (
            f"工具名 '{name}' 不合法：必须以 dyn_ 开头，全小写字母/数字/下划线，"
            "总长 4-43，如 dyn_kb_deep_search"
        )
    desc = str(spec.get("description", "")).strip()
    if not (3 <= len(desc) <= 500):
        return False, "description 必须为 3-500 字符，说明这个组合工具解决什么问题"
    params = spec.get("params") or {}
    if not isinstance(params, dict) or len(params) > MAX_PARAMS:
        return False, f"params 必须是 {{参数名: 说明}} 对象，且不超过 {MAX_PARAMS} 个"
    for p in params:
        if not _PARAM_RE.match(str(p)):
            return False, f"参数名 '{p}' 不合法：小写字母/数字/下划线"
    pipeline = spec.get("pipeline")
    if not isinstance(pipeline, list) or not (1 <= len(pipeline) <= MAX_STEPS):
        return False, f"pipeline 必须是 1-{MAX_STEPS} 步的数组"
    aliases: set = set()
    for i, step in enumerate(pipeline, 1):
        if not isinstance(step, dict):
            return False, f"pipeline 第 {i} 步必须是对象 {{tool, args, as}}"
        tool = str(step.get("tool", "")).strip()
        if tool not in SAFE_BASE_TOOLS:
            return False, (
                f"第 {i} 步的工具 '{tool}' 不在可组合白名单内。"
                f"仅允许：{sorted(SAFE_BASE_TOOLS)}"
                "（ask 类工具与 mcp__ 远端工具禁止组合，防止绕过权限确认）"
            )
        args = step.get("args") or {}
        if not isinstance(args, dict) or len(args) > MAX_ARGS_PER_STEP:
            return False, f"第 {i} 步 args 必须是对象且不超过 {MAX_ARGS_PER_STEP} 个键"
        as_name = str(step.get("as", "")).strip()
        if not _ALIAS_RE.match(as_name):
            return False, f"第 {i} 步别名 'as' 不合法：小写字母开头的下划线命名"
        if as_name in aliases:
            return False, f"别名 '{as_name}' 重复，每步别名必须唯一"
        aliases.add(as_name)
    return True, ""


def register_dynamic_tool(registry: ToolRegistry, spec: Any) -> Tuple[bool, str]:
    """校验并注册一个动态组合工具。返回 (ok, msg)。

    成功后工具即刻可用（本任务内），下一轮 harness.run() 启动时自动清除（TTL）。
    """
    ok, err = validate_spec(spec)
    if not ok:
        return False, err
    name = spec["name"].strip()
    desc = str(spec["description"]).strip()
    param_docs: Dict[str, str] = {str(k): str(v)[:200] for k, v in (spec.get("params") or {}).items()}
    pipeline = spec["pipeline"]

    async def _execute(**kwargs) -> str:
        results: Dict[str, str] = {}
        steps_out = []
        try:
            for i, step in enumerate(pipeline, 1):
                tool_name = step["tool"]
                base = registry.get(tool_name)
                if base is None:  # 极端情况：注册时存在、执行时被清理
                    return json.dumps({"status": "error", "message": f"原语 '{tool_name}' 当前不可用"}, ensure_ascii=False)
                resolved = {k: _resolve_value(v, kwargs, results) for k, v in (step.get("args") or {}).items()}
                obs = await base.execute(**resolved)
                results[step["as"]] = obs
                steps_out.append({
                    "step": i, "tool": tool_name, "as": step["as"],
                    "result": _truncate(obs),
                })
            return json.dumps({
                "status": "ok",
                "tool": name,
                "steps": steps_out,
                "results": {a: _truncate(r) for a, r in results.items()},
            }, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001
            logger.warning("[dyn_tool] %s 执行异常: %s", name, e)
            return json.dumps({"status": "error", "tool": name, "message": str(e)}, ensure_ascii=False)

    registry.register(Tool(
        name=name,
        description=f"（动态组合工具）{desc}",
        parameters={
            "type": "object",
            "properties": {k: {"type": "string", "description": v} for k, v in param_docs.items()},
            "required": list(param_docs.keys()),
        },
        func=_execute,
    ))
    steps_desc = " → ".join(f"{s.get('tool')}:{s.get('as')}" for s in pipeline)
    logger.info("[dyn_tool] 已注册 %s（%s）", name, steps_desc)
    return True, f"动态工具 {name} 注册成功（{steps_desc}），本任务内可直接调用。"


def make_register_func(registry: ToolRegistry):
    """生成注册中心绑定的注册函数（供 tools.py 的元工具使用）。"""

    async def _tool_register_dynamic(name: str = "", description: str = "",
                                     params: Optional[dict] = None,
                                     pipeline: Optional[list] = None) -> str:
        spec = {
            "name": name, "description": description,
            "params": params or {}, "pipeline": pipeline or [],
        }
        ok, msg = register_dynamic_tool(registry, spec)
        return json.dumps({
            "status": "ok" if ok else "error",
            "message": msg,
            "hint": "" if ok else "请修正 spec 后重新调用 register_dynamic_tool",
        }, ensure_ascii=False)

    return _tool_register_dynamic
