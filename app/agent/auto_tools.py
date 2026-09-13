# -*- coding: utf-8 -*-
"""L4-P3-1 自建工具（auto_tools）：模型用 Python 定义**新能力**（不只是组合原语）。

与 dynamic_tools（P1/T1.2）的分工：
  register_dynamic_tool : 组合**已有**白名单原语为流水线（DSL，无代码）；
  create_tool（本模块） : 模型写**受限 Python 函数体**造新工具（如 TCO 试算、单位换算）。

安全模型（铁律：**进程内永不执行模型代码**）：
1. 函数体约束：必须定义顶层 ``def run(params: dict)``，返回可 JSON 序列化对象；
2. AST 静态检查：复用 sandbox.precheck（import 白名单 / 黑名单内建 / dunder 全禁），
   注入攻击面与 run_python 沙箱完全同级；
3. 执行 = 子进程沙箱：注册时试跑验证 + 之后每次调用都在 ``python -I`` 子进程里跑
   （rlimit 五重限制：CPU/内存/禁写文件/防 fork/禁外联），复用 run_python 全部机制；
4. 单任务 TTL + 用户级持久化：dyn_ 前缀随任务清除；持久化到
   ``data/user_tools/<user_id>.json``，后续任务启动时**重新过静态检查**再加载
   （防持久化文件被篡改后绕过检查）；
5. 总开关 ``AGENT_AUTO_TOOLS``（默认 0=关）：回退 = 置 0 重启。
"""
import ast
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.agent.tools import Tool, ToolRegistry
from app.agent import sandbox

logger = logging.getLogger(__name__)

# 目录：用户级自建工具持久化（data/user_tools/<user_id>.json）
USER_TOOLS_DIR = Path("data") / "user_tools"

_NAME_RE = re.compile(r"^dyn_[a-z][a-z0-9_]{2,39}$")
_PARAM_RE = re.compile(r"^[a-z_][a-z0-9_]{0,30}$")
MAX_PARAMS = 8
MAX_BODY_CHARS = 6000          # 沙箱上限 8000，留 wrapper 余量
MAX_USER_TOOLS = 20            # 单用户自建工具数上限（防持久化膨胀）

WRAPPER_TEMPLATE = (
    "import json as _json\n"
    "_ARGS = _json.loads({json_str!r})\n"
    "{body}\n"
    "_RESULT = run(_ARGS)\n"
    "print(_json.dumps(_RESULT, ensure_ascii=False, default=str))\n"
)


def build_wrapper(body: str, params_obj: Any) -> str:
    """把函数体 + 参数组装成完整沙箱脚本。

    参数经 json.dumps + !r（repr 字面量）注入：repr 会正确转义引号/反斜杠/控制字符，
    纯数据字面量、无注入路径，且不依赖 base64（沙箱 import 白名单外）。
    """
    json_str = json.dumps(params_obj or {}, ensure_ascii=False)
    return WRAPPER_TEMPLATE.format(json_str=json_str, body=body)


def _has_top_level_run(body: str) -> bool:
    try:
        tree = ast.parse(body)
    except SyntaxError as e:  # noqa: BLE001
        return False
    for node in tree.body:  # 只看顶层
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            return bool(node.args.args)  # 至少 1 个参数（params）
    return False


def validate_tool_def(name: str, description: str, params: Any, body: str) -> Tuple[bool, str]:
    """静态校验自建工具定义。返回 (ok, 错误信息)——错误信息面向 LLM，可直接回喂修正。"""
    name = str(name or "").strip()
    if not _NAME_RE.match(name):
        return False, (f"工具名 '{name}' 不合法：必须以 dyn_ 开头，全小写字母/数字/下划线，"
                       "总长 4-43，如 dyn_tco_calc")
    description = str(description or "").strip()
    if not (3 <= len(description) <= 500):
        return False, "description 必须为 3-500 字符，说明这个工具计算/处理什么问题"
    params = params or {}
    if not isinstance(params, dict) or len(params) > MAX_PARAMS:
        return False, f"params 必须是 {{参数名: 说明}} 对象，且不超过 {MAX_PARAMS} 个"
    for p in params:
        if not _PARAM_RE.match(str(p)):
            return False, f"参数名 '{p}' 不合法：小写字母/数字/下划线"
    body = str(body or "").strip()
    if not (10 <= len(body) <= MAX_BODY_CHARS):
        return False, f"body 必须为 10-{MAX_BODY_CHARS} 字符的 Python 函数体"
    if not _has_top_level_run(body):
        return False, ("body 必须在顶层定义 def run(params):（params 为 dict，"
                       "返回可 JSON 序列化的结果，如 return {\"total\": 123}）")
    # AST 静态检查（与 run_python 沙箱同级：import 白名单 / 黑名单内建 / dunder 全禁）
    err = sandbox.precheck(body)
    if err:
        return False, f"body 未通过沙箱静态检查：{err}"
    return True, ""


