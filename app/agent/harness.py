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
from app.agent.memory import ConversationMemory
from app.services.solution_prompt import (
    parse_markdown_to_chapters,
    build_anti_hallucination,
    build_audience_tone,
    build_few_shot,
    build_format_block,
)
from app.services.solution_matcher import SolutionMatcherService
from app.agent.clarify_store import ClarifySessionStore

logger = logging.getLogger(__name__)


# ReAct 提示词模板（Final Answer 结构与标准模式共用同一套增强指令，保证三模式质量一致）
REACT_SYSTEM_PROMPT_BASE = """你是一个华为云售前智能助手（Copilot）。你既精通华为云解决方案、竞品对比、报价测算与方案文档生成，也能回答云计算/ICT 通用知识、写作辅助（周报/邮件/话术）、平台使用方法与功能指引，以及用户的任何随机关心问题——用户问什么，你就答什么。

## 工作方式
你需要使用"思考-行动-观察"的方式逐步解决问题：

1. 先判断需求是否"关键信息齐全"：
   - 关键信息 = 行业（或业务领域，大类即可）+ 核心场景/目标 + 至少一个具体细节（规模/数量/痛点量化等）。三者齐全时直接走工具链，不要用 Clarify。
   - 如果行业/核心场景缺失、且无法从对话历史推断 → 第一步输出 Clarify 向用户提问（不要先调用任何工具）；拿到补充后再走工具链。
   - **特别注意**：用户输入 ≥30 字且能同时提取出「行业+场景+细节」三类信息时，视为关键信息齐全。例如「中型制造企业50台设备想做预测性维护减少停工」已包含制造(行业)+预测性维护(场景)+50台(细节)，应直接检索不要追问。
   - 如果关键信息齐全 → 调用 analyze_demand 分析需求，再 search_kb 检索，必要时 search_competitor 对比，最后 Final Answer。
2. 根据分析结果，调用 search_kb 检索华为云方案（换关键词可多次调用）
3. 如果用户提到竞品，调用 search_competitor 进行对比
4. 收集足够信息后，输出 Final Answer（内容依意图而定，见下方「意图识别与工具选择」）

## 意图识别与工具选择（关键：先判意图，再选工具链，完成后立即终止）

请先判断用户输入的主意图，再选择对应工具链。**每类意图完成其工具链后必须立即输出 Final Answer，禁止继续调用其他工具。**

**【最关键的兜底规则】如果用户输入不属于 A–E 任何一类（例如：云计算概念科普、写作辅助、平台怎么用/某个功能干嘛、闲聊、或任何超出售前范畴的问题），一律判定为 F. 通用问答，直接输出 Final Answer 回答用户，不要调用任何工具，更不要把它套成方案。** 绝大多数"随便问问"的问题都走 F。

【A. 方案推荐】用户想要解决方案 / 架构建议 / 技术选型（未要求生成文件）
  特征词：方案、解决、架构、推荐、怎么上云、xx行业云、怎么做、规划
  工具链：analyze_demand → search_kb → （提及竞品时）search_competitor → Final Answer
  输出：完整方案报告（系统会增强为结构化方案）
  ★ 完成标志：search_kb 返回结果后即可 Final Answer，不要继续调其他工具

【B. 竞品对比】用户要对比不同厂商的优劣
  特征词：对比、vs、竞品、阿里云、腾讯云、AWS、谁好、优劣、差异
  工具链：search_competitor → **立即** Final Answer
  输出：对比分析（2-4 段精炼总结 + 关键维度对比表）
  ★★★ 绝对禁止：search_competitor 完成后禁止调 analyze_demand / search_kb / query_pricing！那会变成完整方案，不是用户要的竞品对比！

【C. 报价 / 价目】用户问价格、费用、成本、预算
  特征词：多少钱、报价、价格、费用、成本、TCO、预算、包月、包年
  工具链：query_pricing → **立即** Final Answer
  输出：价目清单 + 简要说明（2-3 段）
  ★★★ 绝对禁止：query_pricing 完成后禁止调 analyze_demand / search_kb / search_competitor！

【D. 文件生成】用户明确要求生成文件（Excel / PPT / Word / 图表 / 报表 / 大纲文件）
  特征词：生成、做、写、导出、Excel、PPT、报表、xlsx、pptx、图表、大纲文件
  ★ 工具链：直接 run_code（写代码生成文件），**不要调用 search_kb / search_competitor / analyze_demand**
  ★ 输出：简要说明已生成的文件名、内容、如何下载（3-5 句话，不要写完整方案报告）
  ★★★ run_code 成功生成文件后立即 Final Answer，禁止再调任何检索工具！

【E. 混合意图】同时包含多种（如"做个政务云方案，对比阿里云，算3年TCO"）
  工具链：按 A→B→C 顺序分多轮调用，最后整合到 Final Answer
  ⚠️ 混合意图的输出应**精炼聚焦**（总长度控制在合理范围），不要机械拼接导致冗长

【F. 通用问答 / 平台助手】用户问的是通用知识、云计算概念科普、写作辅助（周报/邮件/话术/演讲稿）、平台使用方法/功能指引（"怎么导出历史方案""积分怎么算""某个按钮干嘛"）、闲聊，或任何不属于 A–E 的问题
  特征：无明确"方案/竞品/价目/文件"意图，或问题超出售前范畴
  ★ 工具链：**无需调用任何工具**，直接基于你的知识输出 Final Answer
  ★ 输出：直接、准确、有帮助的回答（可带示例、步骤、要点列表）
  ★★★ 绝对禁止：不要把 F 类问题套成方案结构，也不要为了"显得专业"去调 analyze_demand / search_kb 生成方案！直接回答用户的问题即可
  （例外：若问题与华为云具体产品参数/最新报价强相关且你需要事实补全，可轻量调用 query_pricing / search_kb 仅作事实补充，但目的只是补全回答，不是生成方案文档）

## ⚠️ 核心纪律（违反会导致体验极差）
1. **识别意图后只走该意图的工具链，不走别的**
2. **工具链完成 = 立即 Final Answer，不追加额外工具**
3. **意图 B/C/D 的 Final Answer 应该简短精炼（几段话/一个表），不是 14 章方案文档**
4. 如果你发现自己在非方案意图上调了 analyze_demand 或 search_kb → **立即停止，直接 Final Answer**
5. **F. 通用问答是默认兜底**：任何不属于 A–E 的问题（知识科普、写作、平台用法、闲聊等）一律按 F 直接回答，**绝不套用方案结构、绝不强行调工具**。用户"随便问问"时，给一个自然、有用的回答即可。

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
- 售前事实类问题（方案/竞品/报价）必须基于工具检索，不能凭空编造；但**通用问答/知识科普/写作类问题（意图 F）可直接回答，无需调用工具**——此时直接输出 Final Answer 即可，不必强行调工具。
- Action Input 必须是合法的 JSON
- 每次只输出一个 Action，不要一次输出多个
- 如果工具返回错误，尝试调整参数重试一次，再失败就基于已有信息回答
- 最多执行 {max_steps} 步
- 不要调用 generate_report 工具——你直接用 Final Answer 输出报告即可
- 【代码沙箱 run_code】当需要**精确数值计算**（如三年 TCO、ROI、成本对比）或**生成真实文件**（Excel 报表/数据表/PPT 图表）时，调用 run_code 在隔离沙箱运行 Python。可用库：pandas、openpyxl、python-pptx（无需联网）。脚本须独立可跑，结果用 openpyxl/pptx 写入当前目录文件，关键结论用 print() 输出；严禁联网。执行过程会实时回传日志，报错请自行修改脚本重试（最多 2 次）。生成文件后在 Final Answer 中告知用户可下载。**注意：当用户只说要生成文件（如「生成PPT大纲」「做一份Excel报表」）时，直接调用 run_code 生成，不要先检索知识库（那是方案推荐意图才做的）。**
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


# Final Answer 增强指南：仅适用于方案推荐意图（A/E），其他意图忽略此节
REACT_FINAL_GUIDE = (
    "\n\n【Final Answer 报告结构要求 —— 仅当你的意图是「方案推荐(A)」或「混合意图(E)含方案部分」时才需遵守以下章节结构。"
    "若你的意图是竞品对比(B)/价目查询(C)/文件生成(D)，请完全忽略此节，按对应意图的输出要求给出精炼回答。】\n"
    + build_format_block()
    + "\n"
    + build_anti_hallucination()
    + build_audience_tone()
    + build_few_shot()
    + "【来源标注】引用检索到的资料时，必须在句末注明来源文件名（如：据《xxx.docx》），"
    "来源文件名已在上方 Observation 的 source 字段给出。\n"
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
        max_steps: int = 12,
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

    # ---- 主入口 ----

    async def _emit(self, event_callback, event: Dict[str, Any]) -> None:
        """安全调用事件回调"""
        if event_callback:
            try:
                await event_callback(event)
            except Exception as e:
                logger.warning(f"事件回调失败: {e}")

    async def run(
        self,
        user_input: str,
        session_id: str = "default",
        extra_context: str = "",
        event_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        clarify_id: Optional[str] = None,
        answers: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        运行 ReAct 循环

        参数:
            event_callback: 可选异步回调，用于 SSE 流式推送进度事件。
                事件格式: {"type": "step"|"tool_start"|"tool_end"|"thought"|"final", ...}

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
        self._event_callback = event_callback  # 供 _execute_tool 注入工具上下文
        tool_calls_log = []
        self._clarify_round = 0

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

            tools_desc = self.tools.get_tools_prompt()
            system_prompt = (REACT_SYSTEM_PROMPT_BASE + REACT_FINAL_GUIDE).format(
                tools=tools_desc,
                max_steps=self.max_steps,
            )

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
                    # 统一增强管线：基于已检索资料重写最终答案（与标准模式一致）
                    final_answer = await self._finalize_answer(user_input, final_answer, tool_calls_log)
                    self.memory.add_agent_response(session_id, final_answer)
                    await self._emit(event_callback, {
                        "type": "final",
                        "step": self._step_count,
                        "elapsed": round(time.time() - self._start_time, 2),
                    })
                    # 方案意图：发 solution_card 事件（前端渲染方案摘要卡，嵌入对话流）
                    if event_callback:
                        _used_kb = any(
                            tc.get("tool") in ("analyze_demand", "search_kb")
                            for tc in tool_calls_log
                        )
                        if _used_kb:
                            _industry = ""
                            for tc in tool_calls_log:
                                if tc.get("tool") == "analyze_demand":
                                    try:
                                        _d = json.loads(tc.get("result", "{}"))
                                        _industry = _d.get("industry", "")
                                    except Exception:
                                        pass
                            try:
                                await event_callback({
                                    "type": "solution_card",
                                    "industry": _industry,
                                    "preview": final_answer[:200],
                                    "word_count": len(final_answer),
                                })
                            except Exception as e:
                                logger.warning(f"[solution_card] 事件回调失败: {e}")
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

                    # 发送工具开始事件
                    await self._emit(event_callback, {
                        "type": "tool_start",
                        "step": self._step_count,
                        "tool": tool_name,
                    })

                    # 执行工具
                    observation = await self._execute_tool(tool_name, tool_input)
                    self._log("observation", observation[:300])
                    self.memory.add_observation(session_id, observation)

                    # 将工具结果存入日志，供 routes.py 提取 source_documents
                    tool_calls_log[-1]["result"] = observation

                    # 发送工具完成事件
                    await self._emit(event_callback, {
                        "type": "tool_end",
                        "step": self._step_count,
                        "tool": tool_name,
                    })

                    # 将 Observation 追加到 Prompt，进入下一轮（意图感知的续行提示）
                    _nudge = self._build_intent_nudge(tool_calls_log, tool_name)
                    current_prompt += f"""

