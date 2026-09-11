# -*- coding: utf-8 -*-
"""L4-P2 Agent Runtime · 事件映射（events.py）

职责（单一）：把运行时的内部进展**翻译成既有 SSE 事件契约**。

为什么单独成模块：前端 `agent_workspace.js` 的 `onEvent` 已按
plan / thought / tool_start / tool_end / delta / final / result / self_check /
permission_request / doc_generated 消费事件。运行时换引擎但**不换契约**，
前端因此零改动（只改一个开关字段）。把这些映射集中在一处，
后续任何人改事件都只需要改这里，且一眼能看出契约边界。
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 终稿渐进上屏的分片大小（字符）。
# 语义澄清：这是把**模型已经产出的终稿**分片推送以获得打字机观感，
# 不是重新生成（重新生成会违反"终稿归模型所有"的设计决策 D1）。
DELTA_CHUNK_CHARS = 240


async def emit_plan(harness, event_callback, steps: List[str], statuses: List[str], intent: str = "solution") -> None:
    """plan 事件：计划面板渲染。steps/plan_status 与前端 _renderPlan 对齐。

    附带 runtime：FC 引擎的计划由模型自由维护，没有 legacy 的"步 ↔ 工具/步结果"绑定，
    前端据此隐藏"重跑本步"（该功能依赖 legacy 的 _step_results）。
    """
    await harness._emit(event_callback, {
        "type": "plan",
        "steps": list(steps or []),
        "intent": intent,
        "plan_status": list(statuses or []),
        "runtime": getattr(harness, "_runtime", "") or "",
    })


async def emit_thought(harness, event_callback, text: str, step: int = 0) -> None:
    """thought 事件：思考面板。运行时用它承载模型的 reasoning_content（真实推理）。"""
    t = (text or "").strip()
    if not t:
        return
    await harness._emit(event_callback, {"type": "thought", "step": step, "text": t[:400]})


async def emit_tool_start(harness, event_callback, tool: str, step: int, plan_index: int = -1) -> None:
    await harness._emit(event_callback, {
        "type": "tool_start",
        "step": step,
        "tool": tool,
        "plan_index": plan_index,
    })


async def emit_tool_end(harness, event_callback, tool: str, step: int, summary: str, plan_index: int = -1) -> None:
    await harness._emit(event_callback, {
        "type": "tool_end",
        "step": step,
        "tool": tool,
        "summary": summary,
        "plan_index": plan_index,
    })


async def emit_delta_chunks(harness, event_callback, text: str, chunk: int = DELTA_CHUNK_CHARS) -> None:
    """把终稿分片作为 delta 事件推送（渐进渲染，不重新生成）。"""
    if not text:
        return
    n = max(1, int(chunk))
    for i in range(0, len(text), n):
        await harness._emit(event_callback, {"type": "delta", "text": text[i:i + n]})


async def emit_final(harness, event_callback, step: int, elapsed: float, plan_index: int = -1) -> None:
    await harness._emit(event_callback, {
        "type": "final",
        "step": step,
        "elapsed": round(elapsed, 2),
        "plan_index": plan_index,
    })


async def emit_skill_pack(harness, event_callback, pack: Optional[Dict[str, Any]], kind: str = "") -> None:
    """技能包挂载提示（与 legacy 路径同事件形状；kind=capability 为能力包）。"""
    if not pack:
        return
    ev: Dict[str, Any] = {
        "type": "skill_pack",
        "industry": pack.get("industry", ""),
        "version": pack.get("version", ""),
    }
    if kind:
        ev["kind"] = kind
    await harness._emit(event_callback, ev)
