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
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

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
REACT_SYSTEM_PROMPT_BASE = """你是一个智能解决方案匹配助手，帮助用户找到最合适的华为云解决方案。

## 工作方式
你需要使用"思考-行动-观察"的方式逐步解决问题：

1. 先判断需求是否"关键信息齐全"：
   - 关键信息 = 行业（或业务领域）+ 核心场景/目标。二者至少其一齐备，才能有效检索华为云方案。
   - 如果行业/核心场景缺失、且无法从对话历史推断 → 第一步直接输出 Clarify 向用户提问（不要先调用任何工具）；拿到补充后再走工具链。
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

### 需要向用户澄清时（关键信息缺失，尤其是行业/核心场景缺失时优先使用）：
Clarify: [{{"question": "这个项目的所属行业/业务领域是？", "options": ["制造业", "政务", "零售/电商", "医疗健康", "其他（请补充）"]}}]
（可一次给 1-2 个问题，每个问题可附带若干候选选项方便用户快速选择；当缺少行业或核心场景时，务必先用 Clarify 提问，不要直接调 analyze_demand）

## 规则
- 必须调用工具来获取信息，不能凭空编造
- Action Input 必须是合法的 JSON
- 每次只输出一个 Action，不要一次输出多个
- 如果工具返回错误，尝试调整参数重试一次，再失败就基于已有信息回答
- 最多执行 {max_steps} 步
- 不要调用 generate_report 工具——你直接用 Final Answer 输出报告即可
- 【澄清优先】当需求缺少"行业/业务领域"或"核心场景/目标"、且无法从对话历史推断时，请优先用 Clarify 提问（不要先调 analyze_demand/search_kb）；拿到补充后再走工具链。
- 【多轮澄清策略】用户首次输入通常很模糊（如"帮我做个云方案"仅几个字），一次提问往往不够。请按以下策略逐步收集：
  ① 第 1 轮：优先问行业/业务领域（最关键，没有行业无法精准检索）
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
            current_prompt = saved_prompt + f"""
Observation: 用户补充信息：
{ans_text}
请继续分析。如果信息足够，请输出 Final Answer。"""
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

                    # 将 Observation 追加到 Prompt，进入下一轮
                    current_prompt += f"""

{llm_response}

Observation: {observation}

请继续分析。如果信息足够，请输出 Final Answer。"""

                else:
                    # 解析失败。如果已有工具调用结果，直接把 LLM 输出当最终答案
                    if tool_calls_log:
                        self._log("warn", f"LLM 格式不对但已有数据，统一增强管线重写")
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

    async def _finalize_answer(self, user_input: str, draft: str, tool_calls: list) -> str:
        """用统一增强管线重写最终答案（与标准模式一致：来源标注/防幻觉/话术/14章）。

        失败（如 LLM 异常）时回退到 Agent 的草稿，保证不阻断主流程。
        """
        try:
            context, industry, demand_analysis = self._collect_context_and_demand(tool_calls)
            if not context.strip():
                # 没有检索到任何资料 → 不二次生成，直接用草稿
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
