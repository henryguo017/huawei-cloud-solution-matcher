# -*- coding: utf-8 -*-
"""L4-P2 Agent Runtime · 计划所有权（todo.py）

落实判据 **C4：计划所有权在模型**，并在 L4-P0 给它加上**唯一的齿：闭合**。

legacy 路径的计划是「planner 生成一次 → PLAN_STEP_TOOL_MAP 把步与工具锁死」，
模型之后无法改动 —— 这是 workflow 的核心特征。本模块把计划变成模型**可调用的工具**：
模型开工前发布计划、执行中随时改写。

**L4-P0 的语义变更（计划从「叙述」变「有齿的待办」）**：
  - 计划是模型自己的待办清单。终稿交付前，每步必须处于 `done` 或 `skipped`(带原因)。
  - 有未闭合项时，宿主**不接收终稿**，把未闭合项交回模型自决（补做 / 标 skipped+原因）。
  - ⚠️ 宿主**不做**"某工具属于某步"的归属推导，也**不规定**顺序 —— 只查
    「模型自己发布的计划有没有未闭合项」这一个事实。控制权仍在模型手里。

由此产生两个验收现象：
  - 计划文本与最终工具调用序列**不一致** → 证明计划不锁死执行（A9）；
  - 交付时计划**全部闭合** → 证明模型把待办当回事（A11 计划收敛率）。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

TODO_TOOL_NAME = "update_plan"

# 闭合状态：done / skipped 视为已闭合；pending / running 视为未闭合
_CLOSED = ("done", "skipped")

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
    # L4-P0：放弃某步是**合法**的，但必须由模型显式声明（可带原因），不允许"默默不收尾"
    "skipped": "skipped",
    "skip": "skipped",
    "dropped": "skipped",
    "abandoned": "skipped",
    "cancelled": "skipped",
}

TODO_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TODO_TOOL_NAME,
        "description": (
            "发布或更新你的执行计划（同时是你自己的待办清单）。执行顺序由你决定，随时可以改写；"
            "但**收尾前必须让每一步都闭合**：要么 done，要么 skipped 并在 note 里说明为什么不做。"
            "建议：开始执行前先发布一次计划；某步完成、计划有变、或决定不做某步时更新它。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "计划步骤列表（按你打算执行的顺序）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string", "description": "步骤描述（一句话）"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "done", "skipped"],
                                "description": "该步当前状态；skipped 表示主动放弃（须在 note 说明原因）",
                            },
                            "note": {"type": "string", "description": "补充说明（skipped 时必填原因）"},
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


def open_steps(statuses: List[str]) -> List[int]:
    """未闭合步的索引（非 done/skipped）。

    L4-P0：这是宿主判断"计划有没有齿"的**唯一**依据 —— 只看状态，不看工具、不做归属推导。
    """
    return [i for i, st in enumerate(statuses or []) if st not in _CLOSED]


def closure_summary(steps: List[str], statuses: List[str]) -> str:
    """给日志/元数据用的一行闭合概况。"""
    n = len(steps or [])
    done = sum(1 for s in (statuses or []) if s == "done")
    skipped = sum(1 for s in (statuses or []) if s == "skipped")
    return f"{done} done / {skipped} skipped / {len(open_steps(statuses))} open / {n} total"


def build_close_instruction(steps: List[str], statuses: List[str]) -> str:
    """计划未闭合时，交回模型自决的提示（**给选项，不替它做决定**）。"""
    idxs = open_steps(statuses)
    lines = []
    for i in idxs:
        step = steps[i] if i < len(steps) else "(未知步骤)"
        st = statuses[i] if i < len(statuses) else "pending"
        lines.append(f"  - 第 {i + 1} 步「{step}」（当前 {st}）")
    body = "\n".join(lines)
    return (
        "【宿主核验】你准备交付，但你**自己发布的计划**里还有未闭合的步骤：\n"
        f"{body}\n"
        "交付前请自行决定怎么处理，二选一（由你判断，宿主不替你选）：\n"
        "  1) 继续调用工具把它做完，然后用 update_plan 标为 done；\n"
        "  2) 如果这一步确实不必做（信息已足够 / 与目标无关 / 无法完成），\n"
        "     用 update_plan 把它标为 skipped 并在 note 里写清原因，再交付。\n"
        "注意：不要为了让计划好看而虚标 done —— 若某步实际没做，如实标 skipped 才是正确做法。"
    )


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
    # L4-P2 观测：计划改写次数（供 A9 计划自治度评估——>1 证明模型执行中确实改了计划，
    # 而不是像老管线那样一次铸死）。计数归 _run_fc_runtime 复位。
    try:
        harness._plan_update_count = int(getattr(harness, "_plan_update_count", 0) or 0) + 1
    except (TypeError, ValueError):
        harness._plan_update_count = 1
    reason = str((args or {}).get("reason") or "").strip()
    await emit_plan(harness, event_callback, steps, statuses, intent=getattr(harness, "_intent", "solution"))

    idx = active_index(statuses)
    done_n = sum(1 for s in statuses if s == "done")
    skip_n = sum(1 for s in statuses if s == "skipped")
    _open = open_steps(statuses)
    obs = (
        f"计划已更新（{len(steps)} 步：{done_n} 完成 / {skip_n} 跳过 / {len(_open)} 待办）。"
        + (f"当前进行中：第 {idx + 1} 步「{steps[idx]}」。" if idx >= 0 else "")
        + (f"调整原因：{reason}" if reason else "")
        + (" 计划已全部闭合，你可以在需要时直接交付终稿。" if not _open
           else f" 仍有 {len(_open)} 步未闭合 —— 收尾前请把每一步做成 done 或 skipped(带原因)。")
    )
    harness._log("system", f"[FC] update_plan {len(steps)} 步 active={idx} · {closure_summary(steps, statuses)}")
    return obs, idx
