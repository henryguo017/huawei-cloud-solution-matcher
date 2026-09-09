"""
Agent 执行引擎 (Harness)

职责：
- 管理 ReAct 循环（Thought → Action → Observation → 重复）
- 步数限制 + 超时保护
- 工具执行调度
- 错误重试 + 降级
- 全链路日志

设计原则：
- 零改动现有代码
- 纯 ReAct 文本协议（兼容所有 LLM，不需要原生 function calling）
- 200 行内搞定核心逻辑
"""

import re
import json
import time
import asyncio
import uuid
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from app.agent.tools import ToolRegistry
from app.agent.tools import _tool_analyze_demand, _get_kb

# 文档附件注入标记（2026-09-09）：api/agent_routes.py 构建 doc_block 以此开头。
# 用途：①带附件时跳过澄清表（需求往往就在附件里）；②真方案诉求下引导 read_customer_file。
# 注意：附件文本已由 agent_routes 预处理注入消息，此处不再强制 intent=solution
# （简历案例实测：强制会把"聊着天让看看简历"拉进方案流水线还弹澄清表）。
DOC_ATTACH_MARKER = "[用户在本对话附带了以下客户资料文件"

from app.agent.memory import ConversationMemory
from app.services.solution_prompt import (
    parse_markdown_to_chapters,
    build_anti_hallucination,
    build_audience_tone,
    build_few_shot,
    build_format_block,
    build_compare_block,
)
from app.services.solution_matcher import SolutionMatcherService
from app.agent.clarify_store import ClarifySessionStore
from app.agent.intent import classify_intent
from app.config import (
    MATCH_LLM_MODEL, SUPPORTED_COMPETITORS, AGENT_TWO_PHASE, AGENT_MULTI_AGENT, AGENT_CONTEXT_WINDOW,
    AGENT_SELF_CHECK, SELF_CHECK_PASS, SELF_CHECK_MAX_ITERS,
    AGENT_REFLEXION_REPLAN, REFLEXION_MAX_REPLANS, AGENT_PARALLEL_TOOLS, MAX_PARALLEL,
    AGENT_SKILL_PACKS,
)

logger = logging.getLogger(__name__)


def _trunc(s: str, n: int) -> str:
    """截断过长的文本段（用于追加到 ReAct prompt），防止多步检索后 prompt 爆炸导致模型失焦。"""
    s = s or ""
    if len(s) <= n:
        return s
    return s[:n] + f"\n…（已截断，保留前 {n} 字）"


# ReAct 提示词模板（Final Answer 结构与标准模式共用同一套增强指令，保证三模式质量一致）
REACT_SYSTEM_PROMPT_BASE = """你是一个智能解决方案匹配助手，帮助用户找到最合适的华为云解决方案。
【自我认知】你由自研 AgentHarness 驱动，是一个具备「规划-执行-反思-重规划」能力、可自主选择并调用工具、
拥有跨轮记忆与技能包的 agentic workflow 系统（工作流型智能体）。被问及身份时如实、大方描述这些能力，
不要自我贬低（如"我还不是 Agent""我只是普通问答机器人"），也不要夸大成无所不能。

## 工作方式
你需要使用"思考-行动-观察"的方式逐步解决问题：

1. 先判断需求是否"关键信息齐全"：
   - 关键信息 = 行业（或业务领域，大类即可）+ 核心场景/目标 + 至少一个具体细节（规模/数量/痛点量化等）。三者齐全时直接走工具链，不要用 Clarify。
   - 如果行业/核心场景缺失、且无法从对话历史推断 → 第一步输出 Clarify 向用户提问（不要先调用任何工具）；拿到补充后再走工具链。
   - **特别注意**：用户输入 ≥30 字且能同时提取出「行业+场景+细节」三类信息时，视为关键信息齐全。例如「中型制造企业50台设备想做预测性维护减少停工」已包含制造(行业)+预测性维护(场景)+50台(细节)，应直接检索不要追问。
   - 如果关键信息齐全 → 调用 analyze_demand 分析需求，再 search_kb 检索，必要时 search_competitor 对比，最后 Final Answer。
2. 根据分析结果，调用 search_kb 检索华为云方案（换关键词可多次调用）
3. 如果用户提到竞品，调用 search_competitor 进行对比
4. 收集足够信息后，直接输出 Final Answer 即完整方案报告

## 可用工具
{tools}

## 输出格式（严格遵守）
每次只输出以下两种格式之一：

### 调用工具时：
Thought: [你对当前状态的分析和下一步计划]
Action: [工具名称]
Action Input: [JSON 格式的参数，如 {{"query": "制造业 工业物联网"}}]

### 给出最终答案时：
Thought: 我已收集到足够信息，可以给出完整方案。
Final Answer: 
[你的完整方案报告。系统会基于你检索到的资料进行来源标注与润色，但请你尽量写全结构、并在引用资料时标注来源文件名（如：据《xxx.docx》）。]

### 需要向用户澄清时（仅当行业/核心场景/具体细节确实全部缺失时才使用，不要对已有足够信息的需求追问）：
Clarify: [{{"question": "这个项目的主要业务领域是？", "options": ["制造业", "政务", "零售/电商", "医疗健康", "教育", "其他（请补充）"]}}]
（可一次给 1-2 个问题，每个问题可附带若干候选选项方便用户快速选择；注意：如果用户已提到行业大类如「制造企业」「学校」「医院」等，不要再追问细分——直接走工具链）

## 规则
- 必须调用工具来获取信息，不能凭空编造
- Action Input 必须是合法的 JSON
- 每次只输出一个 Action，不要一次输出多个
- 如果工具返回错误，尝试调整参数重试一次，再失败就基于已有信息回答
- 最多执行 {max_steps} 步
- 不要调用 generate_report 工具——你直接用 Final Answer 输出报告即可
- 【智能跳过澄清】如果用户原始需求已经包含以下 **全部 3 项**信息，说明需求足够详细，**请直接调用工具链（analyze_demand → search_kb → Final Answer），不要再用 Clarify 提问**：
  ① 行业或业务领域（如「制造」「政务」「零售」等大类即可，不需要精确到细分）
  ② 核心业务场景或目标（如「设备预测性维护」「数据上云」「智慧园区管理」）
  ③ 至少一个具体细节（如规模/数量/痛点量化/技术偏好等，例如「50台设备」「每次损失5万」「100人团队」）
  判断标准：用户输入 ≥30 字且能同时提取出上述三类信息时，视为关键信息齐全，直接走检索。
- 【澄清优先】仅当关键信息确实缺失、且无法从对话历史推断时，才用 Clarify 向用户提问（不要先调 analyze_demand/search_kb）；拿到补充后再走工具链。
- 【多轮澄清策略】用户首次输入通常很模糊（如"帮我做个云方案"仅几个字），一次提问往往不够。请按以下策略逐步收集：
  ① 第 1 轮：优先问行业/业务领域（最关键，没有行业无法精准检索）。但如果用户已提到行业大类（如「制造企业」「学校」「医院」），**不要再追问细分行业**——直接基于已有信息走工具链。
  ② 第 2 轮：拿到行业后，如果用户原始描述仍很短（<20字）或缺乏具体业务场景，请继续追问核心场景/目标（如"主要想解决什么问题？是数据上云、应用迁移、还是搭建新平台？"）或规模/阶段——不要急着出方案
  ③ 第 3 轮：仅用于关键细节补漏（如特殊合规要求、技术偏好）
  ④ 满 3 轮后必须给出 Final Answer，不再追问
- 每次最多 1-2 个问题；提问后等待用户回答再继续，不要在提问的同一轮给出 Final Answer
- 如果你已向用户提过 **2 次以上** 问、且用户已补充了基本信息，请基于已有信息给出 Final Answer；仅当补充后仍有**致命缺失**（如完全无法判断方案方向）时才允许第 3 轮追问，之后必须出方案"""


# Final Answer 增强指南：与标准模式共用 14 章结构 + 防幻觉 + 话术
REACT_FINAL_GUIDE = (
    "\n\n【Final Answer 报告结构要求（务必覆盖以下全部章节）】\n"
    + build_format_block()
    + "\n"
    + build_anti_hallucination()
    + build_audience_tone()
    + build_few_shot()
    + "【来源标注】引用检索到的资料时，必须在句末注明来源文件名（如：据《xxx.docx》），"
    "来源文件名已在上方 Observation 的 source 字段给出。\n"
)


# Final Answer 增强指南（竞品对比意图，B 方案）：轻量对比格式 + 防幻觉 + 话术
REACT_FINAL_GUIDE_COMPETITOR = (
    "\n\n【Final Answer 对比报告结构要求（务必覆盖以下全部章节）】\n"
    + build_compare_block()
    + "\n"
    + build_anti_hallucination()
    + build_audience_tone()
    + build_few_shot()
    + "【来源标注】引用检索到的资料时，必须在句末注明来源文件名（如：据《xxx.docx》），"
    "来源文件名已在上方 Observation 的 source 字段给出。\n"
)


# Final Answer 增强指南（文件操作意图）：引导用文件工具真实操作，不套方案模板
REACT_FINAL_GUIDE_FILEOPS = (
    "\n\n【文件操作执行要求】\n"
    "1. 用户要查看/读取/分析自己上传的文件或客户资料。\n"
    "2. 先调用 list_dir 列出用户文件目录；若用户点名了某个文件，直接调用 read_customer_file 读取。\n"
    "3. 读取后基于文件内容回答用户（总结要点/提取需求/回答问题），不要编造文件里没有的内容。\n"
    "4. 若目录为空或文件不存在，如实告知并给出下一步建议（如重新上传）。\n"
    "5. 这不是方案生成需求，禁止套用 14 章方案模板。\n"
    + build_anti_hallucination()
    + "【来源标注】引用文件内容时，注明文件名（如：据《客户需求.docx》）。\n"
)


# Final Answer 增强指南（产品图谱/架构类查询）：检索 + 文字结构化呈现，不套方案模板
REACT_FINAL_GUIDE_KNOWLEDGE_Q = (
    "\n\n【产品知识查询执行要求】\n"
    "1. 用户想了解某华为云产品/服务的结构、架构、功能全景、模块组成（如 IoTDA 产品图谱、ECS 架构）。\n"
    "2. 调用 search_kb 检索该产品相关资料（关键词含产品名 + 架构/模块/功能）。\n"
    "3. 基于检索资料用文字结构化呈现：核心模块/功能清单、典型架构分层（端-边-云等）、关键能力、适用场景。\n"
    "4. 使用列表、小标题组织内容；引用资料处标注来源（据《xxx》或[资料N]）。\n"
    "5. 禁止套用 14 章方案模板，不输出「执行摘要/价值主张/实施路径」等方案章节；除非用户明确要方案，否则保持知识性概述。\n"
    + build_anti_hallucination()
    + "【来源标注】引用检索到的资料时，在句末注明来源（据《xxx》）。\n"
)


