# -*- coding: utf-8 -*-
"""L4-P3-3 真子体（subagents）：父体派生独立上下文/预算的子运行时（不是提示词角色）。

与 agents.py（提示词角色）/ harness 并行只读工具调用的本质区别：
子体 = **同一个 run_loop** + 影子 harness（独立 messages / RunGuards / 计划状态），
只拿到 goal，不继承父体对话上下文（防污染）；父体拿回**结构化摘要**而非全文（防上下文爆炸）。

预算与递归铁律：
1. 子体独立预算（默认 turns 8 / tokens 300k / wall 300s），烧钱上限 = 预算 × 最大子体数；
2. 子体注册表**过滤 spawn_subagent**（深度=1，禁止套娃）；
3. 本进程最大并发/累计子体数 AGENT_SUBAGENT_MAX（默认 4）——超限如实拒绝；
4. 写操作仍走 _gate_tool 弹窗（子体不能绕过人类确认）；
5. 总开关 AGENT_SUBAGENTS（默认 0=关），回退 = 置 0 重启。
"""
import copy
import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.agent.tools import ToolRegistry

logger = logging.getLogger(__name__)

SUBAGENT_TOOL_NAME = "spawn_subagent"

DEFAULT_TURNS = 8
DEFAULT_TOKENS = 300000
DEFAULT_WALL = 300
MAX_TURNS_CAP = 16
MAX_TOKENS_CAP = 1000000

# 本进程累计子体运行数（跨任务累加，防长期烧钱；负责任务结束重置见 reset_counter）
_counter = {"runs": 0}


def reset_counter() -> None:
    _counter["runs"] = 0


class _FilteredRegistry:
    """代理注册表：对子体隐藏 spawn_subagent（深度=1 防套娃）。其余工具直通共享。

    共享父 registry 的理由：子体本来就是"父体能力的受控子集"；register/remove 直通
    （dyn_* TTL 由父任务启动时统一清理，无跨任务残留）。
    """

    def __init__(self, base: ToolRegistry):
        self._base = base

    def get(self, name: str):
        if name == SUBAGENT_TOOL_NAME:
            return None
        return self._base.get(name)

    def list_tools(self) -> List:
        return [t for t in self._base.list_tools() if t.name != SUBAGENT_TOOL_NAME]

    def get_tool_names(self) -> List[str]:
        return [n for n in self._base.get_tool_names() if n != SUBAGENT_TOOL_NAME]

    def get_tools_prompt(self) -> str:
        return self._base.get_tools_prompt()

    def register(self, tool) -> None:
        self._base.register(tool)

    def remove(self, name: str) -> bool:
        return self._base.remove(name)


def _make_shadow(parent) -> Any:
    """浅拷贝父 harness 成子体影子：重置子体专属可变状态，换上过滤注册表。"""
    sh = copy.copy(parent)
    sh.tools = _FilteredRegistry(parent.tools)
    sh._step_count = 0
    sh._plan = []
    sh._plan_status = []
    sh._consecutive_tool_failures = 0
    sh._fc_meta = None
    sh._fc_fail_info = None
    sh._logs = []                 # 子体日志独立（不混入父 SSE 日志流）
    sh._last_trajectory = ""
    sh._intent = "general"        # 子体姿态用 general：不受方案字数契约约束，按 goal 交付
    return sh


async def run_subagent(parent, goal: str, budget_turns: int = DEFAULT_TURNS,
                       budget_tokens: int = DEFAULT_TOKENS,
                       deliverable_hint: str = "") -> Dict[str, Any]:
    """跑一个子体（独立上下文 + 独立预算）。返回结构化结果给父体。"""
    from app.agent.runtime.runner import run_loop

    goal = (goal or "").strip()
    if not goal:
        return {"status": "error", "message": "goal 不能为空——子体只拿到这一句话，必须写清要它做什么、交付什么"}

    budget_turns = max(2, min(int(budget_turns or DEFAULT_TURNS), MAX_TURNS_CAP))
    budget_tokens = max(50000, min(int(budget_tokens or DEFAULT_TOKENS), MAX_TOKENS_CAP))

    shadow = _make_shadow(parent)
    sub_log: List[Dict[str, Any]] = []
    t0 = time.time()
    _counter["runs"] += 1

    user_msg = (
        f"【子任务】{goal}\n"
        + (f"【交付要求】{deliverable_hint}\n" if deliverable_hint else "")
        + "你是被父任务派生的子任务执行者：看不到父任务的对话，只拿到上面这个目标。"
          "完成后直接输出**结论正文**（会被父任务取用，不要寒暄）；"
          "若确实无法完成，如实说明缺口与原因，不要编造。"
    )

    result = await run_loop(
        shadow, user_msg, f"subagent_{int(time.time()*1000)}",
        None,                      # 子体不发 SSE 事件（父体的 tool_start/end 已覆盖可视）
        sub_log,
        extra_blocks=["【运行模式】子任务模式：独立预算，聚焦单一目标，尽快交付结论。"],
        budget_override={"turns_max": budget_turns, "token_budget": budget_tokens,
                         "wall_budget": DEFAULT_WALL},
    )

    elapsed = round(time.time() - t0, 1)
    if result is None or not result.get("final"):
        return {"status": "error",
                "message": f"子任务未能产出结论（耗时 {elapsed}s，可能预算不足或执行失败）",
                "turns": (result or {}).get("turns"), "elapsed": elapsed}
    return {
        "status": "ok",
        "final": str(result.get("final") or "")[:4000],   # 结构化摘要上限，防父上下文爆炸
        "turns": result.get("turns"),
        "tokens": (result.get("guards") or {}).get("tokens_used"),
        "elapsed": elapsed,
        "compactions": (result.get("trace") or {}).get("compactions", 0),
    }


def make_spawn_func(parent_ref):
    """生成 spawn_subagent 工具函数（parent_ref 是 setparent 注入的弱引用槽——用 dict 装父 harness）。"""

    async def _tool_spawn_subagent(goal: str = "", deliverable: str = "",
                                   budget_turns: int = DEFAULT_TURNS,
                                   budget_tokens: int = DEFAULT_TOKENS) -> str:
        from app.config import AGENT_SUBAGENT_MAX
        parent = parent_ref.get("harness")
        if parent is None:
            return "错误：子体派生不可用（父任务上下文缺失）。"
        if _counter["runs"] >= int(AGENT_SUBAGENT_MAX):
            return (f"错误：本任务派生子体数已达上限（{AGENT_SUBAGENT_MAX}）。"
                    "请基于已有信息自行完成剩余工作，或如实说明未覆盖的部分。")
        res = await run_subagent(parent, goal, budget_turns, budget_tokens, deliverable)
        if res.get("status") != "ok":
            return json.dumps(res, ensure_ascii=False)
        return json.dumps({
            "status": "ok",
            "summary": res["final"],
            "stats": {"turns": res.get("turns"), "tokens": res.get("tokens"), "elapsed_s": res.get("elapsed")},
            "hint": "以上是子任务的结论正文。多个子任务的结果请由你汇总为单一交付物。",
        }, ensure_ascii=False)

    return _tool_spawn_subagent


# 父 harness 注入槽（tools.py 注册的工具函数无 harness 引用，run 时由 harness 绑定）
parent_slot: Dict[str, Any] = {"harness": None}