def _placeholder_params(params: Dict[str, str]) -> Dict[str, str]:
    """占位试跑参数：每个声明参数填 "1"（数字可 float、文本可 str，覆盖绝大多数纯计算工具）。"""
    return {k: "1" for k in (params or {})}


async def dry_run(body: str, sample_params: Any) -> Tuple[bool, str]:
    """在子进程沙箱试跑一次。返回 (ok, 输出或错误)。"""
    code = build_wrapper(body, sample_params)
    if len(code) > sandbox.CODE_MAX_CHARS:
        return False, f"组装后代码超长（{len(code)} > {sandbox.CODE_MAX_CHARS} 字符）"
    err = sandbox.precheck(code)
    if err:
        return False, f"试跑未通过静态检查：{err}"
    res = await sandbox.run_python(code)
    if not res.get("ok"):
        stderr = str(res.get("stderr") or "")
        hint = ""
        low = stderr.lower()
        if "keyerror" in low or "missing" in low or "indexerror" in low:
            hint = ("（你的 run() 直接按键取值，但试跑参数里没有该键——"
                    "请在调用时提供 sample_params，或把取值改成 params.get('键名', 默认值) 防御式写法）")
        return False, f"试跑失败：{stderr[:300]}{hint}"
    out = str(res.get("stdout") or "").strip()
    try:
        json.loads(out)
    except Exception:  # noqa: BLE001
        return False, ("试跑输出不是合法 JSON——请确保 run() 返回可序列化对象，"
                       f"实际输出前 200 字符：{out[:200]}")
    return True, out


def register_auto_tool(registry: ToolRegistry, name: str, description: str,
                       params: Dict[str, str], body: str, source: str = "created") -> Tuple[bool, str]:
    """注册一个自建工具（执行 = 子进程沙箱）。成功后本任务内即刻可用。"""

    async def _execute(**kwargs) -> str:
        # 只传声明过的参数，防止模型传未声明键造成语义混乱
        args = {k: kwargs.get(k) for k in params}
        code = build_wrapper(body, args)
        res = await sandbox.run_python(code)
        if not res.get("ok"):
            return json.dumps({"status": "error", "tool": name,
                               "message": f"沙箱执行失败：{str(res.get('stderr') or '')[:400]}"},
                              ensure_ascii=False)
        out = str(res.get("stdout") or "").strip()
        return out if out else json.dumps({"status": "ok", "tool": name, "result": None}, ensure_ascii=False)

    registry.register(Tool(
        name=name,
        description=f"（自建工具/{source}）{description}",
        parameters={
            "type": "object",
            "properties": {k: {"type": "string", "description": str(v)[:200]} for k, v in params.items()},
            "required": list(params.keys()),
        },
        func=_execute,
    ))
    logger.info("[auto_tool] 已注册 %s（source=%s, body=%d chars）", name, source, len(body))
    return True, f"自建工具 {name} 注册成功，本任务内可直接调用（执行走子进程沙箱）。"


# ---------- 用户级持久化 ----------

def _user_tools_path(user_id: int) -> Path:
    return USER_TOOLS_DIR / f"{int(user_id)}.json"


