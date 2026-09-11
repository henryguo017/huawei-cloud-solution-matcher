# -*- coding: utf-8 -*-
"""L4-P2 Agent Runtime · 计划所有权（todo.py）

落实判据 **C4：计划所有权在模型**。

legacy 路径的计划是「planner 生成一次 → PLAN_STEP_TOOL_MAP 把步与工具锁死」，
模型之后无法改动 —— 这是 workflow 的核心特征。本模块把计划变成模型**可调用的工具**：
模型开工前发布计划、执行中随时改写；宿主只负责展示与记录，**不用计划约束执行**。

由此产生一个反直觉但正确的验收现象：
    计划文本与最终工具调用序列**不一致**，恰恰证明计划不再锁死执行（A9 的证据）。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

TODO_TOOL_NAME = "update_plan"

# 前端 plan_status 只认 pending / running / done，模型侧语义更自然的是 in_progress
_STATUS_MAP = {
    "pending": "pending",
    "todo": "pending",
    "in_progress": "running",
    "running": "running",
    "doing": "running",
    "done": "done",
    "completed": "done",
    "complete": "done",
}

TODO_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TODO_TOOL_NAME,
        "description": (
            "发布或更新你的执行计划（给用户看的进度视图）。它**不约束**你的执行顺序 —— "
            "你随时可以修改。建议：开始执行前先发布一次计划；计划发生变化或某步完成时更新它。"
            "每项一个步骤，status 用 pending / in_progress / done 标注当前进度。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "计划步骤列表（按执行顺序）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string", "description": "步骤描述（一句话）"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "done"],
                                "description": "该步当前状态",
                            },
                            "note": {"type": "string", "description": "补充说明（可选）"},
                        },
                        "required": ["step"],
                    },
                },
                "reason": {"type": "string", "description": "本次发布/调整计划的原因（可选）"},
            },
            "required": ["items"],
        },
    },
}


def normalize_items(args: Optional[Dict[str, Any]]) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    """把模型传入的 items 规范化为 (steps, statuses, clean_items)。

    容错：items 为空/非列表 → 全空返回（调用方给模型结构化错误，不抛异常）；
    单步缺 status → pending；未知 status → pending。
    """
    raw = (args or {}).get("items")
    if not isinstance(raw, list):
        return [], [], []
    steps: List[str] = []
    statuses: List[str] = []
    clean: List[Dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        step = str(it.get("step") or "").strip()
        if not step:
            continue
        st = _STATUS_MAP.get(str(it.get("status") or "").strip().lower(), "pending")
        steps.append(step)
        statuses.append(st)
        clean.append({"step": step, "status": st, "note": str(it.get("note") or "").strip()})
    return steps, statuses, clean


def active_index(statuses: List[str]) -> int:
    """当前活跃步索引（首个 in_progress/running）；没有则 -1。"""
    for i, st in enumerate(statuses or []):
        if st == "running":
            return i
    return -1


async def handle_update_plan(harness, event_callback, args: Optional[Dict[str, Any]]):
    """处理模型对 update_plan 的调用。

    返回 (observation_text, active_step_index)：
      - observation_text 回填给模型（确认已发布 + 当前进度，便于模型自洽）；
      - active_step_index 供运行时给 tool 事件带 plan_index，让 Plan 面板点亮"正在做的那步"。
    不经过权限闸门：该工具只写内存与推事件，无外部副作用。
    """
    from app.agent.runtime.events import emit_plan

    steps, statuses, clean = normalize_items(args)
    if not steps:
        return (
            "错误：update_plan 的 items 不能为空，且每项必须包含 step 字段，"
            "status 取 pending / in_progress / done 之一。请修正后重新调用。",
            -1,
        )

    harness._plan = steps
    harness._plan_status = list(statuses)
    reason = str((args or {}).get("reason") or "").strip()
    await emit_plan(harness, event_callback, steps, statuses, intent=getattr(harness, "_intent", "solution"))

    idx = active_index(statuses)
    done_n = sum(1 for s in statuses if s == "done")
    obs = (
        f"计划已发布（{len(steps)} 步，已完成 {done_n} 步）。"
        + (f"当前进行中：第 {idx + 1} 步「{steps[idx]}」。" if idx >= 0 else "")
        + (f"调整原因：{reason}" if reason else "")
        + " 你可以在需要时再次调用 update_plan 更新进度；它不影响你的执行顺序。"
    )
    harness._log("system", f"[FC] update_plan {len(steps)} 步 active={idx}")
    return obs, idx