class AgentHarness:
    """
    ReAct 循环执行引擎

    用法:
        harness = AgentHarness(tools=registry, memory=memory)
        result = await harness.run("我想让工厂更智能", session_id="user_123")
    """

    def __init__(
        self,
        tools: ToolRegistry,
        memory: ConversationMemory,
        max_steps: int = 8,
        timeout: float = 120.0,
        verbose: bool = True,
    ):
        self.tools = tools
        self.memory = memory
        self.max_steps = max_steps
        self.timeout = timeout
        self.verbose = verbose

        self._step_count = 0
        self._start_time = 0.0
        self._logs: list = []
        self._intent = "solution"          # 意图路由结果（首轮 classify 后写入）
        self._format_mode = "solution"     # 最终答案结构：solution=14章 / competitor=对比格式
        self._client_context = ""          # B修复：客户背景上下文（run 入口注入，透传给统一增强管线）
        self._plan: list = []              # P0：执行计划（_emit_plan 写入，前端 Plan 面板渲染）
        self._plan_original_input: str = ""  # P2-D5：plan 对应的原始用户需求（Plan 单步重跑重新汇总用）
        self._plan_status: list = []       # P1-1：plan 每步状态 pending/running/done
        self._last_draft: str = ""         # P1-2：终稿缓存，供 generate_doc 拦截导出（跨轮保留）
        self._web_search_count: int = 0    # P1-2：本会话联网检索次数（限流）
        self._consecutive_tool_failures: int = 0   # P1-3：连续工具失败计数（触发反思）
        self._reflexion_count: int = 0     # P1-3：反思触发次数
        self._reflexion_success: bool = False       # P1-3：反思是否最终纠正成功
        self._last_trajectory: str = ""    # P1-3：最近执行轨迹（反思用，run() 内亦会重置）
        # P3-1：真反思-重规划状态
        self._replan_count: int = 0        # 已重规划次数（受 REFLEXION_MAX_REPLANS 保护）
        self._last_replanned: bool = False # 本次运行是否触发过重规划（写入 result.replanned）
        # P2-1-A：真·两阶段执行状态（plan 驱动执行顺序）
        self._step_results: dict = {}      # P2：每步执行结果（供 D5 重跑与多智能体消费）
        self._phase_outputs: dict = {}     # P2-1-B：多智能体各阶段产物（demand/architect/reviewer）
        self._two_phase_enabled = True     # P2：运行期开关（run() 内按 config 覆盖）
        self._multi_agent_enabled = True   # P2：多智能体开关
        self._memory_context_injected = False  # P2-2：长程记忆注入标记（仅首轮注入一次）
        self._remote_tool_names: list = []     # P2-3：已注册远端 MCP 工具名（plan 步工具集的逃生舱）

    # ---- 主入口 ----

    def set_remote_tool_names(self, names: list) -> None:
        """P2-3：注入已注册远端 MCP 工具名（由 SolutionAgent 在 _ensure_mcp_tools 后调用）。"""
        self._remote_tool_names = list(names) if names else []

    async def _emit(self, event_callback, event: Dict[str, Any]) -> None:
        """安全调用事件回调"""
        if event_callback:
            try:
                await event_callback(event)
            except Exception as e:
                logger.warning(f"事件回调失败: {e}")

    # ---- Plan 面板（2026-08-26 P0：Devin 式执行计划，先列计划再动手） ----

    _PLAN_INTENT_META = {
        "solution": {
            "default": ["分析需求，明确行业与痛点", "检索华为云相关解决方案资料", "生成可落地的方案报告"],
            "prompt_hint": "这是售前方案匹配任务，计划应包含：需求分析 → 知识库检索（必要时竞品对比）→ 方案撰写",
        },
        "competitor": {
            "default": ["识别对比双方与行业背景", "检索华为云与竞品方案资料", "从能力/成本/落地对比并给出结论"],
            "prompt_hint": "这是竞品对比任务，计划应包含：识别对比对象 → 检索华为云与竞品资料 → 维度对比 → 结论建议",
        },
        "knowledge_q": {
            "default": ["解析查询的产品与关注点", "检索知识库产品资料", "结构化呈现产品图谱/架构"],
            "prompt_hint": "这是产品知识查询任务，计划应包含：解析查询意图 → 检索知识库 → 结构化呈现",
        },
        "file_ops": {
            "default": ["确认目标文件是否存在", "读取文件内容", "基于内容回答/总结"],
            "prompt_hint": "这是文件操作任务，计划应包含：定位文件 → 读取内容 → 基于内容回答",
        },
    }

    # P1-1：plan 步 ↔ 工具的归属映射（驱动 Plan 面板实时点亮）。
    # 每个意图对应一个「步骤列表」，每个元素是该步要求调用的工具集合（顺序即 plan 展示顺序）。
    # 列表最后一项为空集合，代表「综合/生成」步（不绑定具体工具，由 final_answer 点亮）。
    # plan 步数严格等于该映射表长度，保证 plan_index 与工具调用一一对应。
    PLAN_STEP_TOOL_MAP = {
        "solution":     [["analyze_demand"], ["search_kb", "search_competitor"], []],
        "competitor":   [["search_competitor", "search_kb"], []],
        "knowledge_q":  [["search_kb"], []],
        "file_ops":     [["list_dir"], ["read_customer_file"], []],
    }

    def _tool_to_plan_index(self, tool_name: str, intent: str) -> int:
        """P1-1：根据工具名计算它归属的 plan 步索引（0-based）。

        取「映射表该意图里、要求工具包含本 tool、且状态≠done 的第一条」索引；
        无归属（如 web_search 等附加工具、或已全部 done）返回 -1（前端不点亮特定步）。
        """
        mp = self.PLAN_STEP_TOOL_MAP.get(intent)
        if not mp:
            return -1
        for i, tools_in_step in enumerate(mp):
            if tool_name in tools_in_step and (i >= len(self._plan_status) or self._plan_status[i] != "done"):
                return i
        return -1

    def _mark_plan_status(self, plan_index: int, status: str) -> None:
        """P1-1：把 plan 指定步置为某状态（越界忽略）。"""
        if 0 <= plan_index < len(self._plan_status):
            self._plan_status[plan_index] = status

    async def _generate_plan(self, user_input: str, intent: str, n_steps: int = None) -> list:
        """执行前生成执行计划并推送 plan 事件（供前端 Plan 面板渲染）。

        - 用 LLM 生成（结构化 JSON 数组），失败时回退到该意图的默认计划（保证前端永远有面板）。
        - n_steps 给定时（P1-1），要求生成恰好 n_steps 步，使 plan 步数与 PLAN_STEP_TOOL_MAP
          对齐，保证 plan_index 与工具调用一一对应、实时点亮精准。
        - 计划只描述"接下来要做什么"，不包含敏感细节。
        """
        meta = self._PLAN_INTENT_META.get(intent)
        default_plan = meta["default"] if meta else ["分析需求", "检索资料", "生成回答"]
        plan = []
        try:
            from app.models.llm import get_llm_response
            hint = meta["prompt_hint"] if meta else ""
            if n_steps:
                step_req = f"恰好 {n_steps} 步"
                step_limit = f"必须正好 {n_steps} 个元素"
            else:
                step_req = "3-6 步"
                step_limit = "3 到 6 个元素"
            prompt = (
                f"你是任务规划器。请为下面的用户需求生成{step_req}简明执行计划（每步 ≤14 字，动作开头，"
                f"如「检索华为云方案资料」）。只输出 JSON 数组，{step_limit}，如 [\"步骤1\", \"步骤2\"]，不要其他文字。\n"
                f"任务类型提示：{hint}\n"
                f"用户需求：{user_input}\n"
                "输出："
            )
            raw = await get_llm_response(prompt, model=MATCH_LLM_MODEL)
            j = raw.find("[")
            k = raw.rfind("]") + 1
            if j >= 0 and k > j:
                parsed = json.loads(raw[j:k])
                if isinstance(parsed, list) and 1 <= len(parsed) <= 8:
                    plan = [str(x).strip()[:20] for x in parsed if str(x).strip()]
            if not plan:
                plan = list(default_plan)
        except Exception as e:
            logger.warning(f"[Plan] LLM 生成计划失败，使用默认计划: {e}")
            plan = list(default_plan)
        # 对齐到目标步数 n_steps（保证 plan_index 与工具映射一一对应）
        if n_steps:
            if len(plan) > n_steps:
                plan = plan[:n_steps]
            elif len(plan) < n_steps:
                base = list(default_plan)
                while len(plan) < n_steps and len(base) >= n_steps:
                    plan.append(base[len(plan)])
                while len(plan) < n_steps:
                    plan.append(default_plan[len(plan) % len(default_plan)])
        else:
            if len(plan) < 3:
                plan = list(default_plan)
            plan = plan[:6]
        return plan

    async def _emit_plan(self, event_callback, user_input: str, intent: str) -> None:
        """生成计划并推送 plan 事件；同时把计划存到 self._plan 供步骤映射。

        P1-1：把 plan 步数对齐到该意图的 PLAN_STEP_TOOL_MAP 长度，并初始化 _plan_status 全 pending，
        使后续 tool_start/tool_end/final 事件能精准点亮对应步。
        """
        n_steps = len(self.PLAN_STEP_TOOL_MAP.get(intent, [])) or None
        self._plan = await self._generate_plan(user_input, intent, n_steps=n_steps)
        self._plan_status = ["pending"] * len(self._plan)
        self._plan_original_input = user_input  # P2-D5：记录原始需求，供 Plan 单步重跑时重新汇总
        await self._emit(event_callback, {
            "type": "plan",
            "steps": self._plan,
            "intent": intent,
            "plan_status": list(self._plan_status),
        })

    # ───────────────────────── P2-1-A：真·两阶段执行（plan 驱动） ─────────────────────────

    # 定价意图关键词（用于「强制成本测算步」守卫）：命中且整轮未调 cost_calc 时补专用步，
    # 确保售前 TCO 测算真正走 MCP 工具而非被模型在编排中漏掉。
    _PRICING_RE = re.compile(
        r"成本|TCO|报价|预算|月租|月费|总价|多少钱|测算|费用", re.IGNORECASE
    )

    # 客户建档意图关键词（用于「强制CRM步」守卫）：命中且整轮未调 client_add 时补专用步，
    # 修复根因 —— 模型在编排中漏掉写入工具、反而在终稿里幻觉"已为你保存客户"，
    # 导致经典模式客户管理看不到（客户根本没落库）。harness 确定性补步，走权限闸门 ask。
    # 动词与「客户」间允许 0-8 字 filler（"保存这个客户"）；误命中无害：
    # 抽取步先于权限弹窗执行，抽不出客户名只会如实要求用户补充，不会误写库。
    _CLIENT_RE = re.compile(
        r"存成客户|存为.{0,8}客户|存入.{0,8}客户|记录.{0,8}客户|添加.{0,8}客户|"
        r"保存.{0,8}客户|新建.{0,8}客户|录入.{0,8}客户|登记.{0,8}客户|"
        r"客户建档|建档|录入客户库|存入客户库",
        re.IGNORECASE,
    )

    # 客户更新意图关键词：与建档正交，命中且整轮未调 client_update 时补专用步，
    # 修复"给X加个行业/更新客户阶段"走 general 直答幻觉"已更新"的同类缺口。
    _CLIENT_UPDATE_RE = re.compile(
        r"(更新|修改|补充|完善).{0,6}(客户|档案|资料)"
        r"|((更新|修改|补充|完善|加上|加个?|添加|录入).{0,4}(行业|阶段|备注|标签|联系人|电话|邮箱|预算|痛点|决策链|规模|区域))"
        r"|((行业|阶段|预算|备注|标签|联系人).{0,4}(改成|改为|更新为|变更为|设置?为))",
        re.IGNORECASE,
    )

    # 客户删除意图：client_delete 是不可逆写操作，走 ask 弹窗人工确认。
    _CLIENT_DELETE_RE = re.compile(
        r"(删除|删掉|删了|去掉|移除|清除).{0,8}客户|客户.{0,6}(删除|删掉)",
        re.IGNORECASE,
    )

    # 客户/历史方案查询意图（只读）：命中走确定性查询（client_list / match_history），
    # 修复 general 直答**编造客户数据**——比写入幻觉更危险（假档案会误导售前决策）。
    _CLIENT_QUERY_RE = re.compile(
        r"查.{0,8}客户|客户(列表|清单|名录|名单|档案|资料|信息)|我的客户|有哪些客户"
        r"|多少.{0,6}客户|几[个户]客户|多少个客户|客户数"
        r"|(查一?下|看看|看下|查看|调出?|打开).{0,12}(档案|客户资料|客户详情)"
        r"|(合作过|服务过|做过|生成过).{0,10}方案|方案(历史|记录)|历史方案|匹配历史|给哪些客户"
        r"|(合作过|服务过|支持过).{0,8}客户|(客户|名单).{0,6}(合作|服务)过"
        r"|(客户|他|她|它).{0,6}的(阶段|预算|行业|联系人|痛点|决策链|档案|资料)"
        r"|(什么|哪个|目前|现在|处于).{0,4}(商机)?阶段",
        re.IGNORECASE,
    )

    # 知识库统计意图（只读真数据）：general 直答会编文档数，命中直接调 get_stats()。
    _KB_STATS_RE = re.compile(
        r"知识库.{0,12}(多少|几[个篇条]|统计|规模|概况|情况|有哪些|覆盖|行业)"
        r"|(文档|资料|语料|方案文档|竞品资料).{0,8}(多少|几[个篇条])"
        r"|(多少|几[个篇条]).{0,6}(篇|个)?(文档|资料|方案|竞品)",
        re.IGNORECASE,
    )

    # 文档/PPT 成文意图（general 分支）：泛化为"动词 + 格式名词"——
    # 实测教训：模型自己引导的指令（"把XX整理成PPT并导出"）必须能命中，
    # 否则用户照做却掉回闲聊，比不引导更伤信任。tests 直接引用本类属性防副本漂移。
    _DOC_INTENT_RE = re.compile(
        r"整理[^。]{0,8}(?:ppt|pptx|word|pdf|文档|报告|文章|文件)"
        r"|(?:转|换|做|输出|生成|导)成?\s*(?:ppt|pptx|word|pdf)"
        r"|写成?.{0,2}(文章|文件)|整篇.{0,2}(文档|文件)"
        r"|完整.{0,4}(文档|文章|文件)|生成.{0,6}(文档|报告|文章)"
        r"|出一份.{0,8}(文档|报告|文章|文件)|导出成?\s?(word|pdf|ppt|文档|报告)"
        r"|并导出|(?:把|将)[^。]{0,12}导出\s*$"
        r"|(?<!会)(?:做|来|要|出|生成|转成|换成|需要)\s*(?:个|一份?)?\s*(?:ppt|pptx|word|pdf)"
        r"|ppt\s*(?:可以|文件|稿|版本|格式)"
        # 边界审计补（2026-09-07）：裸格式词应答（"word吧"/"pdf"，澄清问答的典型回法）
        r"|^\s*(?:ppt|pptx|word|pdf)\s*[吧呗啊呀。.！!，,？?]*$"
        # 英文成文请求（"help me make a PPT"）
        r"|\b(?:make|create|generate|convert|export)\b[^。]{0,16}\b(?:ppt|pptx|word|pdf|document|report)s?\b",
        re.IGNORECASE,
    )

    # 短确认应答（"好/可以/行/嗯/生成吧"）：仅当会话里刚有可成文素材
    # （material_pending 标记，见 general 分支）时升级为成文意图，防陈旧误触发。
    _CONFIRM_RE = re.compile(
        r"^(?:好(?:的|呀|啊|吧)?|可以|行(?:吧|的)?|嗯+|要|生成吧|导出吧|转吧|就这么办|没问题|ok|okay)"
        r"[吧呀啊嘛呢，,！!。\s]{0,4}$",
        re.IGNORECASE,
    )

    @classmethod
    def _crm_intent_hit(cls, text: str) -> bool:
        """建档/更新/删除意图是否命中（写入类，general 分支与两阶段强制步共用）。"""
        t = text or ""
        return bool(
            cls._CLIENT_RE.search(t)
            or cls._CLIENT_UPDATE_RE.search(t)
            or cls._CLIENT_DELETE_RE.search(t)
        )

    @classmethod
    def _crm_query_hit(cls, text: str) -> bool:
        """客户/历史方案查询意图是否命中（只读类，仅 general 分支用）。"""
        return bool(cls._CLIENT_QUERY_RE.search(text or ""))

    @classmethod
    def _kb_stats_hit(cls, text: str) -> bool:
        """知识库统计意图是否命中（只读类，仅 general 分支用）。"""
        return bool(cls._KB_STATS_RE.search(text or ""))

    # 每步子循环内最多允许的 LLM 迭代次数（防单步无限循环）
    _STEP_MAX_ITER = 3

    async def _plan_and_execute(
        self, user_input: str, intent: str,
        event_callback, session_id: str, tool_calls_log: list,
    ) -> Optional[Dict[str, Any]]:
        """P2-1-A：按 plan 逐步骤执行（每步限工具集），最后汇总生成终稿。

        返回：
          Dict → 两阶段执行完成的结果（与 run() 的 _make_result 同构）；
          None → 需降级（第一步触发 Clarify，或执行异常）→ 由 run() 落到旧 ReAct 循环。
        """
        plan = self._plan or []
        if not plan:
            return None
        try:
            step_outputs = []
            for idx, step in enumerate(plan):
                # P2-1-B：多智能体角色（solution/competitor 启用；knowledge_q/file_ops 保持单角色）
                role = None
                if self._multi_agent_enabled and self._intent in ("solution", "competitor"):
                    from app.agent.agents import get_role, role_for_step
                    role = get_role(idx)
                    await self._emit(event_callback, {
                        "type": "agent_phase",
                        "phase": role["phase"],
                        "label": role["name"],
                        "step_index": idx,
                    })
                # 本步允许的工具：多智能体用角色工具子集；否则用映射表（末步空=综合生成）
                if role:
                    toolset = list(role["tools"])
                else:
                    toolset = list(self.PLAN_STEP_TOOL_MAP.get(intent, [])[idx]) \
                        if idx < len(self.PLAN_STEP_TOOL_MAP.get(intent, [])) else []
                # P2-3：远端 MCP 工具作为动作步的「逃生舱」，LLM 可随时按需调用。
                # 边界审计（2026-09-08 线上 OBS 实测根因）：仅动作步追加——此前无脑追加到
                # 每一步，导致综合生成步（映射表末步为空）也只剩成本/CRM 工具，知识问答类
                # 末步"检索知识库并呈现定义"无检索工具可用，模型被迫乱调 CRM 工具触发
                # 权限弹窗，无人值守时逐个 60s 超时拒绝直至整体超时。
                if toolset and self._remote_tool_names:
                    toolset = toolset + self._remote_tool_names
                # P2-Skills：角色提示词追加行业技能包块（仅提示词注入，不动工具集；无包/异常为空串）
                role_prompt = role["prompt"] if role else None
                if role_prompt and getattr(self, "_active_pack", None):
                    try:
                        from app.agent.skill_packs import pack_prompt_block
                        role_prompt += pack_prompt_block(self._active_pack, role_for_step(idx))
                    except Exception as _pe:
                        self._log("warn", f"技能包角色块注入失败（忽略）: {_pe}")
                # P1-B：能力包（动作维度）角色块追加——与行业包正交共存，顺序排在行业包之后
                if role_prompt and getattr(self, "_active_capability", None):
                    try:
                        from app.agent.skill_packs import pack_prompt_block
                        role_prompt += pack_prompt_block(self._active_capability, role_for_step(idx))
                    except Exception as _ce:
                        self._log("warn", f"能力包角色块注入失败（忽略）: {_ce}")
                obs = await self._execute_step(idx, step, toolset, event_callback, session_id, tool_calls_log,
                                               role_prompt=role_prompt)
                if obs is None:
                    return None  # 第一步要求澄清 → 降级
                self._step_results[idx] = obs
                step_outputs.append(obs)
                # 点亮本步 done
                self._mark_plan_status(idx, "done")
                await self._emit(event_callback, {
                    "type": "step_done",
                    "step_index": idx,
                    "summary": "本步完成",
                })

            # ── 强制成本测算步（P0 修复 cost_calc 不被调用）──
            # 模型在多步编排中稳定漏掉定价工具（只调 reference_list、不链 cost_calc，
            # 即便工具集仅限成本工具也停住）。改为由 harness 确定性驱动：
            # 取 SKU 目录 → 结构化抽取 items → 直接调用 cost_calc，确保「项目能力 → MCP → Agent 可调用」闭环。
            if self._remote_tool_names and self._PRICING_RE.search(self._plan_original_input or user_input or ""):
                if not any(t.get("tool") == "mcp__cost__cost_calc" for t in tool_calls_log):
                    self._log("system", "[强制成本步] 定价意图命中且 cost_calc 未调用，确定性补专用成本步")
                    forced_obs = await self._force_cost_step(event_callback, session_id, tool_calls_log, user_input)
                    if forced_obs:
                        step_outputs.append(forced_obs)

            # ── 强制CRM步（修复 client_add/client_update 不被调用 → 模型幻觉"已保存/已更新"）──
            # 用户明确要建档/更新客户，但整轮没调对应写入工具时，由 harness 确定性补步：
            # LLM 抽 op+字段 → 直接调 mcp__crm__client_add / client_update
            # （穿过权限闸门 ask，需用户在弹窗点"允许执行"才落库；拒绝/超时则不写，杜绝脏档案）。
            if self._remote_tool_names and self._crm_intent_hit(self._plan_original_input or user_input or ""):
                if not any(t.get("tool") in ("mcp__crm__client_add", "mcp__crm__client_update") for t in tool_calls_log):
                    self._log("system", "[强制CRM步] 客户建档/更新意图命中且写入工具未调用，确定性补CRM步")
                    forced_crm = await self._force_crm_step(event_callback, session_id, tool_calls_log, user_input)
                    if forced_crm:
                        step_outputs.append(forced_crm)

            # P3-1 真反思-重规划：若任一执行步含 Error:（失败步），且开关开启、预算未超，
            # 则读失败步 → planner 产修订计划 → 重跑失败步 → 重新汇总；否则走常规汇总。
            failed = [i for i in range(len(plan)) if "Error:" in (self._step_results.get(i, "") or "")]
            replan_enabled = (AGENT_REFLEXION_REPLAN or "1").strip() == "1"
            if failed and replan_enabled and self._replan_count < REFLEXION_MAX_REPLANS:
                replanned = await self._reflexion_replan(event_callback, session_id, tool_calls_log)
                if replanned is not None:
                    final = replanned
                else:
                    final = await self._synthesize_final(user_input, plan, step_outputs, event_callback)
            else:
                final = await self._synthesize_final(user_input, plan, step_outputs, event_callback)
            # P3-3 自检 Gate：终稿交付前过质量闸门（不过则二次合成），在增强管线前完成，
            # 保证前端流式内容即闸门后的终稿。
            final, _ = await self._self_check_gate(final, user_input, event_callback, tool_calls_log)
            final = await self._finalize_answer(user_input, final, tool_calls_log, event_callback=event_callback)
            self._last_draft = final
            self.memory.add_agent_response(session_id, final)

            # 点亮最后一步（综合生成步）并收尾
            last_idx = len(plan) - 1
            self._mark_plan_status(last_idx, "done")
            await self._emit(event_callback, {
                "type": "final",
                "step": self._step_count,
                "elapsed": round(time.time() - self._start_time, 2),
                "plan_index": last_idx,
            })
            # P2-2：成功完成方案 → 存入情景记忆
            self._maybe_save_episode(session_id, user_input, final)
            return self._make_result(final, tool_calls_log, success=True)
        except Exception as e:
            self._log("error", f"两阶段执行异常，降级: {e}")
            return None

    async def _execute_step(
        self, idx: int, step: str, toolset: list,
        event_callback, session_id: str, tool_calls_log: list,
        role_prompt: str = None,
    ) -> Optional[str]:
        """P2-1-A：执行 plan 的单个步骤（子循环，仅允许 toolset 内工具）。

        P2-1-B：role_prompt 传入时注入角色提示（多智能体），工具集由调用方按角色传入。

        返回：
          str   → 本步执行结果摘要（供汇总消费）；
          None  → 本步要求 Clarify（仅 idx==0 允许）→ 整体降级到旧循环。
        """
        # 综合生成步：无工具，交给 _synthesize_final（多智能体末步已由角色提供工具集，不走此分支）
        if not toolset:
            self._log("system", f"[两阶段] 步{idx+1} 综合生成步（无工具）")
            return f"（第 {idx + 1} 步：综合生成阶段，由汇总完成）"

        tools_desc = "、".join(toolset)
        role_block = f"\n{role_prompt}\n" if role_prompt else ""
        step_prompt = (
            f"你是华为云售前方案助手，正在执行整体计划的第 {idx + 1} 步。{role_block}\n"
            f"【本步目标】{step}\n"
            f"【本步可用工具】{tools_desc}（只能使用这些工具，不要调用其它工具）\n\n"
            f"请调用工具完成本步目标。每轮输出严格按以下格式：\n"
            f"Thought: [分析]\n"
            f"Action: [工具名]\n"
            f"Action Input: [JSON 参数]\n\n"
            f"观察工具返回结果后：\n"
            f"- 若本步目标已达成 → 输出 STEP_DONE: [一句话总结本步结果]\n"
            f"- 若信息仍不足 → 继续调用工具（仅限本步工具）\n"
            f"- 若前置信息严重不足需要向用户提问（仅第 1 步允许）→ 输出 Clarify: [问题]\n"
        )

        step_iter = 0
        obs_lines: list = []
        while step_iter < self._STEP_MAX_ITER:
            if time.time() - self._start_time > self.timeout:
                self._log("system", f"[两阶段] 步{idx+1} 超时，截断")
                break
            step_iter += 1
            self._step_count += 1
            await self._emit(event_callback, {
                "type": "step", "step": self._step_count, "max_steps": self.max_steps,
            })

            llm_response = await self._call_llm(step_prompt)
            self._log("llm", f"[两阶段 步{idx+1}] {llm_response[:300]}")

            # 显式 STEP_DONE
            if re.search(r'STEP_DONE\s*[*]*\s*[:：]', llm_response, re.IGNORECASE):
                done = re.split(r'STEP_DONE\s*[*]*\s*[:：]', llm_response, 1, re.IGNORECASE)[-1].strip()[:200]
                obs_lines.append(f"（第 {idx + 1} 步完成：{done}）")
                break

            parse_result = self._parse_react_output(llm_response)

            if parse_result["type"] == "clarify":
                if idx == 0:
                    self._log("system", "[两阶段] 第 1 步要求澄清 → 降级到旧循环处理 clarify")
                    return None
                step_prompt += "\n（不允许向用户提问，请基于已有信息继续推进本步。）"
                continue

            if parse_result["type"] == "final_answer":
                # 本步内提前收尾（信息已足够）
                obs_lines.append(f"（第 {idx + 1} 步完成：{parse_result['content'][:200]}）")
                break

            if parse_result["type"] == "action":
                # P3-2 并行子体：若单轮产出多个「只读检索」Action，且开关开启、落在步级工具集内、
                # 数量不过 MAX_PARALLEL，则用 asyncio.gather 并发执行（权限闸门各自阻塞、自然等齐）。
                parallel_actions = self._parse_react_actions(llm_response)
                readonly_set = {"search_kb", "search_competitor", "web_search", "web_extract"}
                if (parallel_actions
                        and (AGENT_PARALLEL_TOOLS or "1").strip() == "1"
                        and len(parallel_actions) >= 2
                        and all(a["tool_name"] in readonly_set for a in parallel_actions)
                        and all(a["tool_name"] in toolset for a in parallel_actions)
                        and len(parallel_actions) <= MAX_PARALLEL):
                    thought = parse_result.get("thought", "")
                    if thought:
                        self.memory.add_thought(session_id, thought)
                        await self._emit(event_callback, {
                            "type": "thought", "step": self._step_count, "text": thought[:300],
                        })
                    self._log("system", f"[P3-2 并行] 步{idx + 1} 并发 {len(parallel_actions)} 个只读工具")
                    obs_list = await asyncio.gather(*[
                        self._exec_one_action(idx, a["tool_name"], a["tool_input"], event_callback, session_id, tool_calls_log)
                        for a in parallel_actions
                    ])
                    for ob in obs_list:
                        obs_lines.append(ob[:250])
                    # 并行下不注入软反思（失败由 _plan_and_execute 外层重规划处理）；继续等 STEP_DONE
                    step_prompt += (
                        f"\n\n{_trunc(llm_response, 1200)}\n\n"
                        + "\n\n".join(f"Observation: {_trunc(ob, 2500)}" for ob in obs_list)
                        + "\n\n请继续（若本步目标已达成，请输出 STEP_DONE: [总结]）。"
                    )
                    continue
                # 顺序路径（单 action，或含非只读工具 / 超上限 / 不在步级工具集 → 兼容旧行为）
                tool_name = parse_result["tool_name"]
                tool_input = parse_result["tool_input"]
                if tool_name not in toolset:
                    hint = f"（本步不允许工具 {tool_name}，仅可使用：{tools_desc}）"
                    obs_lines.append(hint)
                    step_prompt += "\n" + hint
                    continue
                self._mark_plan_status(idx, "running")
                await self._emit(event_callback, {
                    "type": "tool_start", "step": self._step_count,
                    "tool": tool_name, "plan_index": idx,
                })
                thought = parse_result.get("thought", "")
                if thought:
                    self.memory.add_thought(session_id, thought)
                    await self._emit(event_callback, {
                        "type": "thought", "step": self._step_count, "text": thought[:300],
                    })
                self.memory.add_action(session_id, tool_name, str(tool_input))
                observation = await self._execute_tool(tool_name, tool_input, event_callback)
                self.memory.add_observation(session_id, observation)
                tool_calls_log.append({
                    "step": self._step_count, "tool": tool_name,
                    "input": tool_input, "result": observation,
                })
                # 连续失败计数 + 反思（P1-3 复用）
                if "Error:" in observation:
                    self._consecutive_tool_failures += 1
                else:
                    self._consecutive_tool_failures = 0
                self._record_trajectory(thought, tool_name, observation)
                summary = self._summarize_tool_result(tool_name, observation)
                await self._emit(event_callback, {
                    "type": "tool_end", "step": self._step_count,
                    "tool": tool_name, "summary": summary, "plan_index": idx,
                })
                if self._consecutive_tool_failures >= 2 and not getattr(self, "_reflexion_injected", False):
                    reflect = await self._reflexion_retry(event_callback)
                    if reflect:
                        self._consecutive_tool_failures = 0
                        self._reflexion_injected = True
                        step_prompt += f"\n\n【反思与调整建议】{reflect}\n请据此调整策略，不要重复同样错误。"
                obs_lines.append(observation[:250])
                step_prompt += (
                    f"\n\n{_trunc(llm_response, 1200)}\n\n"
                    f"Observation: {_trunc(observation, 2500)}\n\n"
                    f"请继续（若本步目标已达成，请输出 STEP_DONE: [总结]）。"
                )
            else:
                # 解析失败：引导重试
                step_prompt += (
                    f"\n\n{_trunc(llm_response, 800)}\n"
                    f"（你的输出格式不正确。请严格按格式输出：\n"
                    f"Thought: [分析]\nAction: [工具名]\nAction Input: [JSON参数]\n"
                    f"或者本步完成时输出：STEP_DONE: [总结]）"
                )

        if not obs_lines:
            obs_lines.append("（本步未产生工具结果）")
        return "\n".join(obs_lines)[:1500]

    async def _synthesize_final(
        self, user_input: str, plan: list, step_outputs: list, event_callback=None,
    ) -> str:
        """P2-1-A：汇总各步结果，调 LLM 生成终稿（随后走统一增强管线）。"""
        _pairs = list(zip(plan, step_outputs)) + [
            ("补充执行结果", out) for out in step_outputs[len(plan):]
        ]
        steps_txt = "\n".join(
            f"- 第{i + 1}步（{step}）：\n{_trunc(out, 600)}" for i, (step, out) in enumerate(_pairs)
        ) or "（无执行结果）"
        # P2-Skills：终稿追加行业口径块（话术/价值主张/playbook 要点；无包为空串）
        pack_block = ""
        if getattr(self, "_active_pack", None):
            try:
                from app.agent.skill_packs import pack_synthesize_block
                pack_block = pack_synthesize_block(self._active_pack)
            except Exception as _pe:
                self._log("warn", f"技能包终稿块注入失败（忽略）: {_pe}")
        # P1-B：能力包终稿块追加（动作维度口径 + playbook 要点），排在行业包之后
        if getattr(self, "_active_capability", None):
            try:
                from app.agent.skill_packs import pack_synthesize_block
                pack_block += pack_synthesize_block(self._active_capability)
            except Exception as _ce:
                self._log("warn", f"能力包终稿块注入失败（忽略）: {_ce}")
        prompt = (
            "你是华为云售前方案撰写官。你已按计划执行了各步骤，请基于各步收集到的信息，"
            "为用户撰写完整、可落地的最终方案。\n\n"
            f"【用户需求】{user_input}\n\n"
            f"【执行计划与各步结果】\n{steps_txt}\n"
            f"{pack_block}\n\n"
            "请直接输出：\n"
            "Final Answer: [完整方案]\n"
            "（方案须覆盖：客户痛点分析、华为云产品与技术方案、实施路径、价值与预期收益）"
        )
        raw = await self._call_llm(prompt)
        parse = self._parse_react_output(raw)
        if parse["type"] == "final_answer":
            return parse["content"]
        return raw

    # ───────────────────────── P2-2：长程记忆 ─────────────────────────

    def _maybe_save_episode(self, session_id: str, demand: str, answer: str) -> None:
        """方案类意图成功完成时，把 (需求, 终稿) 存入情景记忆（best-effort，不阻塞）。"""
        try:
            if not answer or len(answer) < 300:
                return
            if self._intent not in ("solution", "competitor"):
                return
            uid = self._user_id if isinstance(self._user_id, int) and self._user_id > 0 else None
            if not uid:
                return
            from app.agent.memory_profiles import save_episode
            # 后台执行编码+落库，避免拖慢响应
            loop = asyncio.get_running_loop()
            loop.create_task(asyncio.to_thread(
                save_episode, uid, session_id, demand[:200], answer[:400],
                getattr(self, "_client_id", None),
            ))
        except Exception as e:
            self._log("warn", f"保存情景记忆失败（忽略）: {e}")

    # ─────────────────── 过短需求澄清拦截（P2 修复） ───────────────────
    def _need_clarify(self, user_input: str, industries: list) -> bool:
        """方案/竞品意图但信息严重不足时返回 True，触发澄清追问而非凭空生成方案。

        判定：已有明确行业信息 → 不澄清；否则字数过少或缺乏场景/规模信号 → 澄清。
        """
        text = (user_input or "").strip()
        if not text:
            return True
        if industries:
            return False
        if len(text) < 12:
            return True
        signals = (
            "行业", "企业", "工厂", "医院", "学校", "政府", "园区", "银行",
            "农场", "平台", "系统", "设备", "场景", "项目", "业务", "客户",
            "规模", "上云", "建", "想", "需求", "台", "家", "亩", "例", "万", "亿",
        )
        return not any(k in text for k in signals)

    def _build_clarify_questions(self, user_input: str) -> list:
        """针对过短需求生成澄清问题（行业 / 场景 / 规模 / 目标）。"""
        return [
            "您所在的行业或业务领域是？（如制造、医疗、政务、金融、零售等）",
            "想解决的核心业务场景或痛点是什么？",
            "企业大致规模或覆盖范围是？（如设备数量、门店数、用户量、地域）",
            "期望达成的目标或优先级是？（降本 / 增效 / 合规 / 创新）",
        ]

    async def _rerun_plan_step(
        self, idx: int, session_id: str, event_callback=None,
    ) -> Optional[Dict[str, Any]]:
        """P2-D5：Plan 单步重跑。

        前提：本次会话已成功跑过一次两阶段执行（self._plan / _step_results 非空）。
        流程：重跑第 idx 步（复用角色/工具集，原 plan 文本）→ 用新结果覆盖 _step_results[idx]
              → 重新 _synthesize_final + _finalize_answer → 返回新终稿结果。
        失败/无历史：返回失败结果并提示先完成一次方案生成。
        """
        plan = self._plan or []
        if not plan or not self._step_results:
            return self._make_result(
                "（当前没有可重跑的方案执行记录，请先让我生成一份方案，再点击计划行上的「重跑」。）",
                [], success=False,
            )
        if not (0 <= idx < len(plan)):
            return self._make_result(f"（重跑步索引越界：{idx}，计划共 {len(plan)} 步。）", [], success=False)

        self._log("system", f"[P2-D5] 重跑 plan 第 {idx + 1} 步: {plan[idx]}")
        self._start_time = time.time()
        # 该步角色/工具集与首次执行保持一致
        role = None
        if self._multi_agent_enabled and self._intent in ("solution", "competitor"):
            from app.agent.agents import get_role
            role = get_role(idx)
            await self._emit(event_callback, {
                "type": "agent_phase", "phase": role["phase"], "label": role["name"], "step_index": idx,
            })
        toolset = list(role["tools"]) if role else list(self.PLAN_STEP_TOOL_MAP.get(self._intent, [])[idx]) \
            if idx < len(self.PLAN_STEP_TOOL_MAP.get(self._intent, [])) else []
        # P2-3：远端 MCP 工具作为动作步的「逃生舱」（综合生成步不追加，同 _plan_and_execute 修复）
        if toolset and self._remote_tool_names:
            toolset = toolset + self._remote_tool_names
        tool_calls_log: list = []
        # 重跑该步前先复位该步状态为 pending → running
        self._mark_plan_status(idx, "pending")
        await self._emit(event_callback, {
            "type": "step_done", "step_index": idx, "summary": "重跑开始",
        })
        obs = await self._execute_step(
            idx, plan[idx], toolset, event_callback, session_id, tool_calls_log,
            role_prompt=role["prompt"] if role else None,
        )
        if obs is None:
            return self._make_result("（该步要求澄清，无法在重跑模式下提问，已保留原结果。）", tool_calls_log, success=False)
        self._step_results[idx] = obs
        self._mark_plan_status(idx, "done")

        # 重新汇总（其余步沿用上次结果）
        step_outputs = [self._step_results.get(i, "") for i in range(len(plan))]
        final = await self._synthesize_final(self._plan_original_input or "", plan, step_outputs, event_callback)
        # 注意实参顺序：(answer, user_input)；此处曾误传成 (user_input文本, 终稿)，导致 critic 拿错数据评审
        final, self._quality_warn = await self._self_check_gate(final, self._plan_original_input or "", event_callback, tool_calls_log)
        final = await self._finalize_answer(self._plan_original_input or "", final, tool_calls_log, event_callback=event_callback)
        self._last_draft = final
        self.memory.add_agent_response(session_id, final)
        await self._emit(event_callback, {
            "type": "final",
            "step": self._step_count,
            "elapsed": round(time.time() - self._start_time, 2),
            "plan_index": len(plan) - 1,
        })
        return self._make_result(final, tool_calls_log, success=True)

    async def run(
        self,
        user_input: str,
        session_id: str = "default",
        extra_context: str = "",
        event_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        clarify_id: Optional[str] = None,
        answers: Optional[list] = None,
        user_id: Optional[int] = None,
        user_info: Optional[dict] = None,
        model: Optional[str] = None,
        thinking: Optional[str] = None,
        rerun_plan_index: Optional[int] = None,
        tool_permissions: Optional[dict] = None,
        disable_web_search: bool = False,
        client_id: Optional[int] = None,
        intent_text: Optional[str] = None,
        images_meta: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        运行 ReAct 循环

        参数:
            event_callback: 可选异步回调，用于 SSE 流式推送进度事件。
                事件格式: {"type": "step"|"tool_start"|"tool_end"|"thought"|"final", ...}
            rerun_plan_index: P2-D5 Plan 单步重跑索引。命中时从 _step_results 重跑该步并重新汇总终稿。

        返回:
        {
            "answer": str,          # 最终答案
            "steps": int,           # 执行步数
            "elapsed": float,       # 耗时（秒）
            "tool_calls": list,     # 工具调用记录
            "logs": list,           # 详细日志
            "success": bool,        # 是否成功
        }
        """
        self._step_count = 0
        self._start_time = time.time()
        self._logs = []
        tool_calls_log = []
        self._clarify_round = 0
        self._user_id = user_id
        # 修复：记忆注入标记必须每轮 run 重置——Agent 是进程级单例，__init__ 只执行一次，
        # 不重置会导致进程内第一次对话之后所有对话都不再注入长程记忆（P2-2 名存实亡）。
        # 设计语义是"每个对话的首轮注入一次"（对话内澄清轮不重复注入）。
        self._memory_context_injected = False
        # 客户上下文：情景记忆按 客户 隔离（save_episode/build_memory_context 共用）
        self._client_id = client_id if isinstance(client_id, int) and client_id > 0 else None
        # P1-3：反思注入标记（防重复反思死循环）+ 执行轨迹（供 reflexion 用）
        self._reflexion_injected = False
        self._last_trajectory = ""
        # 工具栏透传：用户临时切换的模型 / 思考开关（None 时走 config 默认）
        self._run_model = model or None
        self._run_thinking = thinking or None
        self._user_info = user_info or {}
        # #3 工具权限策略（allow/ask/deny）与 #6 联网搜索开关（前端工具栏透传，None 走默认）
        self._tool_permissions = tool_permissions or {}
        self._disable_web_search = bool(disable_web_search)
        # P2-Skills：行业技能包复位（单例复用防跨请求残留；仅在首轮意图路由时重新匹配）
        self._active_pack = None
        # P1-B：能力包复位（按"动作"维度挂载，与行业包正交、可同时生效）
        self._active_capability = None

        # P2-D5：Plan 单步重跑 —— 复用上一次的 plan / 各步原参数，重跑指定步并重新汇总
        if rerun_plan_index is not None:
            return await self._rerun_plan_step(rerun_plan_index, session_id, event_callback)

        if clarify_id:
            # ── 续跑模式：从澄清会话状态恢复，跳过初始化，把用户回答作为 Observation 接回 ──
            self._log("system", f"[CLARIFY_RESUME] 开始恢复 clarify_id={clarify_id}")
            state = ClarifySessionStore.get(clarify_id)
            if not state:
                self._log("error", "澄清会话不存在或已过期")
                return self._make_result(
                    "（澄清会话已过期或不存在，请重新发起匹配）", tool_calls_log,
                    success=False, expired=True, plan=[], plan_status=[],
                )
            session_id = state.get("session_id", session_id)
            user_input = state.get("user_input", user_input)
            extra_context = state.get("extra_context", "")
            self._client_context = extra_context  # B修复：续跑模式同样透传客户背景
            self._step_count = state.get("step_count", 0)
            self._start_time = time.time()
            self._clarify_round = state.get("clarify_round", 0)

            # 把用户回答拼成 Observation
            ans_lines = []
            for a in (answers or []):
                q = a.get("question", "") if isinstance(a, dict) else ""
                ans = a.get("answer", "") if isinstance(a, dict) else str(a)
                ans_lines.append(f"- {q}：{ans}")
            ans_text = "\n".join(ans_lines) or "（用户未提供补充信息）"
            saved_prompt = state.get("current_prompt", "") or ""
            original_input = state.get("user_input", "") or ""
            current_prompt = saved_prompt + f"""
Observation: 用户补充信息（第 {self._clarify_round} 轮澄清后）：
{ans_text}
"""
            # 根据轮次动态调整续跑指令——防止 LLM 拿到一个答案就急着 Final Answer
            if self._clarify_round < 2:
                input_short = len(original_input) < 20
                hint = f"（注意：用户原始输入仅{len(original_input)}字「{original_input[:30]}」，信息仍可能严重不足）" if input_short else ""
                current_prompt += f"""请继续分析。当前是第 {self._clarify_round} 轮澄清{hint}。
【重要】如果用户原始需求描述很短且你目前仅有行业信息（缺场景/规模），请继续用 Clarify 追问一轮核心业务场景或目标，不要急于输出 Final Answer。
仅当已同时具备 行业+场景/目标 时才走工具链→Final Answer。"""
            else:
                current_prompt += "请继续分析。若已收集到足够信息，请调用工具检索并输出 Final Answer。"
            self._log("system", f"ReAct 续跑（澄清轮次 {self._clarify_round}）answers={len(ans_lines)} prompt_len={len(current_prompt)}")
        else:
            # ── 首轮：清空短期记忆，记录用户输入，构建初始 Prompt ──
            self.memory.clear_short_term(session_id)
            # images_meta（2026-09-09 跨设备同步）：图片元数据随用户消息落库，
            # 另一台设备恢复历史时可显示图片徽标（路径为服务端 customer_uploads 相对路径）
            self.memory.add_user_message(session_id, user_input, images=images_meta)
            self._client_context = extra_context  # B修复：首轮注入客户背景，供最终增强管线使用
            # 联网检索预算每轮重置（2026-09-08 线上实测根因修复）：
            # reset_web_search_budget 此前定义了但从未被调用，_count 为进程级只增不清，
            # 重启后累计 3 次即所有会话永久 status="limited" 静默短路（凌晨实测全空的真实原因）。
            from app.agent.tools import reset_web_search_budget
            reset_web_search_budget()

            tools_desc = self.tools.get_tools_prompt()

            # ── 意图路由（A 方案）：首轮先识别意图，非方案类直接轻量回复，不进 ReAct/14章流水线 ──
            # intent_text（2026-09-09 E2E 实测）：意图只看用户原话——图片/附件预处理会把大段
            # 描述内容拼进 user_input（如"校徽…智慧校园…数字化"），“仔细描述一下这张图”
            # 会被行业词带进方案匹配全流程。注入内容只参与回答，不参与意图判定。
            intent = classify_intent(intent_text or user_input)
            self._intent = intent.get("intent", "solution")
            # 文档附件（2026-09-09 简历案例二次修正）：附件内容已由 agent_routes 预处理
            # 注入消息（与图片 vision 同架构），不再强制 intent=solution——"聊着天传个
            # 简历让它看看"应该走通用直答自然回答。标记仅用于：①带附件时跳过澄清表；
            # ②真方案诉求下 extra_context 仍有 read_customer_file 引导。
            _has_doc_attach = bool(extra_context and DOC_ATTACH_MARKER in extra_context)
            self._format_mode = "competitor" if self._intent == "competitor" else "solution"
            competitors = intent.get("competitors", []) or []
            self._log("system", f"[INTENT] {intent}")

            # P2-2：首轮注入长程记忆（episodic 相关历史方案 + procedural 用户画像），
            # 仅注入一次，不随澄清轮次重复追加；无记忆/异常时为空串不影响主流程。
            # 【2026-09-07 用户拍板】general/greeting/account/export 不注入——通用对话就是
            # 纯会话上下文，不带跨对话长程记忆（原位置在意图分类前，无法按意图门控）。
            if not getattr(self, "_memory_context_injected", False) and self._intent not in (
                "general", "greeting", "account", "export",
            ):
                try:
                    from app.agent.memory_profiles import build_memory_context, build_profile_context
                    uid = user_id if isinstance(user_id, int) and user_id > 0 else None
                    mem_block = build_memory_context(uid, user_input, client_id=getattr(self, "_client_id", None)) if uid else ""
                    profile_block = build_profile_context(uid) if uid else ""
                    if mem_block or profile_block:
                        extra_context = (extra_context or "") + "\n\n" + mem_block + "\n" + profile_block
                        self._client_context = extra_context
                    self._memory_context_injected = True
                except Exception as e:
                    self._log("warn", f"长程记忆注入失败（忽略）: {e}")
                    self._memory_context_injected = True

            # P2-Skills：行业技能包挂载（默认关；仅 solution/competitor；异常静默降级）。
            # 只注入提示词（三角色 + 终稿口径），不改工具集——工具集决策仍归角色/映射表。
            if self._intent in ("solution", "competitor") and (AGENT_SKILL_PACKS or "0").strip() == "1":
                try:
                    from app.agent.skill_packs import match_pack
                    _pack = match_pack(intent.get("industries") or [])
                    if _pack:
                        self._active_pack = _pack
                        await self._emit(event_callback, {
                            "type": "skill_pack",
                            "industry": _pack.get("industry", ""),
                            "version": _pack.get("version", ""),
                        })
                        self._log("system", f"[SKILL_PACK] 已挂载行业技能包: {_pack.get('industry')} (v{_pack.get('version', 'n/a')})")
                except Exception as e:
                    self._log("warn", f"行业技能包挂载失败（忽略）: {e}")

            # P1-B：能力包挂载（按"动作"维度；与行业包正交，可同时生效）。
            # 触发条件写在包内 triggers（intents/keywords），纯数据驱动、加包不改代码。
            # 这里不限制意图类型——PPT 生成是 export、竞品对比是 competitor，都可能需要能力包。
            if self._intent not in ("greeting", "account") and (AGENT_SKILL_PACKS or "0").strip() == "1":
                try:
                    from app.agent.skill_packs import match_capability
                    _cap = match_capability(self._intent, user_input)
                    if _cap:
                        self._active_capability = _cap
                        await self._emit(event_callback, {
                            "type": "skill_pack",
                            "kind": "capability",
                            "industry": _cap.get("industry", ""),
                            "version": _cap.get("version", ""),
                        })
                        self._log("system", f"[SKILL_PACK] 已挂载能力包: {_cap.get('industry')} (v{_cap.get('version', 'n/a')})")
                except Exception as _ce:
                    self._log("warn", f"能力包挂载失败（忽略）: {_ce}")

            # ── CRM 操作短路（E2E T4 实测缺口）──
            # 行业词会把"给X加个行业，制造业"这类纯客户档案操作判成 solution，
            # 绕进两阶段生成完整方案（答非所问）。solution/competitor 意图但消息
            # 命中 CRM 写入/查询/KB统计 且无明确方案制作动词时，短路走拦截链；
            # 含"做一份/写一份"等组合诉求仍走两阶段（由强制步兜底写入）。
            if self._intent in ("solution", "competitor"):
                _s = intent_text or user_input or ""   # 拦截判定用用户原话（2026-09-09，同意图分类口径）
                if (self._crm_intent_hit(_s) or self._crm_query_hit(_s) or self._kb_stats_hit(_s)) \
                        and not self._SOLUTION_VERB_RE.search(_s):
                    intercepted = await self._maybe_crm_intercept(
                        user_input, session_id, event_callback, tool_calls_log, intent_text=intent_text
                    )
                    if intercepted is not None:
                        self._log("system", "[CRM短路] 纯客户档案操作，跳过两阶段方案生成")
                        return intercepted

            # P2 修复：方案/竞品意图但需求过短、缺行业/场景 → 直接澄清，避免凭空生成方案
            # 附件例外（2026-09-09 简历案例实测）：带文档附件时需求信息往往就在附件里，
            # 弹澄清表单等于让用户把附件内容再敲一遍——跳过澄清，让 Agent 先读附件再答。
            if self._intent in ("solution", "competitor") and not _has_doc_attach and self._need_clarify(
                user_input, intent.get("industries") or []
            ) and not (self._intent == "competitor" and (intent.get("competitors") or [])):
                questions = self._build_clarify_questions(user_input)
                new_clarify_id = str(uuid.uuid4())
                ClarifySessionStore.put(new_clarify_id, {
                    "session_id": session_id,
                    "user_input": user_input,
                    "extra_context": extra_context,
                    "current_prompt": "",
                    "step_count": 0,
                    "clarify_round": 0,
                })
                await self._emit(event_callback, {
                    "type": "clarify",
                    "clarify_id": new_clarify_id,
                    "session_id": session_id,
                    "questions": questions,
                })
                self._log("system", f"[CLARIFY_PRECHECK] 需求过短，发起澄清（{new_clarify_id}）")
                return self._make_result(
                    "", tool_calls_log, success=False,
                    paused=True, clarify_id=new_clarify_id, questions=questions,
                    plan=[], plan_status=[],
                )

            if self._intent == "account":
                # 账户：从后端真实取数（成就/我的方案/收藏/账户信息），绝不套 14 章方案模板
                await self._emit(event_callback, {
                    "type": "thought",
                    "step": 1,
                    "text": "识别意图：账户/成就查询，从后端读取当前账户真实数据",
                })
                light = await self._handle_account_query(user_input)
                self.memory.add_agent_response(session_id, light)
                await self._emit(event_callback, {
                    "type": "final",
                    "step": 1,
                    "elapsed": round(time.time() - self._start_time, 2),
                })
                return self._make_result(light, [], success=True, plan=[], plan_status=[], format_mode="general")

            if self._intent == "greeting":
                # 纯礼节性问候/致谢/再见：极短固定模板
                await self._emit(event_callback, {
                    "type": "thought",
                    "step": 1,
                    "text": "识别意图：纯礼节性问候/致谢，无需检索方案，极短回复",
                })
                light = self._generate_light_reply("greeting", user_input)
                self.memory.add_agent_response(session_id, light)
                await self._emit(event_callback, {
                    "type": "final",
                    "step": 1,
                    "elapsed": round(time.time() - self._start_time, 2),
                })
                return self._make_result(light, [], success=True, plan=[], plan_status=[], format_mode="general")

            if self._intent == "general":
                # ── general 数据诚信拦截链（公共方法，与 solution/competitor 短路共用）──
                intercepted = await self._maybe_crm_intercept(
                    user_input, session_id, event_callback, tool_calls_log, intent_text=intent_text
                )
                if intercepted is not None:
                    return intercepted
                # ── 会话级联网记忆：跨轮记住本会话上次的检索词与结果文本。
                # 追问"整理成文档/总结一下"时直接复用，避免把整句口语喂给搜索引擎带回
                # 无关新闻污染上下文（2026-09-07 实测：'能根据最新消息给我整理一份文档吗'
                # 整句搜索会搜回 GPT-6/美伊局势等无关结果）──
                web_ctx_all = getattr(self, "_web_sessions", None)
                if web_ctx_all is None:
                    web_ctx_all = self._web_sessions = {}
                if len(web_ctx_all) > 50:  # 防长期运行膨胀
                    web_ctx_all.pop(next(iter(web_ctx_all)))
                web_ctx = web_ctx_all.get(session_id) or {}
                # 通用问答（算数/常识/自我介绍/"你能做什么"等）：调 LLM 直答，
                # 不套方案模板；可融合对话历史，让多轮追问能用上上下文。
                await self._emit(event_callback, {
                    "type": "thought",
                    "step": 1,
                    "text": "识别意图：通用问答（非方案/非竞品/非账户/非纯礼节），调 LLM 直接回答",
                })
                # ── 文档成文意图：先只做标记。成文动作统一放在"搜索/复用"之后——
                # 这样即使服务重启清空了会话级联网记忆，用户首轮直接说"把XX最新动态整理成文档"
                # 也能当场检索并成文，而不是掉回闲聊反问（2026-09-07 二次实测反馈）。
                # 正则提为类属性 _DOC_INTENT_RE：tests/test_intent_coverage.py 直接引用，
                # 杜绝测试副本漂移（2026-09-07 四次实测迭代，覆盖"整理成PPT并导出"类）──
                _doc_flag = bool(self._DOC_INTENT_RE.search(user_input))
                # ── 短确认续接（2026-09-07 边界审计）：模型答完素材类内容后用户回
                # "好/可以/生成吧"这类短确认，不应掉回闲聊制造空头承诺。仅当会话带
                # material_pending 标记（上一轮刚检索/复用过素材）或已有成稿草稿时
                # 升级为成文意图；本轮是实质性新消息（非短确认且>4字）则清除标记，
                # 防止陈旧素材在数轮之后被"好"误触发。
                _is_confirm = bool(self._CONFIRM_RE.match((user_input or "").strip()))
                _gctx = web_ctx_all.get(session_id) or {}
                if not _is_confirm and len((user_input or "").strip()) > 4:
                    _gctx.pop("material_pending", None)
                if not _doc_flag and _is_confirm and (
                    _gctx.get("material_pending") or web_ctx.get("draft")
                ):
                    _doc_flag = True
                # 联网补齐（2026-09-07）：general 直答默认无工具，用户明确要搜索/实时信息
                # 且联网开关开启时，先真搜一次再把结果喂给直答——杜绝"口头答应搜索"的假动作
                web_results_text = ""
                _q_probe = re.sub(r"^(帮我|请)?(联网|搜索|搜一下|查一下)+", "", user_input).strip()
                _need_search = not (
                    re.search(r"整理|总结|文档|摘要|成文", _q_probe) and web_ctx.get("results_text")
                )
                # 已有现成成稿且本轮没给新主题/新检索指令（如"那ppt可以吗"）：直接复用成稿转格式，不瞎搜
                _skip_search_for_draft = bool(
                    _doc_flag and web_ctx.get("draft")
                    and not re.search(r"搜索|联网|新闻|最新|实时|今天|现在|根据|关于", user_input)
                )
                if not self._disable_web_search and _need_search and not _skip_search_for_draft and (
                    _doc_flag or re.search(r"搜索|联网|搜一下|查一下|查询|搜搜|新闻|最新|实时|今天|现在", user_input)
                ):
                    try:
                        from app.agent.tools import _tool_web_search
                        import json as _json
                        # 检索词构造：主题提取 + 口语剥离 + 元请求回退（详见 _build_search_query）
                        _q = self._build_search_query(user_input, web_ctx.get("query"))
                        if not _q:
                            # 纯元请求且无历史主题（如首次就说"你联网去搜索相关材料"）：
                            # 不瞎搜，让直答正常向用户追问主题
                            _obs = json.dumps({"status": "ok", "count": 0, "results": []}, ensure_ascii=False)
                            _data = {"status": "no_query"}
                        else:
                            _obs = await _tool_web_search(_q[:120])
                        _data = _json.loads(_obs) if isinstance(_obs, str) else {}
                        if _data.get("status") == "disabled":
                            await self._emit(event_callback, {
                                "type": "thought",
                                "step": 1,
                                "text": "联网搜索未配置检索源（需 WEB_SEARCH_PROVIDER），本次跳过联网",
                            })
                        elif _data.get("status") == "error":
                            # 检索源调用失败（超时/配额/网络）：如实透出，不让用户误以为"没结果"
                            await self._emit(event_callback, {
                                "type": "thought",
                                "step": 1,
                                "text": f"联网检索源调用失败，本次基于本地知识库回答（{_data.get('message', '')[:60]}）",
                            })
                        elif _data.get("status") == "limited":
                            await self._emit(event_callback, {
                                "type": "thought",
                                "step": 1,
                                "text": f"本轮联网检索次数已达上限（{_data.get('message', '')[:40]}），本次基于本地知识库回答",
                            })
                        elif _data.get("status") == "ok" and _data.get("results"):
                            _lines = [
                                f"- {r.get('title', '')}（来源：{r.get('domain', '')}）{r.get('snippet', '')[:200]}"
                                for r in _data.get("results", [])[:5]
                            ]
                            # Extract 精读（2026-09-07）：对前 2 条结果抽取正文全文，
                            # 让"最新动态"类回答有细节支撑而非只有标题+摘要。
                            # url 不在脱敏 observation 里，从 _last_results 原始结果取
                            _details = []
                            from app.agent.tools import _tool_web_extract, _tool_web_search as _tws
                            _raw = (getattr(_tws, "_last_results", None) or [])[:2]
                            for _r in _raw:
                                _u = (_r.get("url") or "").strip()
                                if not _u:
                                    continue
                                try:
                                    _xo = await _tool_web_extract(_u)
                                    _xd = _json.loads(_xo) if isinstance(_xo, str) else {}
                                    if _xd.get("status") == "ok" and _xd.get("content"):
                                        _details.append(
                                            f"《{_xd.get('title') or _r.get('title', '')}》"
                                            f"（来源：{_xd.get('domain', '')}）{_xd.get('content', '')[:1200]}"
                                        )
                                except Exception:
                                    pass  # 单条抽取失败不影响整体
                            # 独立块（不并入记忆 extra_context）：让模型明确知道"这是刚刚搜到的"
                            web_results_text = "\n".join(_lines)
                            if _details:
                                web_results_text += "\n\n【正文精读】\n" + "\n\n".join(_details)
                                _tip = f"已联网检索到 {len(_data.get('results', []))} 条最新信息，并精读 {len(_details)} 条正文，结合结果回答"
                            else:
                                _tip = f"已联网检索到 {len(_data.get('results', []))} 条最新信息，结合结果回答"
                            await self._emit(event_callback, {
                                "type": "thought",
                                "step": 1,
                                "text": _tip,
                            })
                            # 存入会话级联网记忆（含精读正文），供追问复用；保留已生成文档草稿
                            # material_pending：短确认（"好/生成吧"）可续接成文的素材标记
                            _prev = web_ctx_all.get(session_id) or {}
                            web_ctx_all[session_id] = {
                                "query": _q[:80],
                                "results_text": web_results_text,
                                "draft": _prev.get("draft", ""),
                                "material_pending": True,
                            }
                    except Exception as _we:
                        self._log("warn", f"general 联网检索失败（忽略）: {_we}")
                if not _need_search and web_ctx.get("results_text"):
                    # 追问元请求（"总结一下/再详细说说"类）：复用上次检索结果，不重复搜索
                    web_results_text = web_ctx["results_text"]
                    await self._emit(event_callback, {
                        "type": "thought",
                        "step": 1,
                        "text": "复用本会话刚才的联网检索内容作答（含正文精读，不重复搜索）",
                    })
                # ── 文档成文：统一在"搜索/复用"之后判断。素材优先级：本轮检索结果 >
                # 会话记忆复用 > 已生成文档草稿（"那ppt可以吗"直接把上一份 Word 稿转 PPT，
                # 不重新组稿、不再反问）──
                if _doc_flag and (web_results_text or web_ctx.get("draft")):
                    await self._emit(event_callback, {
                        "type": "thought",
                        "step": 1,
                        "text": "识别意图：把联网检索到的内容整理成文档，撰写全文并生成可下载文件",
                    })
                    fmt = "pptx" if re.search(r"ppt", user_input, re.I) else (
                        "pdf" if re.search(r"pdf", user_input, re.I) else "word")
                    if web_results_text:
                        article = await self._compose_web_article(user_input, session_id, web_results_text)
                    else:
                        article = web_ctx.get("draft") or ""
                        if article:
                            await self._emit(event_callback, {
                                "type": "thought",
                                "step": 1,
                                "text": "复用上一份文档成稿转换格式，不重新组稿",
                            })
                    if article and len(article.strip()) > 200:
                        # 复用导出链路：_intercept_generate_doc 吃 _last_draft
                        # （report_type 非 competitor 即 solution 模板，封面/章节骨架通用）
                        self._last_draft = article
                        self._format_mode = "solution"
                        obs = await self._intercept_generate_doc(fmt, event_callback)
                        try:
                            data = json.loads(obs) if isinstance(obs, str) else obs
                        except (json.JSONDecodeError, TypeError):
                            data = {}
                        if data.get("status") == "ok" and data.get("download_url"):
                            answer = (
                                f"已生成{('PPT' if fmt == 'pptx' else ('PDF' if fmt == 'pdf' else 'Word'))}文档"
                                f"（{data.get('file_name', 'doc')}），点击下载按钮即可获取。"
                            )
                            # 成稿存回会话记忆，后续"转成XX格式"直接复用；
                            # material_pending 清零：文档已产出，裸"好"不必再生成一份
                            _prev = web_ctx_all.get(session_id) or {}
                            _prev["draft"] = article
                            _prev["material_pending"] = False
                            web_ctx_all[session_id] = _prev
                        else:
                            answer = data.get("message", "文档生成失败，请稍后再试。")
                    else:
                        answer = "刚才检索到的素材还不够支撑一篇完整文档，建议换一个更具体的话题让我重新联网检索后再试。"
                    self.memory.add_agent_response(session_id, answer)
                    await self._emit(event_callback, {
                        "type": "final",
                        "step": 1,
                        "elapsed": round(time.time() - self._start_time, 2),
                        "format_mode": "general",
                    })
                    return self._make_result(answer, [], success=True, plan=[], plan_status=[], format_mode="general")
                general = await self._answer_general_chat(
                    user_input, session_id, extra_context=extra_context, web_results=web_results_text,
                )
                self.memory.add_agent_response(session_id, general)
                await self._emit(event_callback, {
                    "type": "final",
                    "step": 1,
                    "elapsed": round(time.time() - self._start_time, 2),
                    "format_mode": "general",
                })
                return self._make_result(general, [], success=True, plan=[], plan_status=[], format_mode="general")

            if self._intent == "export":
                # P1-2：导出文档意图（用户说"导出成 Word/PDF"），直接生成可下载文件，不进 ReAct
                # P2-D4：支持 PPTX（"导出成 PPT/PPTX"）
                low = user_input.lower()
                fmt = "pptx" if ("ppt" in low or "pptx" in low) else ("pdf" if "pdf" in low else "word")
                await self._emit(event_callback, {
                    "type": "thought",
                    "step": 1,
                    "text": "识别意图：导出文档请求，生成可下载的方案书",
                })
                obs = await self._intercept_generate_doc(fmt, event_callback)
                try:
                    data = json.loads(obs) if isinstance(obs, str) else obs
                except (json.JSONDecodeError, TypeError):
                    data = {}
                if data.get("status") == "ok" and data.get("download_url"):
                    answer = (
                        f"已为你生成方案书（{data.get('file_name', 'solution_report.docx')}），"
                        "点击下方下载按钮即可获取文件。"
                    )
                else:
                    answer = data.get("message", "暂无可导出的方案，请先让我生成一份方案。")
                self.memory.add_agent_response(session_id, answer)
                await self._emit(event_callback, {
                    "type": "final",
                    "step": 1,
                    "elapsed": round(time.time() - self._start_time, 2),
                })
                return self._make_result(answer, [], success=True, plan=[], plan_status=[])

            # 方案 / 竞品意图：选对应 Final Answer 结构指南（B 方案自适应）
            if self._intent == "file_ops":
                final_guide = REACT_FINAL_GUIDE_FILEOPS
            elif self._intent == "knowledge_q":
                final_guide = REACT_FINAL_GUIDE_KNOWLEDGE_Q
            else:
                final_guide = REACT_FINAL_GUIDE_COMPETITOR if self._intent == "competitor" else REACT_FINAL_GUIDE
            system_prompt = (REACT_SYSTEM_PROMPT_BASE + final_guide).format(
                tools=tools_desc,
                max_steps=self.max_steps,
            )

            # 流式思考面板首步：显式展示识别到的意图，便于用户核对分流是否正确
            if self._intent == "competitor":
                intent_text = "识别意图：竞品对比（" + "、".join(competitors) + "），检索华为+竞品方案并对比"
            elif self._intent == "file_ops":
                intent_text = "识别意图：文件操作（列出/读取上传资料），调用文件工具真实处理"
            elif self._intent == "knowledge_q":
                intent_text = "识别意图：产品图谱/架构查询，检索后文字结构化呈现"
            else:
                intent_text = "识别意图：方案匹配需求，进入工具链"
            await self._emit(event_callback, {
                "type": "thought",
                "step": 0,
                "text": intent_text,
            })

            # P0：进入 ReAct 前先生成执行计划（Devin 式 Plan 面板），
            # 让用户看到"它打算怎么做"，而不是只看到转圈
            await self._emit_plan(event_callback, user_input, self._intent)

            # P2-1-A：真·两阶段执行（plan 驱动工具调用顺序）。
            # 开关默认开；返回 None 表示需降级（clarify 或异常）→ 落到下方旧 ReAct 循环。
            self._two_phase_enabled = (AGENT_TWO_PHASE or "1").strip() == "1"
            self._multi_agent_enabled = (AGENT_MULTI_AGENT or "1").strip() == "1"
            if self._two_phase_enabled and self._plan:
                two_phase_result = await self._plan_and_execute(
                    user_input, self._intent, event_callback, session_id, tool_calls_log,
                )
                if two_phase_result is not None:
                    return two_phase_result
                self._log("system", "两阶段执行降级到 ReAct 循环（clarify 或异常）")

            history = self.memory.get_conversation_history(session_id)

            current_prompt = f"""{system_prompt}

{history}

【当前用户需求】
{user_input}
{extra_context}

现在请开始分析（若需求缺少行业或核心场景，请先用 Clarify 向用户提问）："""

            self._log("system", "ReAct 循环启动")

        # ---- ReAct 主循环 ----
        try:
            while self._step_count < self.max_steps:
                # 超时检查
                if time.time() - self._start_time > self.timeout:
                    self._log("system", f"超时 ({self.timeout}s)，强制终止")
                    fallback = await self._generate_fallback(user_input)
                    return self._make_result(fallback, tool_calls_log, success=False)

                self._step_count += 1
                self._log("system", f"--- Step {self._step_count}/{self.max_steps} ---")
                await self._emit(event_callback, {
                    "type": "step",
                    "step": self._step_count,
                    "max_steps": self.max_steps,
                })

                # 调用 LLM
                try:
                    self._log("system", f"[CLARIFY_RESUME] 开始调用 LLM (prompt_len={len(current_prompt)})")
                    llm_response = await self._call_llm(current_prompt)
                    self._log("system", f"[CLARIFY_RESUME] LLM 返回 len={len(llm_response)}")
                except Exception as e:
                    self._log("error", f"[CLARIFY_RESUME] LLM 调用失败: {e}")
                    fallback = await self._generate_fallback(user_input)
                    return self._make_result(fallback, tool_calls_log, success=False)

                self._log("llm", llm_response[:500])

                # 解析 LLM 回复
                parse_result = self._parse_react_output(llm_response)

                if parse_result["type"] == "final_answer":
                    # Agent 认为完成了
                    final_answer = parse_result["content"]
                    self._log("system", "Agent 输出 Final Answer")
                    # P1-1：点亮 plan 最后一步（综合/生成步）
                    plan_idx = len(self._plan_status) - 1 if self._plan_status else -1
                    if plan_idx >= 0:
                        self._mark_plan_status(plan_idx, "done")
                    # 统一增强管线：基于已检索资料重写最终答案（与标准模式一致）
                    final_answer = await self._finalize_answer(user_input, final_answer, tool_calls_log, event_callback=event_callback)
                    # P1-2：缓存增强后终稿，供后续 generate_doc 拦截导出（跨轮保留，不重置）
                    self._last_draft = final_answer
                    self.memory.add_agent_response(session_id, final_answer)
                    # P2-2：成功完成方案 → 存入情景记忆（旧 ReAct 路径同样保留）
                    self._maybe_save_episode(session_id, user_input, final_answer)
                    await self._emit(event_callback, {
                        "type": "final",
                        "step": self._step_count,
                        "elapsed": round(time.time() - self._start_time, 2),
                        "plan_index": plan_idx,
                    })
                    return self._make_result(final_answer, tool_calls_log, success=True)

                elif parse_result["type"] == "clarify":
                    # Agent 判断前置信息不足，请求向用户澄清 → 暂停循环，等待续跑
                    self._clarify_round += 1
                    if self._clarify_round >= 3:
                        # 已经问过三轮，强制收尾：追加提示后继续循环（下一轮应出 Final Answer）
                        self._log("system", "已达澄清轮次上限，强制收尾")
                        current_prompt += f"""
{llm_response}
（注意：你已经向用户提问过，现在请直接基于已有信息给出 Final Answer，不要再提问。）"""
                        continue

                    new_clarify_id = str(uuid.uuid4())
                    ClarifySessionStore.put(new_clarify_id, {
                        "session_id": session_id,
                        "user_input": user_input,
                        "extra_context": extra_context,
                        "current_prompt": current_prompt,
                        "step_count": self._step_count,
                        "clarify_round": self._clarify_round,
                    })
                    questions = parse_result["questions"]
                    self._log("system", f"Agent 请求澄清（{new_clarify_id}），暂停循环")
                    await self._emit(event_callback, {
                        "type": "clarify",
                        "clarify_id": new_clarify_id,
                        "session_id": session_id,
                        "questions": questions,
                    })
                    return self._make_result(
                        "", tool_calls_log, success=False,
                        paused=True, clarify_id=new_clarify_id, questions=questions,
                    )

                elif parse_result["type"] == "action":
                    # 需要执行工具
                    tool_name = parse_result["tool_name"]
                    tool_input = parse_result["tool_input"]

                    # P1-2：generate_doc 拦截——LLM 在 ReAct 内要求导出时（主路径是 export 意图，
                    # 此处为兜底），直接取缓存终稿导出，不依赖 LLM 传 content（它本就没有终稿文本）。
                    if tool_name == "generate_doc":
                        # #3 工具权限闸门（generate_doc 走专门拦截分支，未经过 _execute_tool）
                        gate = await self._gate_tool(tool_name, tool_input, event_callback)
                        if gate is not None:
                            tool_calls_log.append({
                                "step": self._step_count, "tool": tool_name,
                                "input": tool_input, "result": gate,
                            })
                            self.memory.add_action(session_id, tool_name, str(tool_input))
                            await self._emit(event_callback, {
                                "type": "tool_end",
                                "step": self._step_count,
                                "tool": tool_name,
                                "summary": "已跳过文档生成（被权限策略拦截）",
                            })
                            current_prompt += f"""
Observation: {gate}
请继续（如用户还要求其它操作再调用工具，否则给出 Final Answer）。"""
                            continue
                        fmt = str(tool_input.get("format", "word") or "word").lower()
                        if fmt not in ("word", "pdf", "pptx"):
                            fmt = "word"
                        obs = await self._intercept_generate_doc(fmt, event_callback)
                        tool_calls_log.append({"step": self._step_count, "tool": tool_name, "input": tool_input, "result": obs})
                        self.memory.add_action(session_id, tool_name, str(tool_input))
                        await self._emit(event_callback, {
                            "type": "tool_end",
                            "step": self._step_count,
                            "tool": tool_name,
                            "summary": "已生成可下载的方案书",
                        })
                        current_prompt += f"""
Observation: {obs}
请继续（如用户还要求其它操作再调用工具，否则给出 Final Answer）。"""
                        continue

                    self._log("action", f"调用工具: {tool_name}({tool_input})")
                    tool_calls_log.append({
                        "step": self._step_count,
                        "tool": tool_name,
                        "input": tool_input,
                    })

                    # 记录到记忆
                    thought = parse_result.get("thought", "")
                    if thought:
                        self.memory.add_thought(session_id, thought)
                        await self._emit(event_callback, {
                            "type": "thought",
                            "step": self._step_count,
                            "text": thought[:300],
                        })
                    self.memory.add_action(session_id, tool_name, str(tool_input))

                    # P1-1：计算 plan 步索引并点亮（running）
                    plan_index = self._tool_to_plan_index(tool_name, self._intent)
                    if plan_index >= 0:
                        self._mark_plan_status(plan_index, "running")

                    # 发送工具开始事件（带 plan_index）
                    await self._emit(event_callback, {
                        "type": "tool_start",
                        "step": self._step_count,
                        "tool": tool_name,
                        "plan_index": plan_index,
                    })

                    # 执行工具
                    observation = await self._execute_tool(tool_name, tool_input, event_callback)
                    self._log("observation", observation[:300])
                    self.memory.add_observation(session_id, observation)

                    # 将工具结果存入日志，供 routes.py 提取 source_documents
                    tool_calls_log[-1]["result"] = observation

                    # P1-1：工具完成 → 点亮对应步（done）
                    if plan_index >= 0:
                        self._mark_plan_status(plan_index, "done")

                    # P1-3：连续工具失败计数（达阈值触发反思）
                    if "Error:" in observation:
                        self._consecutive_tool_failures += 1
                    else:
                        self._consecutive_tool_failures = 0

                    # P1-3：记录执行轨迹（供 reflexion 反思使用）
                    self._record_trajectory(thought, tool_name, observation)

                    # P0 工具结果摘要（2026-08-26）：tool_end 附带一句话结果说明，
                    # 让用户看到"检索到什么"，而不只是一个工具名（增强执行可见性）
                    summary = self._summarize_tool_result(tool_name, observation)

                    # 发送工具完成事件（带 plan_index）
                    await self._emit(event_callback, {
                        "type": "tool_end",
                        "step": self._step_count,
                        "tool": tool_name,
                        "summary": summary,
                        "plan_index": plan_index,
                    })

                    # P1-3：连续失败达阈值 → 触发一次反思（注入调整建议到 current_prompt，下一轮继续），避免盲目重试同一错误
                    if self._consecutive_tool_failures >= 2 and not getattr(self, "_reflexion_injected", False):
                        reflect = await self._reflexion_retry(event_callback)
                        if reflect:
                            self._consecutive_tool_failures = 0
                            self._reflexion_injected = True
                            current_prompt += (
                                f"\n\n【反思与调整建议】{reflect}\n"
                                "请据此调整下一步策略，继续推进任务（如信息不足请直接 Clarify 或换关键词重试，不要重复同样的错误参数）。"
                            )

                    # 将 Observation 追加到 Prompt，进入下一轮
                    # D修复：截断回声与 Observation，防止多步检索后 prompt 爆炸导致模型失焦/乱答
                    current_prompt += f"""

{_trunc(llm_response, 1500)}

Observation: {_trunc(observation, 2500)}

请继续分析。如果信息足够，请输出 Final Answer。"""

                else:
                    # 解析失败。如果已有工具调用结果，直接把 LLM 输出当最终答案
                    if tool_calls_log:
                        self._log("warn", "LLM 格式不对但已有数据，统一增强管线重写")
                        final_answer = await self._finalize_answer(user_input, llm_response, tool_calls_log, event_callback=event_callback)
                        self.memory.add_agent_response(session_id, final_answer)
                        await self._emit(event_callback, {
                            "type": "final",
                            "step": self._step_count,
                            "elapsed": round(time.time() - self._start_time, 2),
                        })
                        return self._make_result(final_answer, tool_calls_log, success=True)
                    # 第一次就格式错误，引导重试
                    self._log("warn", f"无法解析 LLM 输出: {llm_response[:200]}")
                    current_prompt += f"""

{_trunc(llm_response, 1500)}

（你的输出格式不正确。请严格按格式输出：
Thought: [分析]
Action: [工具名]
Action Input: [JSON参数]

或者：
Thought: 我已收集到足够信息
Final Answer: [完整方案]）"""

            # 超过最大步数
            self._log("system", f"超过最大步数 {self.max_steps}，尝试 Reflexion 反思后补救")
            if not getattr(self, "_reflexion_injected", False):
                await self._reflexion_retry(event_callback)
            fallback = await self._generate_fallback(user_input)
            return self._make_result(fallback, tool_calls_log, success=False)

        except Exception as e:
            self._log("error", f"ReAct 循环异常: {e}")
            fallback = await self._generate_fallback(user_input)
            return self._make_result(fallback, tool_calls_log, success=False)

    # ---- LLM 调用 ----

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM，支持重试（用户临时切换的模型/思考开关优先）"""
        from app.models.llm import get_llm_response

        last_error = None
        for attempt in range(3):
            try:
                return await get_llm_response(
                    prompt,
                    model=getattr(self, "_run_model", None) or MATCH_LLM_MODEL,
                )
            except Exception as e:
                last_error = e
                logger.warning(f"LLM 调用失败 (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    await asyncio.sleep(2)
        raise last_error or RuntimeError("LLM call failed")

    # ---- 工具执行 ----

    async def _execute_tool(self, tool_name: str, tool_input: dict, event_callback=None) -> str:
        """执行指定工具，返回 Observation 字符串"""
        # #3 工具权限闸门 + #6 联网搜索开关（所有工具路径的统一拦截点）
        gate = await self._gate_tool(tool_name, tool_input, event_callback)
        if gate is not None:
            return gate
        tool = self.tools.get(tool_name)
        if not tool:
            return f"错误：工具 '{tool_name}' 不存在。可用工具：{self.tools.get_tool_names()}"

        try:
            return await tool.execute(**tool_input)
        except TypeError as e:
            # 参数不匹配，尝试纠正
            return f"错误：工具 '{tool_name}' 参数不正确：{e}。期望参数：{json.dumps(tool.parameters, ensure_ascii=False)}"
        except Exception as e:
            return f"工具 '{tool_name}' 执行失败：{str(e)}"

    async def _exec_one_action(
        self, idx: int, tool_name: str, tool_input: dict,
        event_callback, session_id: str, tool_calls_log: list,
    ) -> str:
        """P3-2：单工具执行的统一协程（顺序与并行路径共用）。

        点亮 running → 发 tool_start → 执行 → 记轨迹/失败计数 → 发 tool_end，返回 observation。
        失败计数沿用 P1-3 规则（连续失败由外层 _plan_and_execute 触发重规划）。
        """
        self._step_count += 1
        self._mark_plan_status(idx, "running")
        await self._emit(event_callback, {
            "type": "tool_start", "step": self._step_count,
            "tool": tool_name, "plan_index": idx,
        })
        self.memory.add_action(session_id, tool_name, str(tool_input))
        observation = await self._execute_tool(tool_name, tool_input, event_callback)
        self.memory.add_observation(session_id, observation)
        tool_calls_log.append({
            "step": self._step_count, "tool": tool_name,
            "input": tool_input, "result": observation,
        })
        if "Error:" in observation:
            self._consecutive_tool_failures += 1
        else:
            self._consecutive_tool_failures = 0
        self._record_trajectory("", tool_name, observation)
        summary = self._summarize_tool_result(tool_name, observation)
        await self._emit(event_callback, {
            "type": "tool_end", "step": self._step_count,
            "tool": tool_name, "summary": summary, "plan_index": idx,
        })
        return observation

    # ── 强制成本测算步：harness 确定性驱动 cost_calc（绕过模型不稳定的工具链）──
    async def _force_cost_step(self, event_callback, session_id, tool_calls_log, user_input) -> str:
        """定价意图下若整轮未调 cost_calc，由 harness 确定性完成测算：
        1) 取 cost_reference_list 的 SKU 目录（复用本轮已调结果，否则现调）；
        2) 一次结构化抽取把用户需求转成 items；
        3) 直接调用 cost_calc（harness 驱动，不依赖模型自发 emit）。
        返回该步的 Observation 文本（含 TCO 结果）。"""
        # 1) SKU 目录（复用本轮 reference_list 的 observation）
        ref_obs = ""
        for t in tool_calls_log:
            if t.get("tool") == "mcp__cost__cost_reference_list" and t.get("result"):
                ref_obs = t["result"]
                break
        if not ref_obs:
            ref_obs = await self._exec_one_action(
                len(self._plan), "mcp__cost__cost_reference_list", {},
                event_callback, session_id, tool_calls_log,
            )
        skus = re.findall(r"^- ([A-Za-z0-9.]+):", ref_obs, re.MULTILINE)
        sku_hint = "\n".join(f"- {s}" for s in skus) if skus else "(见上方目录)"
        # 2) 结构化抽取 items
        extract_prompt = (
            "你是云资源成本结构化抽取器。根据用户需求与可用 SKU 目录，抽取成本测算资源清单。\n\n"
            f"【可用 SKU 编码（items[].sku 只能从这些里选）】\n{sku_hint}\n\n"
            f"【用户需求】{user_input}\n\n"
            "只输出一个 JSON 数组，每项 {\"sku\": \"<编码>\", \"qty\": <数量数字>, \"months\": <月数,默认1>}，"
            "不要任何解释。目录中无对应 SKU 的资源直接忽略。\n"
            '示例：[{"sku":"ecs.s6.large.2","qty":50,"months":1}]'
        )
        raw = await self._call_llm(extract_prompt)
        items = self._extract_json_array(raw)
        if isinstance(items, dict):
            items = items.get("items") or []
        if not isinstance(items, list) or not items:
            return "（强制成本步：无法从需求中抽取结构化资源清单，跳过成本测算）"
        if skus:
            items = [it for it in items if isinstance(it, dict) and str(it.get("sku")) in skus]
        if not items:
            return "（强制成本步：抽取到的 SKU 均不在目录内，跳过成本测算）"
        # 3) 确定性调用 cost_calc
        obs = await self._exec_one_action(
            len(self._plan) + 1, "mcp__cost__cost_calc", {"items": items},
            event_callback, session_id, tool_calls_log,
        )
        return f"（强制成本测算步结果）\n{obs}"

    # ── 强制 CRM 步：harness 确定性驱动 client_add / client_update（绕过模型不稳定/幻觉的写入工具链）──
    async def _force_crm_step(self, event_callback, session_id, tool_calls_log, user_input) -> str:
        """客户建档/更新意图下若整轮未调对应写入工具，由 harness 确定性完成：
        1) 用 LLM 从原话判断操作类型（add=新建档案 / update=补充修改已有客户）并抽字段；
        2) 直接调用 mcp__crm__client_add / client_update（走权限闸门 ask，需用户确认才落库）。
        返回该步的 Observation 文本（含真实结果或拒绝/跳过原因），供终稿如实反映。"""
        extract_prompt = (
            "你是 CRM 客户档案操作抽取器。根据用户的话，判断操作类型并抽取客户名称与字段。\n\n"
            f"【用户原话】{user_input}\n\n"
            '只输出一个 JSON 对象：{"op": "add" 或 "update" 或 "delete", "name": "<客户名称，必填>", ...其余只填原话明确提到的字段}\n'
            "可填字段：stage（商机阶段）、industry（行业）、company_size（规模）、region（区域）、"
            "contact_name（联系人）、contact_title（职位）、contact_phone（电话）、contact_email（邮箱）、"
            "budget（预算）、pain_points（痛点）、decision_chain（决策链）、tags（标签）、note（备注）。\n"
            "规则：\n"
            "1. op 判断：想新建档案（存成客户/记录客户/添加客户/建档）→ \"add\"；"
            "想给已有客户补充或修改信息（加个行业/更新阶段/修改备注/补充联系人）→ \"update\"；"
            "想删除客户档案（删除/删掉/移除某客户）→ \"delete\"；\n"
            "2. name 必须从原话提取客户主体名称，例如「把杭州海康威视存成客户」→ name=\"杭州海康威视\"；"
            "「给杭州海康威视加个行业，制造业」→ name=\"杭州海康威视\"、industry=\"制造业\"；\n"
            "3. 除 name 外只填原话明确提到的字段，没提到的绝对不要编（delete 只需 name）；"
            "stage 取值限定：初步接触/需求调研/方案报价/商务谈判/已成交/已流失；\n"
            "4. 只输出 JSON，不要任何解释或代码围栏。\n"
        )
        raw = await self._call_llm(extract_prompt)
        data = self._extract_json_object(raw)
        if not isinstance(data, dict) or not (data.get("name") or "").strip():
            return "（强制CRM步：未能从输入中提取有效客户名称，跳过写入）"
        name = str(data["name"]).strip()
        fields = {}
        for f in ("stage", "industry", "company_size", "region", "contact_name",
                  "contact_title", "contact_phone", "contact_email", "budget",
                  "pain_points", "decision_chain", "tags", "note"):
            v = data.get(f)
            if isinstance(v, str) and v.strip():
                fields[f] = v.strip()
        op = data.get("op") if data.get("op") in ("add", "update", "delete") else "add"
        if op == "update" and not fields:
            return "（强制CRM步：update 缺少要修改的字段，跳过写入）"
        tool = {"add": "mcp__crm__client_add", "update": "mcp__crm__client_update",
                "delete": "mcp__crm__client_delete"}[op]
        args = {"name": name} if op == "delete" else {"name": name, **fields}
        obs = await self._exec_one_action(
            len(self._plan) + 1, tool, args,
            event_callback, session_id, tool_calls_log,
        )
        return f"（强制CRM步结果）\n{obs}"

    # ── 强制 CRM 查询步：只读确定性查询（client_list / match_history），不弹窗 ──
    async def _force_crm_query_step(self, event_callback, session_id, tool_calls_log, user_input) -> str:
        """客户档案/历史方案查询意图（只读）：harness 确定性查询，杜绝 general 直答编造客户数据。
        只读工具由 harness 确定性发起（非模型自主越权），临时放行不弹窗，调用后恢复原权限策略。"""
        extract_prompt = (
            "你是 CRM 查询意图解析器。根据用户的话输出一个 JSON 对象：\n"
            '{"target": "clients" 或 "history", "keyword": "<关键词，可空字符串>"}\n'
            "规则：\n"
            "1. 问客户档案/客户列表/某客户的资料或阶段/有多少客户 → target=\"clients\"；"
            "问历史方案/合作过什么方案/给哪些客户做过方案/匹配记录 → target=\"history\"；\n"
            "2. keyword 取用户想查的客户名/行业/竞品名等过滤关键词，没有就留空字符串；\n"
            "3. 只输出 JSON，不要解释。\n\n"
            f"【用户原话】{user_input}"
        )
        raw = await self._call_llm(extract_prompt)
        data = self._extract_json_object(raw) or {}
        target = data.get("target") if data.get("target") in ("clients", "history") else "clients"
        keyword = str(data.get("keyword") or "").strip()
        args = {"keyword": keyword} if keyword else {}
        saved_perms = dict(getattr(self, "_tool_permissions", {}) or {})
        self._tool_permissions = {
            **saved_perms,
            "mcp__crm__client_list": "allow",
            "mcp__crm__match_history": "allow",
        }
        try:
            if target == "history":
                obs = await self._exec_one_action(
                    len(self._plan) + 1, "mcp__crm__match_history", args,
                    event_callback, session_id, tool_calls_log,
                )
                return f"（历史方案查询结果）\n{obs}"
            obs = await self._exec_one_action(
                len(self._plan) + 1, "mcp__crm__client_list", args,
                event_callback, session_id, tool_calls_log,
            )
            return f"（客户档案查询结果）\n{obs}"
        finally:
            self._tool_permissions = saved_perms

    # ── 知识库统计步：直接调 get_stats() 真数据，杜绝 general 直答编文档数 ──
    async def _force_kb_stats_step(self) -> str:
        from app.services.knowledge_base import get_knowledge_base
        kb = get_knowledge_base()
        stats = await asyncio.to_thread(kb.get_stats)
        total = stats.get("total_documents", 0) or 0
        lines = [f"知识库实时统计：共 {total} 篇向量文档片段。"]
        industries = stats.get("industry_counts") or {}
        ind_pairs = sorted(((k, v) for k, v in industries.items() if v), key=lambda x: -x[1])
        if ind_pairs:
            shown = "、".join(f"{k} {v}篇" for k, v in ind_pairs[:8])
            more = f" 等 {len(ind_pairs)} 个行业" if len(ind_pairs) > 8 else ""
            lines.append(f"行业分布：{shown}{more}。")
        comp_total = stats.get("total_competitor_files", 0) or 0
        if comp_total:
            comps = stats.get("competitor_stats") or {}
            comp_names = "、".join(str(k) for k in comps.keys())[:80]
            lines.append(f"竞品资料：{comp_total} 篇（{comp_names}）。")
        return "（知识库统计结果）\n" + "\n".join(lines)

    @staticmethod
    def _crm_save_answer(obs: str) -> str:
        """把强制CRM步的真实 Observation 映射为对用户的诚实答复。

        铁律：工具没执行/被拒绝/失败时绝不声称"已保存/已更新"。成功与
        重复建档、未找到客户等情况直接透出 crm Server 的可读结果文本。
        """
        if not obs or not obs.strip():
            return "（操作未完成：工具没有返回结果，客户档案未写入。请稍后重试。）"
        if "未能从输入中提取有效客户名称" in obs:
            return (
                "你想操作客户档案，但我没能从你的话里识别出客户名称。"
                "请告诉我客户名称，例如「把杭州海康威视存成客户」或「给杭州海康威视加个行业，制造业」，"
                "我来帮你建档或更新。"
            )
        if "update 缺少要修改的字段" in obs:
            return (
                "你想更新客户档案，但我没识别出要修改的具体内容。"
                "请补充要改的字段，例如「给杭州海康威视加个行业，制造业」或「把海康威视的阶段改成方案报价」。"
            )
        if "你拒绝了工具" in obs or "已被你设为禁止执行" in obs:
            return (
                "本次写入你选择了拒绝（或确认超时），客户档案**没有**保存或修改。"
                "如需操作请再次告诉我，并在权限弹窗中点「允许执行」。"
            )
        if "（强制CRM步" in obs:
            # 其余跳过类（如异常），原样如实反馈，不粉饰
            return obs
        # 成功建档/更新、同名已存在、未找到客户等：crm 返回文本本身可读，直接透出并补一句后续引导
        return obs + "\n\n已同步到你的「客户管理」档案，可随时让我查询或继续补充信息。"

    @staticmethod
    def _crm_query_answer(obs: str) -> str:
        """CRM 查询步的答复映射：查询结果文本本身可读，直接透出；拒绝/空返回如实反馈。"""
        if not obs or not obs.strip():
            return "（查询未完成：工具没有返回结果，请稍后重试。）"
        if "你拒绝了工具" in obs or "已被你设为禁止执行" in obs:
            return "本次查询你选择了拒绝，未读取档案数据。"
        return obs

    def _cost_query_answer(self, obs: str, tool_calls_log: list) -> str:
        """general 兜底成本步的答复映射：成功透出真实测算结果；抽取失败附真实 SKU 目录引导。"""
        if not obs or not obs.strip():
            return "（成本测算未完成：工具没有返回结果，请稍后重试。）"
        if "无法从需求中抽取" in obs:
            ans = (
                "你想测算成本，但我没能从你的话里识别出具体的云资源与数量。"
                "请说明资源和规模，例如「50台4核8G的ECS用3个月多少钱」，我按真实目录给你算。"
            )
        elif "均不在目录" in obs:
            ans = "你提到的资源不在当前可报价 SKU 目录里，无法给出真实报价。"
        elif "Error" in obs or "执行异常" in obs:
            return f"成本测算没有完成：{obs}"
        else:
            ans = obs
        if "无法从需求中抽取" in obs or "均不在目录" in obs:
            dir_obs = ""
            for t in reversed(tool_calls_log):
                if t.get("tool") == "mcp__cost__cost_reference_list" and t.get("result"):
                    dir_obs = t["result"]
                    break
            if dir_obs:
                ans += "\n\n当前可报价的 SKU 目录：\n" + dir_obs
        return ans

    # 明确的方案制作动词（出现时不做 CRM 短路，组合诉求仍走两阶段 + 强制步）
    _SOLUTION_VERB_RE = re.compile(r"(做|写|生成|制定|输出)一?[份个]|做个|写个|生成个|出一份")

    async def _maybe_crm_intercept(self, user_input, session_id, event_callback, tool_calls_log, intent_text=None):
        """general 路径与 solution/competitor 短路共用的数据诚信拦截链。

        general 分支没有工具调用能力（会编数据）；solution 意图会被行业词把
        纯 CRM 操作绕进两阶段方案生成（"给X加个行业，制造业"被当成要写方案，
        E2E 实测）。两类路径统一走本拦截链：全部用真实工具/服务结果作答。
        命中顺序：CRM写入(ask弹窗) → CRM查询 → KB统计 → 成本兜底；
        全不命中返回 None（调用方继续走原路径）。

        intent_text（2026-09-09）：全部正则判定只用用户原话——vision 描述拼进
        user_input 后，其行业/成本词会误触发成本兜底等拦截（图片求描述被拉去报价）。
        user_input 仍作为强制步的输入（工具需要完整上下文）。
        """
        _match_text = intent_text or user_input or ""
        async def _finish(answer_text: str):
            self.memory.add_agent_response(session_id, answer_text)
            await self._emit(event_callback, {
                "type": "final",
                "step": 1,
                "elapsed": round(time.time() - self._start_time, 2),
            })
            return self._make_result(answer_text, tool_calls_log, success=True, plan=[], plan_status=[])

        # 1) CRM 写入（add/update/delete）：走权限闸门 ask，用户弹窗确认才落库
        if self._remote_tool_names and self._crm_intent_hit(_match_text):
            await self._emit(event_callback, {
                "type": "thought",
                "step": 1,
                "text": "识别意图：客户建档/更新/删除（CRM），调用客户管理工具写入档案",
            })
            try:
                crm_obs = await self._force_crm_step(event_callback, session_id, tool_calls_log, user_input)
            except Exception as crm_err:
                self._log("warn", f"[强制CRM步] 执行异常（如实反馈，不降级到通用问答防幻觉）: {crm_err}")
                crm_obs = f"（强制CRM步：执行异常 {crm_err}，客户档案未写入）"
            return await _finish(self._crm_save_answer(crm_obs))

        # 2) CRM 查询（client_list / match_history，只读，harness 确定性放行不弹窗）
        if self._remote_tool_names and self._crm_query_hit(_match_text):
            await self._emit(event_callback, {
                "type": "thought",
                "step": 1,
                "text": "识别意图：客户档案/历史方案查询（CRM 只读），读取真实数据回答",
            })
            try:
                query_obs = await self._force_crm_query_step(event_callback, session_id, tool_calls_log, user_input)
            except Exception as q_err:
                self._log("warn", f"[CRM查询步] 执行异常: {q_err}")
                query_obs = f"（CRM查询：执行异常 {q_err}，未能读取真实档案）"
            return await _finish(self._crm_query_answer(query_obs))

        # 3) 知识库统计（只读真数据，本地服务不依赖 MCP）
        if self._kb_stats_hit(_match_text):
            await self._emit(event_callback, {
                "type": "thought",
                "step": 1,
                "text": "识别意图：知识库统计查询，读取真实统计回答",
            })
            try:
                kb_obs = await self._force_kb_stats_step()
            except Exception as kb_err:
                self._log("warn", f"[KB统计步] 执行异常: {kb_err}")
                kb_obs = f"（知识库统计：执行异常 {kb_err}，无法提供真实数字）"
            return await _finish(kb_obs)

        # 4) 成本/价格问询兜底（带具体规格的问价多判 solution 走两阶段强制成本步；
        #    此处兜仍命中定价词的问法，杜绝编价格；只读确定性放行）
        if self._remote_tool_names and self._PRICING_RE.search(_match_text):
            await self._emit(event_callback, {
                "type": "thought",
                "step": 1,
                "text": "识别意图：成本/价格测算（只读），按真实 SKU 目录报价",
            })
            saved_perms = dict(getattr(self, "_tool_permissions", {}) or {})
            self._tool_permissions = {**saved_perms,
                                      "mcp__cost__cost_calc": "allow",
                                      "mcp__cost__cost_reference_list": "allow"}
            try:
                cost_obs = await self._force_cost_step(event_callback, session_id, tool_calls_log, user_input)
            except Exception as c_err:
                self._log("warn", f"[成本兜底步] 执行异常: {c_err}")
                cost_obs = f"（强制成本步：执行异常 {c_err}，以下回答不含真实报价）"
            finally:
                self._tool_permissions = saved_perms
            return await _finish(self._cost_query_answer(cost_obs, tool_calls_log))

        return None

    @staticmethod
    def _extract_json_object(text):
        if not text:
            return None
        cleaned = re.sub(r"```(?:json)?", "", text).strip()
        try:
            return json.loads(cleaned)
        except Exception:
            pass
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None

    @staticmethod
    def _extract_json_array(text):
        if not text:
            return None
        cleaned = re.sub(r"```(?:json)?", "", text).strip()
        try:
            return json.loads(cleaned)
        except Exception:
            pass
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None

    # ---- 工具权限闸门（#3 human-in-the-loop）/ 联网搜索开关（#6）----
    # 默认策略：高风险工具在 Agent 自主决策执行时先征求确认；显式「导出」意图不走此闸门。
    DEFAULT_TOOL_POLICY = {
        "generate_doc": "ask",
        "read_customer_file": "ask",
        "web_search": "allow",
        "web_extract": "allow",
        "run_python": "ask",    # L4 P0：沙箱代码执行默认弹窗确认（会话内可放行）
    }

    async def _gate_tool(self, tool_name: str, tool_input: dict, event_callback=None) -> Optional[str]:
        """返回 None 表示放行；返回字符串表示跳过工具并作为 Observation 注入。

        - #6 联网搜索关闭：直接跳过 web_search，不再联网。
        - #3 策略 deny：跳过；ask：发 permission_request SSE 并阻塞等待用户决策。
        """
        # #6 联网搜索开关（同时关掉联网正文抽取）
        if tool_name in ("web_search", "web_extract") and getattr(self, "_disable_web_search", False):
            return "（已关闭联网搜索，本次跳过网络检索，仅基于本地知识库作答。）"
        policy = self._resolve_tool_policy(tool_name)
        if policy == "deny":
            return f"（工具「{tool_name}」已被你设为禁止执行，已跳过。）"
        if policy == "ask":
            try:
                from app.agent.permission_gate import request_permission
            except Exception:  # noqa: BLE001
                return None
            import uuid as _uuid
            request_id = str(_uuid.uuid4())
            reason = self._permission_reason(tool_name)
            safe_input = self._permission_safe_input(tool_name, tool_input)
            await self._emit(event_callback, {
                "type": "permission_request",
                "request_id": request_id,
                "tool": tool_name,
                "input": safe_input,
                "reason": reason,
            })
            try:
                decision = await request_permission(request_id, tool_name, tool_input, reason)
            except Exception as e:  # noqa: BLE001
                self._log("warn", f"权限确认异常（默认放行）: {e}")
                return None
            if decision != "allow":
                return f"（你拒绝了工具「{tool_name}」的执行，已跳过该步骤。）"
        return None

    def _resolve_tool_policy(self, tool_name: str) -> "str | None":
        """解析工具权限策略：用户覆盖 > 远端 mcp__ 默认 ask > 内置默认策略。

        策略逻辑下沉到 permission_gate.resolve_tool_policy（纯函数，可单测）。
        """
        from app.agent.permission_gate import resolve_tool_policy
        return resolve_tool_policy(
            tool_name,
            getattr(self, "_tool_permissions", None),
            self.DEFAULT_TOOL_POLICY,
        )

    def _permission_reason(self, tool_name: str) -> str:
        return {
            "generate_doc": "Agent 准备生成一份可下载的方案书（Word/PDF/PPTX），将占用存储并生成文件。",
            "read_customer_file": "Agent 准备读取你上传的客户资料文件。",
            "run_python": "Agent 准备在沙箱中执行一段 Python 代码（精确计算/数据整理，无网络无文件写入，≤5 秒）。",
        "web_search": "Agent 准备联网检索（华为云官网 / 竞品动态），可能产生额外请求。",
        "web_extract": "Agent 准备联网读取一个网页的正文内容，可能产生额外请求。",
    }.get(tool_name, f"Agent 准备执行工具「{tool_name}」。")

    def _permission_safe_input(self, tool_name: str, tool_input: dict) -> dict:
        """URL / 路径脱敏：只暴露对决策有用的最小信息。"""
        ti = tool_input or {}
        if tool_name == "web_search":
            return {"query": str(ti.get("query", ""))[:120]}
        if tool_name == "web_extract":
            return {"url": str(ti.get("url", ""))[:120]}
        if tool_name == "read_customer_file":
            return {"path": str(ti.get("path", ""))[:160]}
        if tool_name == "generate_doc":
            return {"fmt": str(ti.get("format", ti.get("fmt", "word")))}
        if tool_name == "run_python":
            code = str(ti.get("code", ""))
            return {"code": code[:300] + ("…（共 %d 字符）" % len(code) if len(code) > 300 else "")}
        return {k: str(v)[:120] for k, v in ti.items()}

    # ---- 上下文用量预估（#1）----
    @staticmethod
    def _est_tokens(text: str) -> int:
        """中文 + 英文混排的粗略 token 估算（约 1.6 字符 / token）。"""
        if not text:
            return 0
        return max(1, int(len(text) / 1.6))

    def estimate_context_usage(self, session_id: str, extra_text: str = "") -> dict:
        """预估当前会话上下文占用（token 估算，仅展示用，非精确分词）。

        extra_text：客户上下文块（用量接口按选中客户传入），单列 client_context 桶。
        """
        # 系统提示词（方案类基准 + Final Answer 指南）：本模块顶层常量，直接引用
        system_text = (REACT_SYSTEM_PROMPT_BASE or "") + (REACT_FINAL_GUIDE or "")
        tools_text = ""
        try:
            tools_text = self.tools.get_tools_prompt() or ""
        except Exception:  # noqa: BLE001
            tools_text = ""
        memory_text = ""
        try:
            from app.agent.memory_profiles import build_memory_context, build_profile_context
            uid = getattr(self, "_user_id", None)
            if isinstance(uid, int) and uid > 0:
                memory_text = (build_memory_context(uid, "", client_id=getattr(self, "_client_id", None)) or "") + (build_profile_context(uid) or "")
        except Exception:  # noqa: BLE001
            memory_text = ""
        conv_text = ""
        try:
            hist = self.memory.get_conversation_history(session_id) or ""
            conv_text = hist if isinstance(hist, str) else str(hist)
            # 空会话占位文案不算 token（否则新对话"对话历史 5"造成像有残留的误解）
            if conv_text.startswith("（这是第一次对话）"):
                conv_text = ""
        except Exception:  # noqa: BLE001
            conv_text = ""
        window = int(AGENT_CONTEXT_WINDOW or 64000)
        buckets = {
            "system": self._est_tokens(system_text),
            "tools": self._est_tokens(tools_text),
            "memory": self._est_tokens(memory_text),
            "conversation": self._est_tokens(conv_text),
        }
        if extra_text:
            buckets["client_context"] = self._est_tokens(extra_text)
        total = sum(buckets.values())
        return {
            "buckets": buckets,
            "total": total,
            "window": window,
            "percent": min(100, round(total * 1000 / window) / 10) if window else 0,  # 一位小数：低占用区间也能看出对话增长
            "estimated": True,
        }

    # ---- 输出解析 ----

    def _parse_react_output(self, text: str) -> Dict[str, Any]:
        """
        解析 LLM 的 ReAct 格式输出

        支持两种格式：
        1. Thought: ... \n Action: tool_name \n Action Input: {...}
        2. Thought: ... \n Final Answer: ...

        增强：如果既没有 Action 也没有 Final Answer，
        但文本包含实质性内容（中文、Markdown），视为隐式 Final Answer。
        """
        # 先尝试匹配 Clarify（向用户澄清提问）
        clarify_match = re.search(
            r'Clarify\s*[*]*\s*[:：]\s*(.*?)$',
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if clarify_match:
            questions = self._parse_clarify_questions(clarify_match.group(1))
            if questions:
                return {"type": "clarify", "questions": questions}

        # 尝试匹配 Final Answer（显式声明）
        fa_match = re.search(
            r'Final\s*Answer\s*[*]*\s*[:：]\s*[*`]*\s*(.*?)$',
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if fa_match:
            thought_match = re.search(
                r'(?:Thought|思考|分析|计划)\s*[*]*\s*[:：]\s*[*`]*\s*(.+?)(?=\n\s*(?:Final|Action|Action\s*Input)|$)',
                text, re.DOTALL | re.IGNORECASE,
            )
            # 兜底：未匹配到显式 Thought 标签时，取 Final Answer 之前的文本作为思考摘要
            thought_text = ""
            if thought_match:
                thought_text = thought_match.group(1).strip()
            else:
                before_fa = text[:fa_match.start()].strip()
                if before_fa and len(before_fa) > 5:
                    thought_text = before_fa[:200]
            return {
                "type": "final_answer",
                "content": fa_match.group(1).strip(),
                "thought": thought_text,
            }

        # 尝试匹配 Action + Action Input
        action_match = re.search(
            r'Action\s*[*]*\s*[:：]\s*[*`\s]*(\w+)',
            text,
            re.IGNORECASE,
        )
        if action_match:
            tool_name = action_match.group(1).strip()

            # 尝试解析 Action Input（JSON 格式）
            input_match = re.search(
                r'Action\s*Input\s*[*]*\s*[:：]\s*.*?(\{.*?\})',
                text,
                re.DOTALL | re.IGNORECASE,
            )
            tool_input = {}
            if input_match:
                try:
                    tool_input = json.loads(input_match.group(1).strip())
                except json.JSONDecodeError:
                    # JSON 解析失败，尝试提取纯文本作为 query
                    tool_input = {"query": input_match.group(1).strip()}
            else:
                # 没有 Action Input，尝试从整段文本推断
                # 可能 LLM 把参数直接写在了 Action 行后面
                raw_input = text[action_match.end():].strip()
                if raw_input:
                    tool_input = {"query": raw_input[:200]}

            # 提取思考过程（宽松匹配 + 兜底）
            thought_match = re.search(
                r'(?:Thought|思考|分析|计划)\s*[*]*\s*[:：]\s*[*`]*\s*(.+?)(?=\n\s*(?:Action|Action\s*Input|Final)|$)',
                text,
                re.DOTALL | re.IGNORECASE,
            )
            thought_text = ""
            if thought_match:
                thought_text = thought_match.group(1).strip()
            else:
                # 兜底：取 Action 之前的文本作为思考摘要
                before_action = text[:action_match.start()].strip()
                if before_action and len(before_action) > 5:
                    # 去掉常见的无关前缀
                    thought_text = before_action[:200]
            return {
                "type": "action",
                "tool_name": tool_name,
                "tool_input": tool_input,
                "thought": thought_text,
            }

        # 没有 Action 也没有 Final Answer — 智能判断
        # 如果文本包含实质性中文内容或 Markdown 结构，视为隐式 Final Answer
        if self._looks_like_answer(text):
            return {
                "type": "final_answer",
                "content": text.strip(),
                "thought": "",
            }

        # 确实无法解析
        return {"type": "unknown", "content": text}

    @staticmethod
    def _parse_react_actions(response: str) -> list:
        """P3-2：解析可能含多个 Action 的 ReAct 输出，返回 action 列表。

        每项：{"tool_name": str, "tool_input": dict, "thought": str}。
        仅当拆分出 >=2 个 Action 时返回列表；否则返回 []（由调用方走单 action 顺序路径）。
        Action Input 按 JSON 解析（失败兜底为 {"query": ...}），与 _parse_react_output 一致。
        """
        if not response:
            return []
        parts = re.split(r'\n\s*Action\s*[:：]', response, flags=re.IGNORECASE)
        actions = []
        for p in parts[1:]:
            lines = p.splitlines()
            name = lines[0].strip() if lines else ""
            if not name:
                continue
            im = re.search(r'Action\s*Input\s*[:：]\s*(\{.*?\})', p, re.IGNORECASE | re.DOTALL)
            tool_input = {}
            if im:
                try:
                    tool_input = json.loads(im.group(1).strip())
                except json.JSONDecodeError:
                    tool_input = {"query": im.group(1).strip()}
            else:
                raw = p.strip()
                if raw:
                    tool_input = {"query": raw[:200]}
            actions.append({"tool_name": name, "tool_input": tool_input, "thought": ""})
        return actions if len(actions) >= 2 else []

    def _parse_clarify_questions(self, raw: str) -> list:
        """
        解析 Clarify 后的问题列表。

        期望 JSON 数组：[{"question": "...", "options": ["...", "..."]}]
        容错：剥离 ```json 代码围栏；解析失败则宽松提取单个 question。
        """
        raw = raw.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.IGNORECASE)
        raw = re.sub(r'\s*```$', '', raw).strip()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, list):
            qs = []
            for item in data:
                if isinstance(item, dict) and item.get("question"):
                    qs.append({
                        "question": str(item["question"]),
                        "options": [str(o) for o in item.get("options", [])][:6],
                    })
            if qs:
                return qs[:2]  # 每轮最多 2 个问题
        # 宽松兜底：尝试抓 "question": "xxx"
        m = re.search(r'question\s*[:：]\s*["\']?(.+?)["\']?\s*$', raw, re.IGNORECASE)
        if m:
            return [{"question": m.group(1).strip(), "options": []}]
        return []

    def _looks_like_answer(self, text: str) -> bool:
        """判断文本是否像是一个实质性回答（而非格式错误）。

        D修复：方案/竞品意图下必须显式 Final Answer（上层已优先匹配），此处仅当含 ≥2 个
        ## 章节且无残留 Action/Clarify 时才允许隐式收尾，避免把带 # 的中间思考当终稿吐出。
        """
        if self._intent in ("solution", "competitor"):
            h2 = len(re.findall(r'##\s', text))
            if h2 >= 2 and "Action:" not in text and "Clarify:" not in text:
                return True
            return False
        # 文件操作：回答通常较短（列文件列表/总结要点），无残留 Action/Clarify 即视为答案
        if self._intent == "file_ops":
            return "Action:" not in text and "Clarify:" not in text and len(text.strip()) > 3
        # 产品图谱/架构查询：结构化文字（列表/小标题）即可，无残留 Action/Clarify 即视为答案
        if self._intent == "knowledge_q":
            return "Action:" not in text and "Clarify:" not in text and len(text.strip()) > 20
        # 其它意图（理论上不会到这，general/account/greeting 已在 run 入口短路）
        if re.search(r'#{1,3}\s', text):
            return True
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        if chinese_chars > 20 and len(text) > 100:
            return True
        answer_keywords = ['需求分析', '推荐方案', '核心价值', '产品组合', '实施路径', '下一步']
        keyword_count = sum(1 for kw in answer_keywords if kw in text)
        if keyword_count >= 2:
            return True
        return False

    # ---- 统一增强管线（与标准模式共用）----

    def _collect_context_and_demand(self, tool_calls: list):
        """把 Agent 收集到的工具 observation 格式化为带来源标注的上下文，并提取行业/需求结构化。

        返回的 context 与标准模式 _build_context 风格一致（[资料N | 来源 | 行业 | 类型]），
        供 SolutionMatcherService.generate_enhanced 复用同一套增强 prompt。
        """
        huawei_items = []
        comp_items = []
        industry = ""
        demand_analysis: Dict[str, Any] = {}

        for tc in tool_calls:
            tool = tc.get("tool")
            raw = tc.get("result")
            if not raw:
                continue
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                # 非 JSON 的 observation（罕见）→ 作为华为类参考
                huawei_items.append(("参考", "工具返回", "通用", raw))
                continue

            # analyze_demand 结果 → 提取行业与结构化需求
            if tool == "analyze_demand" and isinstance(data, dict):
                industry = data.get("industry", "") or industry
                if data.get("pain_points") or data.get("scenarios") or data.get("keywords"):
                    demand_analysis = data
                continue

            # search_kb / search_competitor 结果 → 格式化资料
            results = data.get("results", []) if isinstance(data, dict) else []
            for doc in results:
                if not isinstance(doc, dict):
                    continue
                source = doc.get("source", "未知来源")
                doc_industry = doc.get("industry", "")
                doc_type = doc.get("type", "华为云方案")
                # search_competitor 的 type 可能是竞品名；search_kb 无 type → 华为云方案
                typ = "竞品方案" if (doc_type and doc_type != "华为云") else "华为云方案"
                item = (typ, source, doc_industry or "通用", doc.get("content", ""))
                (comp_items if typ == "竞品方案" else huawei_items).append(item)

        # 华为资料排在前（主方案落地），竞品资料排在后（仅第6章对比），统一连续编号
        parts = []
        idx = 0
        for typ, source, doc_industry, content in huawei_items + comp_items:
            if idx >= 12:  # 限制上下文规模，避免多步检索导致膨胀
                break
            idx += 1
            parts.append(
                f"[资料{idx} | 来源:{source} | 行业:{doc_industry} | 类型:{typ}]\n{content}"
            )

        context = "\n\n".join(parts)
        return context, industry, demand_analysis

    async def _finalize_answer(self, user_input: str, draft: str, tool_calls: list, event_callback=None) -> str:
        """用统一增强管线重写最终答案（与标准模式一致：来源标注/防幻觉/话术/结构）。

        B修复要点：
        - 透传 client_context（客户背景/历史方案）给增强管线，使 Agent 终稿与经典模式一致地融合客户上下文；
        - industry 缺失时兜底补跑 analyze_demand，保证行业剧本注入与检索过滤生效；
        - 上下文为空/过薄时触发保底全文检索重建，保证 Agent 最差情况仍 ≥ 标准模式底座，杜绝「吐草稿」。
        format_mode 取自 self._format_mode：solution=14章售前方案书，competitor=轻量对比格式。
        失败（如 LLM 异常）时回退到 Agent 的草稿，保证不阻断主流程。
        """
        # 文件操作意图：不走 14 章方案增强管线，直接返回 ReAct 草稿（文件列表/内容总结）
        if self._intent == "file_ops":
            if event_callback:
                await self._emit(event_callback, {"type": "delta", "text": draft})
            return draft
        # 产品图谱/架构查询：不走方案增强管线（避免被套 14 章模板），直接返回检索后的结构化草稿
        if self._intent == "knowledge_q":
            if event_callback:
                await self._emit(event_callback, {"type": "delta", "text": draft})
            return draft
        try:
            context, industry, demand_analysis = self._collect_context_and_demand(tool_calls)
            # B修复：行业缺失时兜底补跑需求结构化（与标准模式 _prepare 对齐）
            industry, demand_analysis = await self._ensure_demand(user_input, industry, demand_analysis)
            # B修复：上下文过薄（如 LLM 直接 Final Answer 未检索 / 检索为空）→ 保底全文检索重建
            if len(context.strip()) < 200:
                self._log("system", "Agent 上下文过薄，触发保底检索重建上下文")
                context, industry, demand_analysis = await self._fallback_retrieve(user_input, industry, demand_analysis)
            if not context.strip():
                # 完全没有资料 → 不二次生成，直接用草稿
                self._log("system", "Agent 仍未检索到资料，跳过统一增强，使用草稿")
                if event_callback:
                    await self._emit(event_callback, {"type": "delta", "text": draft})
                return draft
            matcher = SolutionMatcherService()

            async def _on_delta(tok):
                await self._emit(event_callback, {"type": "delta", "text": tok})

            # P0 模板降权（2026-08-26）：solution/competitor 也走"agent"自主结构，
            # 不再强制 14 章/对比骨架，消除"模板填充器"包装感；经典模式不受影响（仍用 solution/competitor）。
            agent_format = "agent"
            enhanced = await matcher.generate_enhanced_stream(
                demand=user_input,
                context=context,
                industry=industry,
                demand_analysis=demand_analysis,
                format_mode=agent_format,
                client_context=getattr(self, "_client_context", ""),  # B修复：透传客户背景
                on_delta=_on_delta,
            )
            answer = enhanced["answer"]

            # P0 完整性自检（Evaluator-Optimizer 轻量版）：让 LLM 自查是否覆盖关键元素，缺失则补写。
            # 仅对 solution/competitor 走（file_ops/knowledge_q 已提前返回）；失败静默，不影响主流程。
            answer = await self._self_check_answer(user_input, answer, tool_calls, event_callback)

            self._log("system", "统一增强管线重写完成 (format_mode=agent)")
            return answer
        except Exception as e:
            logger.warning(f"[Agent] 统一增强生成失败，回退草稿并发整段: {e}")
            if event_callback:
                await self._emit(event_callback, {"type": "delta", "text": draft})
            return draft

    def _summarize_tool_result(self, tool_name: str, observation: str) -> str:
        """P0 工具结果摘要：把原始工具输出压成一句话，供前端 tool_end 展示。

        - search_kb / search_competitor：报告检索到几篇 + 最相关来源文件名。
        - read_customer_file / list_dir：报告读取/列出情况。
        - analyze_demand：不摘要（分析过程，前端已有 thought）。
        """
        if not observation:
            return ""
        try:
            data = json.loads(observation) if isinstance(observation, str) else observation
        except (json.JSONDecodeError, TypeError):
            return ""
        if not isinstance(data, dict):
            return ""
        if tool_name in ("search_kb", "search_competitor"):
            results = data.get("results") or []
            if data.get("status") == "no_match":
                return "未检索到匹配资料，正在换关键词重试…"
            if not results:
                return "检索完成，无结果"
            top = results[0].get("source", "") if isinstance(results[0], dict) else ""
            n = len(results)
            if top:
                return f"检索到 {n} 篇资料，最相关：《{top}》"
            return f"检索到 {n} 篇资料"
        if tool_name == "read_customer_file":
            txt = str(data.get("content") or data.get("text") or "")
            n = len(txt)
            return f"已读取文件内容（{n} 字）" if n else "文件内容为空"
        if tool_name == "list_dir":
            files = data.get("files") or []
            n = len(files) if isinstance(files, list) else 0
            return f"目录共 {n} 个文件" if n else "目录为空"
        if tool_name == "web_search":
            # P1-2：联网检索摘要（observation 形如 {status, count, results:[{domain,title,snippet}]}）
            try:
                res = json.loads(observation) if isinstance(observation, str) else observation
            except (json.JSONDecodeError, TypeError):
                return ""
            if res.get("status") == "limited":
                return "已达本会话联网检索上限"
            if res.get("status") == "disabled":
                return "未配置联网搜索，仅基于知识库作答"
            if res.get("status") == "no_draft":
                return "尚无可检索内容"
            n = res.get("count") or len(res.get("results", []) or [])
            return f"联网检索到 {n} 条资料" if n else "联网检索无结果"
        if tool_name == "web_extract":
            # 联网正文抽取摘要
            try:
                res = json.loads(observation) if isinstance(observation, str) else observation
            except (json.JSONDecodeError, TypeError):
                return ""
            if res.get("status") == "disabled":
                return "未配置联网抽取"
            if res.get("status") == "limited":
                return "已达本会话网页抽取上限"
            n = len(str(res.get("content") or ""))
            return f"已抽取网页正文（{n} 字）" if n else "该网页无正文可抽取"
        return ""

    async def _self_check_answer(self, user_input: str, answer: str, tool_calls: list, event_callback=None) -> str:
        """P0 完整性自检：让 LLM 审查方案是否覆盖售前关键元素，缺失则补写（Evaluator-Optimizer 轻量版）。

        检查维度：需求/痛点、方案思路或架构、产品组合、客户价值、下一步建议。
        失败时静默返回原答案，绝不让自检成为阻断点。
        """
        if not answer or len(answer.strip()) < 200:
            return answer
        try:
            from app.models.llm import get_llm_response
            prompt = (
                "你是方案质量审查员。下面是一份已生成的华为云售前方案。请审查它是否覆盖以下关键元素：\n"
                "1. 客户需求/痛点分析\n2. 方案思路或架构\n3. 推荐产品组合\n4. 客户价值\n5. 下一步建议\n\n"
                "如果**缺少其中任意一项**，请只输出【补写内容】这一部分（用 ## 开头），补写缺项、"
                "风格与原方案一致、标注[资料N]或『需进一步核实』（不要重复已有内容）。\n"
                "如果五项都已覆盖，只输出：OK\n\n"
                f"用户需求：{user_input}\n\n"
                f"方案内容：\n{answer[:6000]}\n\n"
                "审查结果："
            )
            review = await get_llm_response(prompt, model=MATCH_LLM_MODEL)
            review = (review or "").strip()
            if review and review != "OK" and "OK" not in review[:4]:
                # 只追加补写部分，不覆盖原方案
                if len(review) > 10 and "补写" not in review and "##" not in review:
                    review = "## 补充说明\n" + review
                answer = answer.rstrip() + "\n\n" + review
                self._log("system", "[自检] 方案缺失元素，已补写")
                if event_callback:
                    await self._emit(event_callback, {"type": "delta", "text": "\n\n" + review})
            else:
                self._log("system", "[自检] 方案完整，无需补写")
        except Exception as e:
            self._log("error", f"[自检] 失败，跳过: {e}")
        return answer

    # ─────────────────── P3-3：自检 Gate（质量闸门） ───────────────────
    async def _self_check_gate(
        self, answer: str, user_input: str, event_callback=None, tool_calls: list = None,
    ) -> tuple:
        """P3-3 硬质量闸门：critic LLM 按 rubric 验收终稿（draft 阶段，finalize 之前）。

        tool_calls：本次真实工具调用记录（[{tool, input, result}, ...]）。注入 critic 提示词后，
        「是否调用过某工具/数据是否有据可查」按真实记录判定，消除"工具已调用但正文没提工具名
        就被判未调用"的误判。

        返回 (answer, quality_warn)：
          - 通过 → 原 answer，quality_warn=False；
          - 不通过且在迭代上限内 → 用 patch_hint 二次合成（不重跑工具、不流式），返回修订稿，quality_warn=False；
          - 达上限仍不过 → 返回最后一次稿，quality_warn=True（不阻断用户，稳定性铁律）。
        异常 → 静默返回原 answer，quality_warn=False（自检永不阻断）。
        """
        self._quality_warn = False
        enabled = (AGENT_SELF_CHECK or "1").strip() == "1"
        if not enabled or not answer or len(answer.strip()) < 200:
            return answer, False
        try:
            from app.models.llm import get_llm_response
            mention_competitor = bool(SUPPORTED_COMPETITORS and any(
                c.lower() in (user_input or "").lower() for c in SUPPORTED_COMPETITORS
            ))
            rubric = (
                "1. 需求/痛点覆盖\n2. 方案思路或架构\n3. 推荐产品组合"
                + ("\n4. 竞品对比（用户提到了友商，必须含华为云 vs 友商对比）" if mention_competitor else "")
                + "\n5. 无幻觉/有据可查\n6. 结构完整可执行"
            )
            # 真实工具调用记录：让 critic 按系统记录核对，而非凭正文里有没有工具名瞎猜
            tool_block = ""
            if tool_calls:
                lines = []
                for t in tool_calls[-12:]:
                    name = str(t.get("tool", "") or "")
                    res = str(t.get("result", "") or "").replace("\n", " ")[:120]
                    lines.append(f"- {name}：{res}")
                tool_block = (
                    "【本次实际调用过的工具（系统真实记录）】\n" + "\n".join(lines)
                    + "\n\n判定规则（重要）：上表是工具调用的真实记录。判断『是否调用过某工具』"
                    "『数据是否有据可查』必须以本记录为准，不得仅因方案正文未出现工具名、"
                    "或未声明『工具返回』就判定未调用。若记录显示工具确已调用并返回了结果，"
                    "则该维度视为达标，不得据此判 fail。"
                )
            current = answer
            for it in range(1, SELF_CHECK_MAX_ITERS + 1):
                critic_prompt = (
                    "你是售前方案质量审查员，按以下 rubric 逐维度判断方案是否覆盖要点。\n"
                    f"Rubric：\n{rubric}\n\n"
                    "评分原则（重要）：\n"
                    "- 评分依据『维度要点是否被覆盖』，而非篇幅长短。一份结构完整、各维度要点均已体现的方案"
                    "（即使表述简练）应判 pass=true，score 给 80-95。\n"
                    "- 仅当存在明确缺失的维度（如完全没提推荐产品、或用户提了友商却无任何对比）时才判"
                    "pass=false，并在 gaps 中列出具体缺失维度。\n"
                    "只输出 JSON（不要其它文字）：\n"
                    '{"pass": true|false, "score": 0-100, "gaps": ["缺失维度1", ...], '
                    '"patch_hint": "如何补强的简要指引"}\n\n'
                    f"用户需求：{user_input}\n\n"
                    f"待审查方案：\n{current[:6000]}\n\n"
                    f"{tool_block}\n\n"
                    "审查结果 JSON："
                )
                raw = await get_llm_response(critic_prompt, model=MATCH_LLM_MODEL)
                verdict = self._parse_self_check_verdict(raw)
                passed = bool(verdict.get("pass")) and verdict.get("score", 0) >= SELF_CHECK_PASS
                await self._emit(event_callback, {
                    "type": "self_check",
                    "gate": "pass" if passed else "fail",
                    "score": verdict.get("score", 0),
                    "gaps": verdict.get("gaps", []),
                    "iter": it,
                    "max_iters": SELF_CHECK_MAX_ITERS,
                })
                if passed:
                    self._log("system", f"[P3-3 自检] 通过 score={verdict.get('score')}")
                    return current, False
                # 不通过 → 二次合成（非流式、不重跑工具）
                self._log("system", f"[P3-3 自检] 第{it}次未过 score={verdict.get('score')}，二次合成")
                hint = verdict.get("patch_hint", "") or "；".join(verdict.get("gaps", []))
                revise_prompt = (
                    "你是华为云售前方案撰写官。下面是一份方案，审查指出它存在以下不足，请据此修订为完整终稿。\n"
                    "要求：①保留已达标的维度，只补强指出的不足；②不要大幅扩写无关内容，修订稿篇幅控制在"
                    "原方案的 1.2 倍以内（建议 1500-3500 字）；③风格一致，涉及具体数据标注[资料N]或『需进一步核实』。\n"
                    f"不足与修补指引：{hint}\n\n"
                    f"用户需求：{user_input}\n\n"
                    f"原方案：\n{current[:4000]}\n\n"
                    "修订后完整方案："
                )
                revised = await self._call_llm(revise_prompt)
                revised = (revised or "").strip()
                if revised:
                    current = revised
                else:
                    # 二次合成失败，保留原稿并标记 warn
                    self._quality_warn = True
                    return current, True
            # 达上限仍不过
            self._quality_warn = True
            await self._emit(event_callback, {
                "type": "self_check", "gate": "warn", "score": verdict.get("score", 0),
                "gaps": verdict.get("gaps", []), "iter": SELF_CHECK_MAX_ITERS, "max_iters": SELF_CHECK_MAX_ITERS,
            })
            self._log("system", f"[P3-3 自检] 达上限仍不过，放行并附 quality_warn")
            return current, True
        except Exception as e:
            self._log("error", f"[P3-3 自检] 异常跳过: {e}")
            return answer, False

    @staticmethod
    def _parse_self_check_verdict(raw: str) -> dict:
        """从 critic 回复中解析 {pass, score, gaps, patch_hint} JSON，容错。"""
        if not raw:
            return {"pass": True, "score": SELF_CHECK_PASS, "gaps": [], "patch_hint": ""}
        text = raw.strip()
        # 优先定位第一个 { 到最后一个 } 的 JSON 段
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            try:
                data = json.loads(text[s:e + 1])
                if isinstance(data, dict):
                    data["pass"] = str(data.get("pass", "")).strip().lower() in ("true", "1", "yes")
                    try:
                        data["score"] = int(float(data.get("score", SELF_CHECK_PASS)))
                    except (TypeError, ValueError):
                        data["score"] = SELF_CHECK_PASS
                    data["gaps"] = data.get("gaps") or []
                    data["patch_hint"] = data.get("patch_hint", "") or ""
                    return data
            except (json.JSONDecodeError, TypeError):
                pass
        # 退化：含 "OK"/"通过" 视为通过
        ok = any(k in text for k in ("OK", "通过", "合格", "pass"))
        return {"pass": ok, "score": SELF_CHECK_PASS if ok else 0, "gaps": [], "patch_hint": ""}

    async def _ensure_demand(self, user_input: str, industry: str, demand_analysis: Dict[str, Any]) -> tuple:
        """B修复：行业缺失时兜底补跑 analyze_demand，保证行业剧本注入与检索过滤生效。"""
        if industry:
            return industry, demand_analysis
        try:
            raw = await _tool_analyze_demand(user_input)
            j = raw.find("{")
            k = raw.rfind("}") + 1
            if j >= 0 and k > j:
                d = json.loads(raw[j:k])
                industry = d.get("industry", "") or industry
                if d.get("pain_points") or d.get("scenarios") or d.get("keywords"):
                    demand_analysis = d
        except Exception as e:
            logger.warning(f"[Agent] 兜底需求结构化失败（跳过）: {e}")
        return industry, demand_analysis

    async def _fallback_retrieve(self, user_input: str, industry: str, demand_analysis: Dict[str, Any]) -> tuple:
        """B修复：保底全文检索。当 Agent 中途未检索到足够资料时，用需求原文（+行业过滤）取
        全文资料重建上下文，保证终稿底座至少等于标准模式；若需求/关键词提及竞品则补充竞品资料。"""
        kb = _get_kb()
        huawei_items = []
        try:
            hw_docs = await to_thread_limited(kb.search_huawei, user_input, 6, filter_industry=(industry or None))
        except Exception as e:
            logger.warning(f"[Agent] 保底检索华为失败: {e}")
            hw_docs = []
        for doc in hw_docs[:6]:
            meta = getattr(doc, "metadata", {}) or {}
            huawei_items.append(("华为云方案", meta.get("source", "未知来源"), meta.get("industry", "") or "通用", doc.page_content))

        # 竞品资料：需求原文或关键词提及竞品时补充
        pool = [user_input]
        if isinstance(demand_analysis, dict):
            pool += [str(x) for x in demand_analysis.get("keywords", [])]
        pool_text = " ".join(pool).lower()
        comp_names = [c for c in SUPPORTED_COMPETITORS if c.lower() in pool_text]
        comp_items = []
        for c in comp_names:
            try:
                comp_docs = await asyncio.to_thread(kb.search_competitor, f"{c} 解决方案", 6)
            except Exception:
                comp_docs = []
            for doc in comp_docs[:6]:
                meta = getattr(doc, "metadata", {}) or {}
                comp_items.append((c, meta.get("source", "未知来源"), meta.get("industry", "") or "通用", doc.page_content))

        parts = []
        idx = 0
        for typ, source, doc_industry, content in huawei_items + comp_items:
            if idx >= 12:
                break
            idx += 1
            parts.append(f"[资料{idx} | 来源:{source} | 行业:{doc_industry} | 类型:{typ}]\n{content}")
        context = "\n\n".join(parts)
        return context, industry, demand_analysis

    # ---- 兜底方案 ----

    async def _generate_fallback(self, user_input: str) -> str:
        """当 Agent 循环失败时，用增强模板直接生成（结构与意图对齐：方案=14章 / 竞品=对比格式）"""
        from app.models.llm import get_llm_response

        format_block = build_compare_block() if getattr(self, "_format_mode", "solution") == "competitor" else build_format_block()
        prompt = (
            "你是华为云解决方案专家。用户提出了以下需求，请直接给出完整方案建议。\n\n"
            f"用户需求：{user_input}\n\n"
            + build_anti_hallucination()
            + build_audience_tone()
            + format_block
        )

        try:
            return await get_llm_response(
                prompt,
                model=getattr(self, "_run_model", None) or MATCH_LLM_MODEL,
            )
        except Exception:
            return "抱歉，当前服务暂时不可用，请稍后重试。如问题持续，请联系管理员。"

    # ───────────────────────── P1-2：导出文档拦截 ─────────────────────────

    async def _intercept_generate_doc(self, fmt: str, event_callback=None) -> str:
        """P1-2：导出文档工具的实际执行（generate_doc 拦截 / export 意图复用）。

        直接取 self._last_draft（增强后终稿）+ self._format_mode（决定 report_type），
        复用 ReportGeneratorService 生成 Word/PDF，返回 JSON 字符串（与工具 observation 一致）。
        无终稿时返回友好提示（不报错，不阻断）。
        """
        draft = getattr(self, "_last_draft", "")
        if not draft or len(draft.strip()) < 30:
            return json.dumps({
                "status": "no_draft",
                "message": "当前还没有可导出的方案内容，请先让我为你生成一份方案，再点「导出方案书」或说「导出成 Word」。",
            }, ensure_ascii=False)
        from app.agent.tools import _tool_generate_doc
        try:
            # 把缓存终稿注入 content；report_type 由 _format_mode 决定（solution/competitor）
            obs = await _tool_generate_doc(fmt, content=draft, report_type=self._format_mode)
        except Exception as e:
            logger.error(f"[generate_doc] 导出失败: {e}")
            return json.dumps({"status": "error", "message": f"方案书生成失败：{e}"}, ensure_ascii=False)
        # obs 已是 {status, download_url, file_name, task_id} 或 {error}
        try:
            data = json.loads(obs) if isinstance(obs, str) else obs
        except (json.JSONDecodeError, TypeError):
            data = {}
        if data.get("status") == "ok" and data.get("download_url"):
            # 通过 SSE 额外推送 doc_generated 事件，前端渲染下载 chip
            if event_callback:
                await self._emit(event_callback, {
                    "type": "doc_generated",
                    "download_url": data.get("download_url"),
                    "file_name": data.get("file_name"),
                    "fmt": fmt,
                })
        return obs

    # ───────────────────────── P1-3：Reflexion 反思 ─────────────────────────

    def _record_trajectory(self, thought: str, tool_name: str, observation: str) -> None:
        """P1-3：把最近一步的 (thought, action, observation) 摘要追加到执行轨迹，
        供 _reflexion_retry 反思使用（只保留最近 ~1200 字，防止过长）。"""
        snippet = f"[思考] {thought[:120]}\n[动作] {tool_name}\n[观察] {observation[:200]}\n"
        self._last_trajectory = (self._last_trajectory + snippet).strip()
        if len(self._last_trajectory) > 1200:
            self._last_trajectory = self._last_trajectory[-1200:]

    async def _reflexion_retry(self, event_callback=None) -> str:
        """P1-3：基于最近执行轨迹让 LLM 反思「哪里不对/如何调整」，返回反思文本（空串=失败）。

        轻量实现（不嵌套执行、不破坏 ReAct 主循环）：只生成自然语言调整建议，
        由调用方（action 分支）把文本追加到 current_prompt，下一轮 LLM 读到后自我纠正；
        max_steps 耗尽分支调用时则仅 emit 事件 + 记 metric（无 current_prompt 可拼接）。
        受 max_steps 保护（正常路径走主循环），不无限递归。
        """
        trajectory = getattr(self, "_last_trajectory", "")
        if not trajectory:
            return ""
        try:
            from app.models.llm import get_llm_response
            prompt = (
                "你刚才在执行任务时连续遇到困难或已达到步数上限。下面是最近的执行轨迹：\n"
                f"{trajectory}\n\n"
                "请反思：信息是否不足？参数是否错误？下一步应如何调整才能推进任务？"
                "只输出 2-4 句具体、可执行的调整建议（不要输出 Final Answer，也不要输出 Action 格式）。"
            )
            reflect = await get_llm_response(prompt, model=MATCH_LLM_MODEL)
            reflect = (reflect or "").strip()
            if not reflect:
                return ""
            self._reflexion_count += 1
            self._reflexion_success = True
            if event_callback:
                await self._emit(event_callback, {"type": "reflexion", "text": reflect})
            self._log("system", "[Reflexion] 反思注入成功")
            return reflect
        except Exception as e:
            logger.warning(f"[Reflexion] 反思失败（跳过）: {e}")
            return ""

    @staticmethod
    def _parse_plan_v2(raw: str) -> list:
        """从 planner 回复中解析修订计划（JSON 字符串数组），容错。"""
        if not raw:
            return []
        text = raw.strip()
        s, e = text.find("["), text.rfind("]")
        if s >= 0 and e > s:
            try:
                data = json.loads(text[s:e + 1])
                if isinstance(data, list):
                    return [str(x).strip() for x in data if str(x).strip()]
            except (json.JSONDecodeError, TypeError):
                pass
        # 退化：按行拆分非空项
        items = [ln.strip().lstrip("0123456789.、-").strip() for ln in text.splitlines() if ln.strip()]
        return items

    async def _reflexion_replan(
        self, event_callback, session_id: str, tool_calls_log: list,
    ) -> Optional[str]:
        """P3-1 真反思-重规划：替代 P1-3 软重试。

        触发前提：调用方已确认存在失败步（_step_results 含 'Error:'）。本方法：
          1. 读取失败步摘要；
          2. 调 planner LLM 产出修订计划（plan_v2，长度与原 plan 一致，仅替换失败步文本）；
          3. 对失败步用 _execute_step 重跑（复用角色/工具集，成功步结果保留）；
          4. emit plan(plan_version=2) + reflexion(replanned=True) + step_done；
          5. 重新 _synthesize_final 汇总，返回新终稿。
        异常/超限 → 返回 None（由调用方回退常规汇总或旧软重试路径，稳定性铁律）。
        """
        replan_enabled = (AGENT_REFLEXION_REPLAN or "1").strip() == "1"
        if not replan_enabled:
            return None
        if self._replan_count >= REFLEXION_MAX_REPLANS:
            self._log("system", "[P3-1 重规划] 已达 REFLEXION_MAX_REPLANS 上限，跳过")
            return None
        failed = [i for i in range(len(self._plan)) if "Error:" in (self._step_results.get(i, "") or "")]
        if not failed:
            return None
        try:
            self._replan_count += 1
            summary = "；".join(
                f"第{i + 1}步失败：{(self._step_results.get(i, '') or '')[:120]}" for i in failed
            )
            self._log("system", f"[P3-1 重规划] 触发（第{self._replan_count}次）：{summary}")
            # 反思事件（前端显示「重规划中」）
            await self._emit(event_callback, {
                "type": "reflexion",
                "text": f"检测到 {len(failed)} 个步骤执行失败，已重规划并重跑失败步：{summary}",
                "replanned": True,
                "plan_version": 2,
            })
            # planner LLM → 修订计划（仅替换失败步文本，长度保持与原 plan 一致，前端安全）
            planner_prompt = (
                "你是任务规划师。以下方案执行中部分步骤失败，请根据原始需求与失败摘要，"
                "针对【失败步骤】给出修订后的单步目标（一句），其余步骤保持不变。\n"
                f"原始需求：{self._plan_original_input or ''}\n"
                f"失败步骤摘要：{summary}\n\n"
                "只输出 JSON 字符串数组，元素数量等于失败步骤数，每个元素是一句修订后的步骤目标。"
                "例如：[\"重新检索制造业ERP上云资料（换用关键词）\", \"基于资料撰写方案\"]"
            )
            try:
                pv_raw = await self._call_llm(planner_prompt)
                pv = self._parse_plan_v2(pv_raw)
            except Exception as e:
                self._log("warn", f"[P3-1] planner 失败（用原步文本重跑）: {e}")
                pv = []
            plan_v2 = list(self._plan)
            for k, i in enumerate(failed):
                if k < len(pv):
                    plan_v2[i] = pv[k]
            # emit plan(plan_version=2) + 重新点亮 plan_status（成功步保持 done）
            status_v2 = ["done" if i not in failed else "pending" for i in range(len(self._plan))]
            await self._emit(event_callback, {
                "type": "plan", "plan": plan_v2, "plan_status": status_v2, "plan_version": 2,
            })
            # 重跑失败步（复用角色/工具集）
            for i in failed:
                self._mark_plan_status(i, "pending")
                role = None
                if self._multi_agent_enabled and self._intent in ("solution", "competitor"):
                    from app.agent.agents import get_role
                    role = get_role(i)
                toolset = list(role["tools"]) if role else (
                    list(self.PLAN_STEP_TOOL_MAP.get(self._intent, [])[i])
                    if i < len(self.PLAN_STEP_TOOL_MAP.get(self._intent, [])) else []
                )
                # P2-3：远端 MCP 工具作为每步的「逃生舱」
                if self._remote_tool_names:
                    toolset = toolset + self._remote_tool_names
                obs = await self._execute_step(
                    i, plan_v2[i], toolset, event_callback, session_id, tool_calls_log,
                    role_prompt=role["prompt"] if role else None,
                )
                if obs is None:
                    # 重跑步要求澄清 → 放弃该步重规划（保留原失败结果，不阻断）
                    self._log("warn", f"[P3-1] 第{i + 1}步重跑触发澄清，放弃重规划")
                    self._mark_plan_status(i, "done")
                    continue
                self._step_results[i] = obs
                self._mark_plan_status(i, "done")
                await self._emit(event_callback, {
                    "type": "step_done", "step_index": i, "summary": "重规划重跑完成",
                })
            # 重新汇总
            step_outputs = [self._step_results.get(i, "") for i in range(len(self._plan))]
            final = await self._synthesize_final(
                self._plan_original_input or "", self._plan, step_outputs, event_callback,
            )
            self._last_replanned = True
            return final
        except Exception as e:
            self._log("error", f"[P3-1 重规划] 异常降级: {e}")
            return None

    # ───────────────────────── 账户数据真实取数 ─────────────────────────
    def _classify_account_subtype(self, text: str) -> str:
        """账户类问题细分：成就 / 我的方案 / 收藏 / 总览 / 账户信息。

        优先级：成就 > 收藏 > 方案 > 总览(概况/整体/总览) > 账户信息。
        「概况/整体/总览」置于账户信息之前，使「我的账号整体概况」走汇总而非单条资料。
        """
        t = (text or "").lower()
        if any(k in t for k in ["成就", "徽章", "勋章", "解锁", "点亮", "achievement"]):
            return "achievements"
        if any(k in t for k in ["收藏", "收藏夹", "favorite", "favourite"]):
            return "favorites"
        if any(k in t for k in [
            "方案", "我的方案", "历史方案", "生成过", "做过", "匹配记录",
            "历史匹配", "导出", "下载", "solution",
        ]):
            return "solutions"
        if any(k in t for k in ["概况", "整体", "总览", "概览", "overview"]):
            return "overview"
        if any(k in t for k in [
            "账户", "资料", "信息", "用户名", "邮箱", "注册", "我的资料",
            "profile", "账号",
        ]):
            return "profile"
        return "overview"

    async def _handle_account_query(self, user_input: str) -> str:
        """账户意图：从后端真实读取当前登录用户的数据，生成自然语言回复。

        子类型（_classify_account_subtype）：
        - achievements：成就/徽章（achievement_service）
        - solutions：我的方案/历史匹配（usage_logger.match_history）
        - favorites：收藏（auth_service.favorites）
        - profile：账户信息（路由传入的 user_info）
        - overview：以上汇总

        未登录（user_id 为空）→ 诚实提示先登录，不编造。
        """
        uid = self._user_id
        if not uid:
            return (
                "你还没有登录，我无法读取你的账户数据。\n"
                "请先在页面右上角登录你的账号，登录后我就能帮你查询"
                "成就、我的方案、收藏和账户信息啦。"
            )

        sub = self._classify_account_subtype(user_input)

        try:
            if sub == "achievements":
                return self._fmt_achievements(uid)
            if sub == "favorites":
                return self._fmt_favorites(uid)
            if sub == "solutions":
                return self._fmt_solutions(uid)
            if sub == "profile":
                return self._fmt_profile()
            # overview：汇总一份轻量概览
            return self._fmt_overview(uid)
        except Exception as e:  # 取数异常兜底，不暴露内部错误
            logger.warning(f"[Agent] 账户数据取数失败(uid={uid}, sub={sub}): {e}")
            return (
                "读取你的账户数据时出了点小问题，请稍后重试。\n"
                "你也可以直接前往页面顶部「我的」查看成就、方案与收藏。"
            )

    def _fmt_achievements(self, uid: int) -> str:
        from app.services.achievement_service import get_achievement_service
        svc = get_achievement_service()
        items = svc.get_user_achievements(uid)
        stats = svc.get_user_stats(uid)
        unlocked = [it for it in items if it.get("unlocked")]
        lines = []
        lines.append(
            f"你已解锁 {stats.get('unlocked', 0)} / 共 {stats.get('total', 0)} 个成就"
            f"（完成度 {stats.get('percent', 0)}%）。"
        )
        if unlocked:
            lines.append("")
            lines.append("已解锁的成就：")
            for it in unlocked:
                lines.append(
                    f"- {it.get('name', '???')}（{it.get('rarity_name', '')}）："
                    f"{it.get('description', '')}"
                )
        else:
            lines.append("")
            lines.append("你还没有解锁任何成就，多在平台里匹配方案、查看资讯就能解锁哦～")
        lines.append("")
        lines.append("（完整成就墙与进度请前往「我的」→「成就」查看）")
        return "\n".join(lines)

    def _fmt_favorites(self, uid: int) -> str:
        from app.services.auth_service import AuthService
        favs = AuthService.get_favorites(uid, page=1, page_size=20)
        if not favs:
            return (
                "你目前还没有收藏任何方案。\n"
                "在方案详情页点击「收藏」即可把心仪的华为云方案存到这里，"
                "之后在「我的」→「收藏」随时查看。"
            )
        lines = [f"你收藏了 {len(favs)} 个方案："]
        for f in favs:
            name = f.get("solution_name") or "未命名方案"
            ind = f.get("industry") or "通用"
            lines.append(f"- {name}（{ind}）")
        lines.append("")
        lines.append("（前往「我的」→「收藏」可查看完整内容或取消收藏）")
        return "\n".join(lines)

    def _fmt_solutions(self, uid: int) -> str:
        from app.services.usage_logger import get_usage_logger
        ul = get_usage_logger()
        total = ul.get_match_history_count(user_id=uid)
        recents = ul.get_match_history_list(limit=8, user_id=uid)
        if not total:
            return (
                "你目前还没有生成过方案。\n"
                "告诉我你的**行业 + 场景 + 规模**，我来帮你匹配一份华为云解决方案～"
            )
        lines = [f"你当前共有 {total} 份历史方案。最近几份："]
        for i, r in enumerate(recents, 1):
            title = r.get("title") or r.get("demand_text") or "未命名方案"
            title = (title[:40] + "…") if len(title) > 41 else title
            ind = r.get("industry") or "通用"
            ts = (r.get("created_at") or "")[:10]
            lines.append(f"{i}. {title}（{ind}）— {ts}")
        lines.append("")
        lines.append(
            "这些方案都保存在「我的」→「我的方案」里，支持查看、编辑、下载与对比。"
            "需要导出时，在「我的方案」里选择方案后点击「下载」即可导出为文档。"
        )
        return "\n".join(lines)

    def _fmt_profile(self) -> str:
        u = self._user_info or {}
        if not u:
            return (
                "你的登录信息暂时获取不到，请刷新页面或重新登录后重试。\n"
                "（账户信息也可在「我的」→「账户」查看）"
            )
        lines = ["你的账户信息："]
        lines.append(f"- 用户名：{u.get('username', '—')}")
        if u.get("email"):
            lines.append(f"- 邮箱：{u.get('email')}")
        role = u.get("role", "user")
        role_cn = "管理员" if role == "admin" else "普通用户"
        lines.append(f"- 角色：{role_cn}")
        if u.get("created_at"):
            lines.append(f"- 注册时间：{str(u.get('created_at'))[:19]}")
        if u.get("last_login"):
            lines.append(f"- 最近登录：{str(u.get('last_login'))[:19]}")
        lines.append("")
        lines.append("（修改邮箱/密码请在「我的」→「账户」操作）")
        return "\n".join(lines)

    def _fmt_overview(self, uid: int) -> str:
        from app.services.achievement_service import get_achievement_service
        from app.services.auth_service import AuthService
        from app.services.usage_logger import get_usage_logger
        svc = get_achievement_service()
        stats = svc.get_user_stats(uid)
        favs = AuthService.get_favorites(uid, page=1, page_size=1)
        fav_count = len(favs)
        ul = get_usage_logger()
        total = ul.get_match_history_count(user_id=uid)
        lines = ["这是你账户的当前概况："]
        lines.append(f"- 成就：已解锁 {stats.get('unlocked', 0)} / {stats.get('total', 0)}"
                     f"（完成度 {stats.get('percent', 0)}%）")
        lines.append(f"- 我的方案：共 {total} 份")
        lines.append(f"- 收藏：共 {fav_count} 个")
        u = self._user_info or {}
        if u.get("username"):
            lines.append(f"- 账号：{u.get('username')}")
        lines.append("")
        lines.append("想看具体哪一类？告诉我「我的成就 / 我的方案 / 我的收藏 / 我的资料」即可。")
        return "\n".join(lines)

    def _generate_light_reply(self, intent: str, user_input: str) -> str:
        """账户/纯礼节意图的轻量回复（不走 LLM、不检索、不套模板）。

        - account：诚实说明能力边界，指路「我的」页
        - greeting：极短礼节回复
        """
        if intent == "account":
            return (
                "## 关于你的账户\n\n"
                "我是**方案匹配助手**，专注帮你匹配华为云解决方案，无法直接读取你的账户数据"
                "（成就 / 收藏 / 历史方案）。\n\n"
                "- **成就 / 徽章**：请前往页面顶部「我的」→「成就」查看。\n"
                "- **我的方案 / 收藏 / 历史匹配**：请在「我的」页面查看。\n\n"
                "如果你有具体的业务需求想匹配华为云方案，告诉我**行业 + 场景 + 规模**，我帮你生成方案。"
            )
        if intent == "greeting":
            # 极短礼节回复：基于输入类型给一个友好回应，不背稿
            t = (user_input or "").strip()
            low = t.lower()
            if any(c in t for c in ["谢谢", "感谢", "辛苦了", "多谢"]):
                return "不客气～有方案匹配需求随时找我 👋"
            if any(c in t for c in ["晚安", "再见", "拜拜", "下次聊"]):
                return "好的，下次聊～有方案需要随时来 👋"
            # 普通你好/hi
            return "你好呀～我是华为云解决方案匹配助手，有什么想匹配的需求告诉我？"
        # 兜底（不该到这里，保留旧的自我介绍模板避免异常暴露）
        return (
            "## 你好\n\n"
            "我是华为云解决方案智能匹配助手，可以帮你：\n"
            "- 根据**行业 + 场景**匹配最合适的华为云解决方案\n"
            "- 对比**华为云与主流竞品**（阿里云 / 腾讯云 / AWS 等）的优劣势\n"
            "- 给出**产品组合、实施路径与商务建议**\n\n"
            "告诉我你的业务需求，我们从方案匹配开始。"
        )

    @staticmethod
    def _build_search_query(user_input: str, last_query: str = "") -> str:
        """从口语输入构造检索词（2026-09-07）：整句口语直接喂搜索引擎会搜回无关结果
        （实测'你联网去搜索相关材料'/'能根据华为云最新消息给我整理一份文档吗'）。

        三级策略：
        1. 主题提取：命中"根据/关于/围绕 X + 动词"句式 → 取 X（剥指代词）
        2. 前缀/元词剥离：剥口语前缀与"整理/文档/材料"类元词，剩核心词≥3字就用
        3. 元请求兜底：剥完为空（纯"你联网去搜索相关材料"类）→ 复用上次检索词
        """
        q = (user_input or "").strip()
        # 1) 主题提取
        m = re.search(r"(?:根据|关于|围绕|就)\s*([^，。？?!，。？！]{2,30}?)(?:整理|搜索|写|生成|查|做|出|汇总)", q)
        if not m:
            # "把(刚才/这份/那份)X整理成/转成..."句式（模型引导的指令常为此形态）
            m = re.search(r"把(?:刚才|这份|那份|上面)?的?([^，。？?!，。？！的]{2,20}?)(?:整理|转换?|做成?|生成|导出|汇总)", q)
        if m:
            topic = re.sub(r"^(刚才|刚刚|上面|以上|最新的?|相关|这些|那些|这份|那份)", "", m.group(1)).strip()
            topic = re.sub(r"(给我|帮我|请|麻烦|一下|的最新?|的新闻|的消息|的动态|的信息)+$", "", topic).strip()
            if len(topic) >= 2:
                return topic
        # 2) 前缀与元词剥离
        q2 = re.sub(r"^(帮我|请|麻烦|你|您|先|给我|去|再|帮忙|能不能|可以|把)+", "", q).strip()
        q2 = re.sub(r"^(刚才|这份|那份|上面)+(的)?", "", q2).strip()
        q2 = re.sub(r"^(联网|搜索|搜一下|搜搜|查一下|查查)+", "", q2).strip()
        core = re.sub(
            r"(整理|总结|文档|摘要|成文|一份|相关|材料|资料|搜索|联网|查一下|搜一下"
            r"|最新的?|消息|新闻|动态|信息|导出|并|成|ppt|pptx|word|pdf|吗|吧|呢|么)",
            "", q2, flags=re.I,
        ).strip()
        if len(core) >= 3:
            return q2[:120]
        # 3) 元请求兜底：有上次主题就复用；没有则返回空串（调用方跳过搜索，让模型正常追问主题）
        return (last_query or "").strip()

    async def _compose_web_article(self, user_input: str, session_id: str, web_results_text: str) -> str:
        """把本会话最近的联网检索素材撰写成一篇结构完整的文章（供导出链路成 doc）。

        铁律：只用检索素材里的事实，不编造数字与细节；素材不足用概述带过。
        失败返回空串，调用方走兜底话术（不阻断）。
        """
        from app.models.llm import get_llm_response
        history = self.memory.get_conversation_history(session_id) or ""
        prompt = (
            "你是售前资料撰稿人。基于下面提供的联网检索素材，撰写一篇结构完整的中文文章：\n"
            "- 必须有一个 Markdown 一级标题（# ）和 3-5 个二级小节（## ）\n"
            "- 开头一段导语概括主题，结尾一段小结\n"
            "- 只使用素材中出现的事实与数字，严禁编造素材里没有的细节；\n"
            "  素材不足的部分用概述性语言带过，不要虚构\n"
            "- 篇幅 800-1500 字，语气客观专业\n\n"
            f"【对话上下文（理解用户意图用）】\n{history[:1500]}\n\n"
            f"【联网检索素材（唯一事实来源）】\n{web_results_text[:6000]}\n\n"
            f"【用户要求】{user_input}\n\n直接输出文章正文，不要任何解释。"
        )
        try:
            article = await get_llm_response(prompt)
            return str(article or "").strip()
        except Exception as e:
            self._log("warn", f"联网素材成文失败（忽略）: {e}")
            return ""

    async def _answer_general_chat(self, user_input: str, session_id: str,
                                   extra_context: str = "", web_results: str = "") -> str:
        """通用问答（算数/常识/自我介绍/"你能做什么"等）：调 LLM 直接回答。

        关键能力：
        - 多轮上下文：注入 `get_conversation_history(session_id)`，让追问能用上前面
        - 长程记忆/客户上下文：注入 extra_context（系统检索的记忆块，带防矛盾措辞），
          否则用户问"翻一下记忆"时模型会按诚信红线否认真实存在的记忆
        - 防止驴头不对马嘴：明确禁止套方案模板，要求「先答用户问题，再补一句方案能力」
        - 失败安全兜底（LLM 超时/异常）：返回一个简洁自我介绍
        """
        from app.models.llm import get_llm_response

        history = self.memory.get_conversation_history(session_id) or "（这是第一次对话）"
        memory_block = ""
        if extra_context and extra_context.strip():
            memory_block = (
                "【系统检索到的记忆与客户上下文（以下是真实数据，不是你的编造；"
                "用户问起历史需求/记忆时可放心引用；与问题无关就忽略）】\n"
                f"{extra_context.strip()}\n\n"
            )
        web_block = ""
        if web_results and web_results.strip():
            web_block = (
                "【联网检索结果·刚刚实时搜索所得（真实有效的最新信息，回答时应优先引用并注明来源）】\n"
                f"{web_results.strip()}\n\n"
            )
        prompt = (
            "你是华为云解决方案智能匹配助手，也是一个有见识、有温度的聊天对象。下面是用户与你的多轮对话历史。\n"
            "【关键】用户当前问的不一定是方案问题，可能是算数/常识/概念/自我介绍等通用问询。\n"
            "回答原则：\n"
            "1) 像一个博学又接地气的朋友在聊天，不是客服窗口。**长度跟着问题走**：闲聊、讲历史、"
            "聊常识、聊图片都可以自然展开——有细节、有背景、有你自己的视角，两三段完全没问题；"
            "只有用户明确要简短（\"一句话\"\"简单说\"）时才收着说。**禁止**默认电报式的三五句话冷回答。\n"
            "2) 如果问题与方案匹配无关（如「1+1等于几」「Python 是什么」），**只回答问题本身**，不要强行推销方案能力。\n"
            "3) 像正常大模型聊天一样自然回答：纯闲聊、游戏、娱乐、常识、情感化问题**完全不要**"
            "加任何推广、过渡或能力介绍尾巴（不要出现「如果你有…需求可以告诉我」「我来帮你匹配方案」这类话）；"
            "只有当用户的问题与云计算/企业数字化有自然关联时，才顺带提一句方案能力。\n"
            "4) 口吻自然、有态度、可以带点幽默和温度；别用公文腔、总结陈词腔和客服腔；"
            "可以在回答里自然延伸一个相关的冷知识或观点，让对话有来有往。避免「我是华为云助手，根据行业+场景匹配…」这种固定模板式开场。\n"
            "5) 【数据诚信红线】凡系统注入的记忆/上下文块中**明确写出**的历史需求与客户信息，可以"
            "直接引用作答；块中**没有**的客户档案内容、历史方案、实时报价、知识库文档数等数据"
            "**绝对不要编造**，应如实说明并引导用户换明确问法来触发对应功能"
            "（如「把XX存成客户」「查一下XX的档案」「50台4核8G的ECS用3个月多少钱」）。\n"
            "6) 【不拽业务】用户自我介绍、聊人际、聊日常时，像朋友一样自然回应即可，"
            "**不要**主动引导「存成客户档案」「查客户档案」，一次都不要提；"
            "**更不要虚构「我记住了」「已帮你保存」**——系统只有用户明确说「把XX存成客户」并确认后才真正保存，"
            "在那之前你只是聊过天而已。\n"
            "7) 【联网引用规则】你**具备**联网检索能力（系统会在需要时自动检索并把结果注入上下文）。"
            "若上下文里有【联网检索结果·刚刚实时搜索所得】块，它就是你刚刚真实搜到的最新信息，"
            "**直接引用作答并注明来源**，不要否认它的存在；"
            "若没有该块，只代表本次回答未附检索结果——**绝对不要**说「我不具备联网能力」「我无法联网」"
            "这类否认能力的话（那是错的，系统有检索功能），也不要承诺「我马上去搜」（你无法主动触发）；"
            "此时涉及实时信息就基于已有对话信息作答，并如实说明本次没有可引用的检索结果。\n"
            "8) 【不做空头承诺】你无法在对话里主动执行生成动作；当用户要 Word/PPT/PDF 文件时，"
            "**不要**回答「好的我马上生成」「请稍等」——那是永远不会兑现的空头支票。"
            "正确做法：告诉用户发一句明确指令即可，例如「把这份内容整理成PPT」「导出成Word」，"
            "系统收到指令会自动生成可下载文件。\n"
            "9) 【自我认知·如实】你是一个由自研 AgentHarness 驱动的 agentic workflow 系统：具备"
            "制定计划并分步执行、自主选择并调用工具（含联网检索/知识库/竞品/沙箱代码计算/文档生成）、"
            "反思重试、多轮澄清和跨轮记忆的能力。被问「你是不是 AI / 机器人 / Agent」时大方如实承认："
            "是 AI 助手，有自主规划和调用工具的能力；**绝对不要**说「我还不是 Agent」「我只是普通"
            "问答机器人」这类与事实不符的自我贬低，也**不要**吹嘘成能自主联网下单、操控电脑的"
            "超级 Agent——如实描述上面列出的能力即可。\n\n"
            f"{web_block}"
            f"{memory_block}"
            f"{history}\n\n"
            f"用户最新问题：{user_input}\n\n"
            "直接回答："
        )
        try:
            reply = await get_llm_response(
                prompt,
                model=getattr(self, "_run_model", None) or MATCH_LLM_MODEL,
            )
            reply = (reply or "").strip()
            if not reply:
                raise RuntimeError("empty reply")
            return reply
        except Exception as e:
            logger.warning(f"[Agent] general_chat LLM 失败，兜底自我介绍: {e}")
            return (
                "我是华为云解决方案匹配助手，主业是帮你按行业+场景匹配华为云方案、"
                "以及对比华为云与主流竞品的差异。\n\n"
                "你刚才的问题我暂时没能给出满意答复（可能服务繁忙），如果有方案匹配需求，"
                "告诉我**行业 + 场景 + 规模**，我帮你继续。"
            )

    # ---- 结果组装 ----

    def _make_result(
        self,
        answer: str,
        tool_calls: list,
        success: bool,
        paused: bool = False,
        clarify_id: Optional[str] = None,
        questions: Optional[list] = None,
        expired: bool = False,
        plan: Optional[list] = None,
        plan_status: Optional[list] = None,
        format_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        elapsed = time.time() - self._start_time
        # P1-2：集中缓存终稿，供后续 export 意图 / generate_doc 拦截导出（跨轮保留）。
        # 仅对真正产出方案内容的意图且在成功时缓存；account/greeting/general/export 不缓存，
        # 避免把轻量回复当作方案终稿导出。覆盖 final_answer 主路径与解析失败兜底路径，
        # 确保任一成功路径收尾后 _last_draft 都非空。
        if success and answer and isinstance(answer, str) and self._intent in (
            "solution", "competitor", "knowledge_q", "file_ops",
        ):
            self._last_draft = answer
        return {
            "answer": answer,
            "solution_json": parse_markdown_to_chapters(answer) if answer else [],
            "steps": self._step_count,
            "elapsed": round(elapsed, 2),
            "tool_calls": tool_calls,
            "logs": self._logs,
            "success": success,
            "paused": paused,
            "clarify_id": clarify_id,
            "questions": questions or [],
            "expired": expired,
            # P0：执行计划透传（前端可在 result 后收起/保留 Plan 面板）。
            # 轻量路径（account/greeting/general/export 等）显式传 plan=[]，避免单例 agent
            # 把上一轮 plan-driven 运行的旧计划残留进本轮 result。
            "plan": list(self._plan) if plan is None else plan,
            "plan_status": list(self._plan_status if plan_status is None else plan_status),  # P1-1：plan 每步状态
            "format_mode": format_mode or getattr(self, "_format_mode", "solution"),  # P0：导出时决定 report_type（solution/competitor）；轻量路径传 general 让前端不出导出按钮
            "reflexion_used": self._reflexion_count > 0,   # P1-3：是否触发过反思
            "reflexion_success": self._reflexion_success,  # P1-3：反思是否成功注入
            "replanned": getattr(self, "_last_replanned", False),  # P3-1：本次是否触发真重规划
            "quality_warn": getattr(self, "_quality_warn", False),  # P3-3：自检 Gate 达上限仍不过时标记
        }

    # ---- 日志 ----

    def _log(self, level: str, msg: str) -> None:
        entry = {
            "time": round(time.time() - self._start_time, 3),
            "level": level,
            "message": msg,
        }
        self._logs.append(entry)
        if self.verbose:
            log_func = {
                "system": logger.info,
                "llm": logger.debug,
                "action": logger.info,
                "observation": logger.debug,
                "error": logger.error,
                "warn": logger.warning,
            }.get(level, logger.info)
            log_func(f"[Agent][{level}] {msg[:200]}")