def load_user_tools(user_id: int) -> List[Dict[str, Any]]:
    p = _user_tools_path(user_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        tools = data.get("tools") or []
        return tools if isinstance(tools, list) else []
    except Exception as e:  # noqa: BLE001
        logger.warning("[auto_tool] 读取用户 %s 自建工具失败（忽略）: %s", user_id, e)
        return []


def persist_user_tool(user_id: int, name: str, description: str,
                      params: Dict[str, str], body: str) -> Tuple[bool, str]:
    """落盘一个自建工具（同名覆盖=更新语义，天然去重收敛）。"""
    try:
        USER_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        tools = load_user_tools(user_id)
        tools = [t for t in tools if t.get("name") != name]
        tools.append({"name": name, "description": description, "params": params,
                      "body": body, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        if len(tools) > MAX_USER_TOOLS:
            return False, f"自建工具数已达上限（{MAX_USER_TOOLS}），请先清理不再使用的工具"
        p = _user_tools_path(user_id)
        p.write_text(json.dumps({"user_id": int(user_id), "tools": tools},
                                ensure_ascii=False, indent=1), encoding="utf-8")
        return True, f"已持久化（用户级，后续任务可直接调用）"
    except Exception as e:  # noqa: BLE001
        logger.warning("[auto_tool] 持久化失败: %s", e)
        return False, f"持久化失败：{e}"


def autoload_user_tools(registry: ToolRegistry, user_id: int) -> int:
    """任务启动时加载该用户的自建工具。每条**重新过静态检查**（防文件被篡改）。"""
    loaded = 0
    for t in load_user_tools(user_id):
        try:
            ok, _ = validate_tool_def(t.get("name", ""), t.get("description", ""),
                                      t.get("params") or {}, t.get("body", ""))
            if not ok:
                logger.warning("[auto_tool] 跳过未通过静态检查的持久化工具 %s", t.get("name"))
                continue
            register_auto_tool(registry, t["name"], t["description"],
                               t.get("params") or {}, t.get("body", ""), source="persisted")
            loaded += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("[auto_tool] 加载持久化工具失败（跳过）: %s", e)
    if loaded:
        logger.info("[auto_tool] 已为用户 %s 加载 %d 个自建工具", user_id, loaded)
    return loaded


def make_create_tool_func(registry: ToolRegistry, user_id: Optional[int] = None):
    """生成 create_tool 元工具（注册进注册表供模型调用）。"""

    async def _tool_create_tool(name: str = "", description: str = "",
                                params: Optional[dict] = None,
                                body: str = "",
                                sample_params: Optional[dict] = None,
                                persist: bool = True) -> str:
        ok, err = validate_tool_def(name, description, params, body)
        if not ok:
            return json.dumps({"status": "error", "message": err,
                               "hint": "请修正后重新调用 create_tool"}, ensure_ascii=False)
        # 试跑验证：模型给了样例参数 → 只试样例；没给 → 用占位参数（每键 "1"），
        # 消除「run() 直接按键取值导致空参 KeyError」的假失败（活测 T4 实证：曾引发 10 次重试）。
        if sample_params:
            samples = [sample_params]
        else:
            samples = [_placeholder_params(params or {})]
        seen: set = set()
        for s in samples:
            key = json.dumps(s, sort_keys=True, ensure_ascii=False, default=str)
            if key in seen:
                continue
            seen.add(key)
            ok, out = await dry_run(body, s)
            if not ok:
                return json.dumps({"status": "error", "message": out,
                                   "hint": "请修正 run() 后重新调用 create_tool（注册未生效）"},
                                  ensure_ascii=False)
        register_auto_tool(registry, name.strip(), description.strip(),
                           {str(k): str(v) for k, v in (params or {}).items()}, body)
        persisted = ""
        if persist and user_id and int(user_id) > 0:
            pok, pmsg = persist_user_tool(int(user_id), name.strip(), description.strip(),
                                          {str(k): str(v) for k, v in (params or {}).items()}, body)
            persisted = f"；{pmsg}" if pok else f"；持久化未成功：{pmsg}"
        return json.dumps({"status": "ok",
                           "message": f"自建工具 {name.strip()} 注册成功，本任务内可直接调用{persisted}"},
                          ensure_ascii=False)

    return _tool_create_tool
