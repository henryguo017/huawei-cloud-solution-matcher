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
from app.config import MATCH_LLM_MODEL, SUPPORTED_COMPETITORS, AGENT_TWO_PHASE, AGENT_MULTI_AGENT, AGENT_CONTEXT_WINDOW

logger = logging.getLogger(__name__)


def _trunc(s: str, n: int) -> str:
    """截断过长的文本段（用于追加到 ReAct prompt），防止多步检索后 prompt 爆炸导致模型失焦。"""
    s = s or ""
    if len(s) <= n:
        return s
    return s[:n] + f"\n…（已截断，保留前 {n} 字）"


# ReAct 提示词模板（Final Answer 结构与标准模式共用同一套增强指令，保证三模式质量一致）
REACT_SYSTEM_PROMPT_BASE = """你是一个智能解决方案匹配助手，帮助用户找到最合适的华为云解决方案。

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
        # P2-1-A：真·两阶段执行状态（plan 驱动执行顺序）
        self._step_results: dict = {}      # P2：每步执行结果（供 D5 重跑与多智能体消费）
        self._phase_outputs: dict = {}     # P2-1-B：多智能体各阶段产物（demand/architect/reviewer）
        self._two_phase_enabled = True     # P2：运行期开关（run() 内按 config 覆盖）
        self._multi_agent_enabled = True   # P2：多智能体开关
        self._memory_context_injected = False  # P2-2：长程记忆注入标记（仅首轮注入一次）

    # ---- 主入口 ----

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
                    from app.agent.agents import get_role
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
                obs = await self._execute_step(idx, step, toolset, event_callback, session_id, tool_calls_log,
                                               role_prompt=role["prompt"] if role else None)
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

            # 汇总各步结果 → 终稿（走统一增强管线 + 自检）
            final = await self._synthesize_final(user_input, plan, step_outputs, event_callback)
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
                tool_name = parse_result["tool_name"]
                tool_input = parse_result["tool_input"]
                if tool_name not in toolset:
                    hint = f"（本步不允许工具 {tool_name}，仅可使用：{tools_desc}）"
                    obs_lines.append(hint)
                    step_prompt += "\n" + hint
                    continue
                # 点亮 running
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
        steps_txt = "\n".join(
            f"- 第{i + 1}步（{step}）：\n{_trunc(out, 600)}" for i, (step, out) in enumerate(zip(plan, step_outputs))
        ) or "（无执行结果）"
        prompt = (
            "你是华为云售前方案撰写官。你已按计划执行了各步骤，请基于各步收集到的信息，"
            "为用户撰写完整、可落地的最终方案。\n\n"
            f"【用户需求】{user_input}\n\n"
            f"【执行计划与各步结果】\n{steps_txt}\n\n"
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
                    success=False, expired=True,
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
            self.memory.add_user_message(session_id, user_input)
            self._client_context = extra_context  # B修复：首轮注入客户背景，供最终增强管线使用

            # P2-2：首轮注入长程记忆（episodic 相关历史方案 + procedural 用户画像），
            # 仅注入一次，不随澄清轮次重复追加；无记忆/异常时为空串不影响主流程。
            if not getattr(self, "_memory_context_injected", False):
                try:
                    from app.agent.memory_profiles import build_memory_context, build_profile_context
                    uid = user_id if isinstance(user_id, int) and user_id > 0 else None
                    mem_block = build_memory_context(uid, user_input) if uid else ""
                    profile_block = build_profile_context(uid) if uid else ""
                    if mem_block or profile_block:
                        extra_context = (extra_context or "") + "\n\n" + mem_block + "\n" + profile_block
                        self._client_context = extra_context
                    self._memory_context_injected = True
                except Exception as e:
                    self._log("warn", f"长程记忆注入失败（忽略）: {e}")
                    self._memory_context_injected = True

            tools_desc = self.tools.get_tools_prompt()

            # ── 意图路由（A 方案）：首轮先识别意图，非方案类直接轻量回复，不进 ReAct/14章流水线 ──
            intent = classify_intent(user_input)
            self._intent = intent.get("intent", "solution")
            self._format_mode = "competitor" if self._intent == "competitor" else "solution"
            competitors = intent.get("competitors", []) or []
            self._log("system", f"[INTENT] {intent}")

            # P2 修复：方案/竞品意图但需求过短、缺行业/场景 → 直接澄清，避免凭空生成方案
            if self._intent in ("solution", "competitor") and self._need_clarify(
                user_input, intent.get("industries") or []
            ):
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
                return self._make_result(light, [], success=True)

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
                return self._make_result(light, [], success=True)

            if self._intent == "general":
                # 通用问答（算数/常识/自我介绍/"你能做什么"等）：调 LLM 直答，
                # 不套方案模板；可融合对话历史，让多轮追问能用上上下文。
                await self._emit(event_callback, {
                    "type": "thought",
                    "step": 1,
                    "text": "识别意图：通用问答（非方案/非竞品/非账户/非纯礼节），调 LLM 直接回答",
                })
                general = await self._answer_general_chat(user_input, session_id)
                self.memory.add_agent_response(session_id, general)
                await self._emit(event_callback, {
                    "type": "final",
                    "step": 1,
                    "elapsed": round(time.time() - self._start_time, 2),
                })
                return self._make_result(general, [], success=True)

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
                return self._make_result(answer, [], success=True)

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

    # ---- 工具权限闸门（#3 human-in-the-loop）/ 联网搜索开关（#6）----
    # 默认策略：高风险工具在 Agent 自主决策执行时先征求确认；显式「导出」意图不走此闸门。
    DEFAULT_TOOL_POLICY = {
        "generate_doc": "ask",
        "read_customer_file": "ask",
        "web_search": "allow",
    }

    async def _gate_tool(self, tool_name: str, tool_input: dict, event_callback=None) -> Optional[str]:
        """返回 None 表示放行；返回字符串表示跳过工具并作为 Observation 注入。

        - #6 联网搜索关闭：直接跳过 web_search，不再联网。
        - #3 策略 deny：跳过；ask：发 permission_request SSE 并阻塞等待用户决策。
        """
        # #6 联网搜索开关
        if tool_name == "web_search" and getattr(self, "_disable_web_search", False):
            return "（已关闭联网搜索，本次跳过网络检索，仅基于本地知识库作答。）"
        policy = (getattr(self, "_tool_permissions", None) or {}).get(tool_name) \
            or self.DEFAULT_TOOL_POLICY.get(tool_name)
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

    def _permission_reason(self, tool_name: str) -> str:
        return {
            "generate_doc": "Agent 准备生成一份可下载的方案书（Word/PDF/PPTX），将占用存储并生成文件。",
            "read_customer_file": "Agent 准备读取你上传的客户资料文件。",
            "web_search": "Agent 准备联网检索（华为云官网 / 竞品动态），可能产生额外请求。",
        }.get(tool_name, f"Agent 准备执行工具「{tool_name}」。")

    def _permission_safe_input(self, tool_name: str, tool_input: dict) -> dict:
        """URL / 路径脱敏：只暴露对决策有用的最小信息。"""
        ti = tool_input or {}
        if tool_name == "web_search":
            return {"query": str(ti.get("query", ""))[:120]}
        if tool_name == "read_customer_file":
            return {"path": str(ti.get("path", ""))[:160]}
        if tool_name == "generate_doc":
            return {"fmt": str(ti.get("format", ti.get("fmt", "word")))}
        return {k: str(v)[:120] for k, v in ti.items()}

    # ---- 上下文用量预估（#1）----
    @staticmethod
    def _est_tokens(text: str) -> int:
        """中文 + 英文混排的粗略 token 估算（约 1.6 字符 / token）。"""
        if not text:
            return 0
        return max(1, int(len(text) / 1.6))

    def estimate_context_usage(self, session_id: str) -> dict:
        """预估当前会话上下文占用（token 估算，仅展示用，非精确分词）。"""
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
                memory_text = (build_memory_context(uid, "") or "") + (build_profile_context(uid) or "")
        except Exception:  # noqa: BLE001
            memory_text = ""
        conv_text = ""
        try:
            hist = self.memory.get_conversation_history(session_id) or ""
            conv_text = hist if isinstance(hist, str) else str(hist)
        except Exception:  # noqa: BLE001
            conv_text = ""
        window = int(AGENT_CONTEXT_WINDOW or 64000)
        buckets = {
            "system": self._est_tokens(system_text),
            "tools": self._est_tokens(tools_text),
            "memory": self._est_tokens(memory_text),
            "conversation": self._est_tokens(conv_text),
        }
        total = sum(buckets.values())
        return {
            "buckets": buckets,
            "total": total,
            "window": window,
            "percent": min(100, round(total * 100 / window)) if window else 0,
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
            # P1-2：联网检索摘要（observation 形如 {status, count, results:[{domain,title}]}）
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
            hw_docs = await asyncio.to_thread(kb.search_huawei, user_input, 6, filter_industry=(industry or None))
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

    async def _answer_general_chat(self, user_input: str, session_id: str) -> str:
        """通用问答（算数/常识/自我介绍/"你能做什么"等）：调 LLM 直接回答。

        关键能力：
        - 多轮上下文：注入 `get_conversation_history(session_id)`，让追问能用上前面
        - 防止驴头不对马嘴：明确禁止套方案模板，要求「先答用户问题，再补一句方案能力」
        - 失败安全兜底（LLM 超时/异常）：返回一个简洁自我介绍
        """
        from app.models.llm import get_llm_response

        history = self.memory.get_conversation_history(session_id) or "（这是第一次对话）"
        prompt = (
            "你是华为云解决方案智能匹配助手。下面是用户与你的多轮对话历史。\n"
            "【关键】用户当前问的不一定是方案问题，可能是算数/常识/概念/自我介绍等通用问询。\n"
            "回答原则：\n"
            "1) 先**直接、准确**地回答用户问题（短答优先，不超过 3 句话，除非用户明确要详细）。\n"
            "2) 如果问题与方案匹配无关（如「1+1等于几」「Python 是什么」），**只回答问题本身**，不要强行推销方案能力。\n"
            "3) 回答结束时，自然地加一句过渡，告诉用户如果有方案匹配需求可继续告诉你。\n"
            "4) 用**简洁、自然**的口吻，避免「我是华为云助手，根据行业+场景匹配…」这种固定模板式开场。\n\n"
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
            "plan": self._plan,   # P0：执行计划透传（前端可在 result 后收起/保留 Plan 面板）
            "plan_status": list(self._plan_status),  # P1-1：plan 每步状态，前端 result 后保留面板点亮
            "format_mode": getattr(self, "_format_mode", "solution"),  # P0：导出时决定 report_type（solution/competitor）
            "reflexion_used": self._reflexion_count > 0,   # P1-3：是否触发过反思
            "reflexion_success": self._reflexion_success,  # P1-3：反思是否成功注入
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
