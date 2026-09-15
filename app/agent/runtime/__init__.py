# -*- coding: utf-8 -*-
"""L4-P2 Agent Runtime：原生 function calling 的 model-in-the-loop 引擎。

设计文档：docs/agent-architecture-fc-2026-09-11.md
入口：`run_loop`（主循环）。宿主侧组装（终稿质量门 / 落库 / 结果封装）在
`AgentHarness._run_fc_runtime`，本包不含产品层逻辑。

模块职责（单向依赖，无环）：
    schema.py   工具接口层：Tool→function schema、消息规范化、只读并行判定
    guards.py   预算守卫：轮次/token/墙钟，先 advisory 后熔断（不做任务决策）
    todo.py     计划所有权：update_plan 工具（C4）
    context.py  上下文装配 + 压缩
    verify.py   完成态核验（治"已保存"幻觉）
    events.py   trace → SSE 事件契约映射
    runner.py   主循环状态机
"""

from app.agent.runtime.runner import run_loop

__all__ = ["run_loop"]