{llm_response}

Observation: {observation}

{_nudge}"""

                else:
                    # 解析失败。如果已有工具调用结果，直接把 LLM 输出当最终答案
                    if tool_calls_log:
                        self._log("warn", "LLM 格式不对但已有数据，统一增强管线重写")
                        final_answer = await self._finalize_answer(user_input, llm_response, tool_calls_log)
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

{llm_response}

（你的输出格式不正确。请严格按格式输出：
Thought: [分析]
Action: [工具名]
Action Input: [JSON参数]

或者：
Thought: 我已收集到足够信息
Final Answer: [完整方案]）"""

            # 超过最大步数
            self._log("system", f"超过最大步数 {self.max_steps}，强制汇总")
            fallback = await self._generate_fallback(user_input)
            return self._make_result(fallback, tool_calls_log, success=False)

        except Exception as e:
            self._log("error", f"ReAct 循环异常: {e}")
            fallback = await self._generate_fallback(user_input)
            return self._make_result(fallback, tool_calls_log, success=False)

    # ---- LLM 调用 ----

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM，支持重试"""
        from app.models.llm import get_llm_response

        last_error = None
        for attempt in range(3):
            try:
                return await get_llm_response(prompt)
            except Exception as e:
                last_error = e
                logger.warning(f"LLM 调用失败 (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    await asyncio.sleep(2)
        raise last_error or RuntimeError("LLM call failed")

    # ---- 工具执行 ----

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """执行指定工具，返回 Observation 字符串"""
        tool = self.tools.get(tool_name)
        if not tool:
            return f"错误：工具 '{tool_name}' 不存在。可用工具：{self.tools.get_tool_names()}"

        # 注入事件回调到工具上下文（如 run_code 沙箱需要实时透传 stdout）
        try:
            from app.agent.tools import set_agent_event_callback
            set_agent_event_callback(getattr(self, "_event_callback", None))
        except Exception:
            pass

        try:
            return await tool.execute(**tool_input)
        except TypeError as e:
            # 参数不匹配，尝试纠正
            return f"错误：工具 '{tool_name}' 参数不正确：{e}。期望参数：{json.dumps(tool.parameters, ensure_ascii=False)}"
        except Exception as e:
            return f"工具 '{tool_name}' 执行失败：{str(e)}"

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
        """判断文本是否像是一个实质性回答（而非格式错误）"""
        # 包含 Markdown 标题
        if re.search(r'#{1,3}\s', text):
            return True
        # 包含中文 + 长度 > 100
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        if chinese_chars > 20 and len(text) > 100:
            return True
        # 包含方案报告常见关键词
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

    def _detect_intent(self, tool_calls: list) -> str:
        """根据已调用工具链判断用户意图类型。

        返回值：
        - 'solution' : 调用了 analyze_demand 或 search_kb（方案推荐/混合方案部分）
        - 'competitor': 仅调了 search_competitor（纯竞品对比）
        - 'pricing'  : 仅调了 query_pricing（纯价目查询）
        - 'filegen'  : 仅调了 run_code（纯文件生成）
        - 'mixed'    : 多种工具组合（含竞品+价目等非方案工具）
        - 'unknown'  : 无法判断（无工具调用或异常）
        """
        tools_used = set(tc.get("tool", "") for tc in tool_calls)
        has_kb = bool(tools_used & {"analyze_demand", "search_kb"})
        has_comp = "search_competitor" in tools_used
        has_price = "query_pricing" in tools_used
        has_code = "run_code" in tools_used

        if has_kb:
            return "solution"
        if has_comp and not has_price and not has_code and len(tools_used) == 1:
            return "competitor"
        if has_price and not has_comp and not has_code and len(tools_used) == 1:
            return "pricing"
        if has_code and not has_kb and not has_comp and not has_price:
            return "filegen"
        if len(tools_used) > 1:
            return "mixed"
        return "unknown"

    async def _finalize_answer(self, user_input: str, draft: str, tool_calls: list) -> str:
        """意图感知的最终答案增强。

        - 方案意图(solution/mixed含KB)：走完整 14 章增强管线（来源标注/防幻觉/话术）
        - 非方案意图(competitor/pricing/filegen)：直接用 Agent 草稿，不做 14 章重写
        - 失败时回退到 Agent 的草稿，保证不阻断主流程
        """
        intent = self._detect_intent(tool_calls)
        self._log("system", f"[_finalize_answer] 检测意图={intent}, 工具={[tc.get('tool') for tc in tool_calls]}")

        # 非方案意图 → 直接返回 Agent 草稿，不走 14 章增强
        if intent in ("competitor", "pricing", "filegen"):
            self._log("system", f"非方案意图({intent})，跳过14章增强，使用Agent草稿(len={len(draft)})")
            return draft

        # 通用问答（意图 F，0 工具调用）→ 直接返回草稿，绝不重写为方案
        if intent == "unknown":
            self._log("system", f"通用问答意图(unknown/0工具)，跳过14章增强，使用Agent草稿(len={len(draft)})")
            return draft

        # 方案意图 / mixed 含 KB → 走完整增强管线
        try:
            context, industry, demand_analysis = self._collect_context_and_demand(tool_calls)
            if not context.strip():
                self._log("system", "Agent 未检索到资料，跳过统一增强，使用草稿")
                return draft
            matcher = SolutionMatcherService()
            enhanced = await matcher.generate_enhanced(
                demand=user_input,
                context=context,
                industry=industry,
                demand_analysis=demand_analysis,
            )
            self._log("system", "统一增强管线重写完成")
            return enhanced["answer"]
        except Exception as e:
            logger.warning(f"[Agent] 统一增强生成失败，回退草稿: {e}")
            return draft

    # ---- 兜底方案 ----

    async def _generate_fallback(self, user_input: str) -> str:
        """当 Agent 循环失败时，用增强模板直接生成（与标准模式一致的 14 章结构）"""
        from app.models.llm import get_llm_response

        prompt = (
            "你是华为云解决方案专家。用户提出了以下需求，请直接给出完整方案建议。\n\n"
            f"用户需求：{user_input}\n\n"
            + build_anti_hallucination()
            + build_audience_tone()
            + build_format_block()
        )

        try:
            return await get_llm_response(prompt)
        except Exception:
            return "抱歉，当前服务暂时不可用，请稍后重试。如问题持续，请联系管理员。"

    # ---- 结果组装 ----

    def _build_intent_nudge(self, tool_calls_log: list, last_tool: str) -> str:
        """根据已调用工具链生成意图感知的续行提示，防止非方案意图越界调用其他工具。"""
        tools_used = [tc.get("tool", "") for tc in tool_calls_log]
        # 判断当前意图倾向
        has_kb = any(t in ("analyze_demand", "search_kb") for t in tools_used)
        has_comp = "search_competitor" in tools_used
        has_price = "query_pricing" in tools_used
        has_code = "run_code" in tools_used

        # 纯竞品意图：search_competitor 完成后强制 Final Answer
        if last_tool == "search_competitor" and not has_kb and not has_code:
            return ("竞品信息已获取完毕。请立即输出 Final Answer（精炼的竞品对比分析，2-4段+对比表），"
                    "禁止再调 analyze_demand / search_kb / query_pricing！")

        # 纯价目意图：query_pricing 完成后强制 Final Answer
        if last_tool == "query_pricing" and not has_kb and not has_comp and not has_code:
            return ("价目信息已获取完毕。请立即输出 Final Answer（精炼的价目说明，2-3段），"
                    "禁止再调 analyze_demand / search_kb / search_competitor！")

        # 文件生成意图：run_code 完成后强制 Final Answer
        if last_tool == "run_code" and not has_kb:
            return ("文件已生成完毕。请立即输出 Final Answer（简要说明文件名和内容，3-5句话），"
                    "禁止再调 analyze_demand / search_kb / search_competitor / query_pricing！")

        # 方案意图或混合：标准续行提示
        if has_kb:
            if has_comp and not has_price:
                return "方案和竞品信息都已收集。如果信息足够，请输出 Final Answer（整合方案+竞品对比）。"
            return "请继续分析。如果方案信息足够（已有 KB 检索结果），请输出 Final Answer。"

        # 首步工具刚完成（如 analyze_demand），继续下一步
        return "请继续分析。如果信息足够，请输出 Final Answer。"

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
