"""
P2-1-B：多智能体角色定义（Orchestrator-Workers）

3 个 Worker 角色（同一 ReAct 引擎，不同 system prompt + 工具子集）：
- 需求分析师 DemandAnalyst   : 提炼行业/场景/痛点/关键词；需求模糊时 Clarify
- 方案架构师 SolutionArchitect: 按需求检索资料，起草方案
- 质量校验官 QualityReviewer  : 对照关键元素查漏补缺，可补检索/导出

Orchestrator（harness._plan_and_execute）按 plan 步序调用各角色，
每个角色只在其对应 plan 步内生效（plan_index 归属天然正确）。

设计铁律：不引入第二套执行框架——角色仅是 prompt + 工具子集的不同。
"""

# 角色 → plan 步索引（solution/competitor 3 步 plan：0=分析师 1=架构师 2=校验官）
ROLE_PLAN_STEP = {
    "demand_analyst": 0,
    "solution_architect": 1,
    "quality_reviewer": 2,
}

# 角色定义：phase 标识（SSE agent_phase 事件用）、工具子集、角色提示词
AGENT_ROLES = {
    "demand_analyst": {
        "name": "需求分析师",
        "phase": "demand_analysis",
        "tools": ["analyze_demand", "read_customer_file", "list_dir", "web_search"],
        "prompt": (
            "你扮演【需求分析师】，负责把用户的模糊需求梳理成可执行的结构化输入。\n"
            "任务：识别用户所在行业、核心业务场景、痛点与目标，给出检索关键词。\n"
            "若用户提供了客户资料文件，请读取后提炼关键约束。"
        ),
    },
    "solution_architect": {
        "name": "方案架构师",
        "phase": "solution_architect",
        "tools": ["search_kb", "search_competitor", "web_search"],
        "prompt": (
            "你扮演【方案架构师】，负责基于需求分析结果检索华为云相关资料，形成方案骨架。\n"
            "任务：检索知识库中的解决方案文档与产品资料（必要时竞品对比），"
            "提炼出适合客户的技术方案要点。"
        ),
    },
    "quality_reviewer": {
        "name": "质量校验官",
        "phase": "quality_review",
        "tools": ["search_kb"],
        "prompt": (
            "你扮演【质量校验官】，负责对方案做最终查漏补缺。\n"
            "任务：对照售前方案必备要素（痛点分析、产品与技术方案、实施路径、价值收益），"
            "若发现缺失信息可补充检索；确认完备后总结本步结论，供最终汇总。"
        ),
    },
}


def role_for_step(step_index: int) -> str:
    """plan 步索引 → 角色名（超出映射范围的步归为校验官）"""
    for role, step in ROLE_PLAN_STEP.items():
        if step == step_index:
            return role
    return "quality_reviewer"


def get_role(step_index: int) -> dict:
    role_name = role_for_step(step_index)
    return AGENT_ROLES[role_name]
