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

logger = logging.getLogger(__name__)


# ReAct 提示词模板（Final Answer 结构与标准模式共用同一套增强指令，保证三模式质量一致）
REACT_SYSTEM_PROMPT_BASE = """你是一个智能解决方案匹配助手，帮助用户找到最合适的华为云解决方案。

## 工作方式
你需要使用"思考-行动-观察"的方式逐步解决问题：

1. 如果用户需求模糊，第一步必须先调用 analyze_demand 分析需求
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

## 规则
- 必须调用工具来获取信息，不能凭空编造
- 如果用户需求模糊，第一步必须先调用 analyze_demand
- Action Input 必须是合法的 JSON
- 每次只输出一个 Action，不要一次输出多个
- 如果工具返回错误，尝试调整参数重试一次，再失败就基于已有信息回答
- 最多执行 {max_steps} 步
- 不要调用 generate_report 工具——你直接用 Final Answer 输出报告即可"""


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

        # 清空短期记忆，记录用户输入
        self.memory.clear_short_term(session_id)
        self.memory.add_user_message(session_id, user_input)

        # 构建初始 Prompt
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

现在请开始分析（如果需求模糊，先调用 analyze_demand）："""

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
                    llm_response = await self._call_llm(current_prompt)
                except Exception as e:
                    self._log("error", f"LLM 调用失败: {e}")
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
                            "text": thought[:200],
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
        # 先尝试匹配 Final Answer（显式声明）
        fa_match = re.search(
            r'Final\s*Answer\s*[:：]\s*(.*?)$',
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if fa_match:
            thought_match = re.search(r'Thought\s*[:：]\s*(.+?)(?=\n\s*(?:Final|Action)|$)', text, re.DOTALL | re.IGNORECASE)
            return {
                "type": "final_answer",
                "content": fa_match.group(1).strip(),
                "thought": thought_match.group(1).strip() if thought_match else "",
            }

        # 尝试匹配 Action + Action Input
        action_match = re.search(
            r'Action\s*[:：]\s*(\w+)',
            text,
            re.IGNORECASE,
        )
        if action_match:
            tool_name = action_match.group(1).strip()

            # 尝试解析 Action Input（JSON 格式）
            input_match = re.search(
                r'Action\s*Input\s*[:：]\s*(\{.*?\})',
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

            thought_match = re.search(
                r'Thought\s*[:：]\s*(.+?)(?=\n\s*Action)',
                text,
                re.DOTALL | re.IGNORECASE,
            )
            return {
                "type": "action",
                "tool_name": tool_name,
                "tool_input": tool_input,
                "thought": thought_match.group(1).strip() if thought_match else "",
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
        parts = []
        idx = 0
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
                # 非 JSON 的 observation（罕见）→ 作为普通资料
                idx += 1
                parts.append(f"[资料{idx} | 来源:工具返回 | 类型:参考]\n{raw}")
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
                idx += 1
                source = doc.get("source", "未知来源")
                doc_industry = doc.get("industry", "")
                doc_type = doc.get("type", "华为云方案")
                # search_competitor 的 type 可能是竞品名；search_kb 无 type → 华为云方案
                typ = "竞品方案" if (doc_type and doc_type != "华为云") else "华为云方案"
                content = doc.get("content", "")
                parts.append(
                    f"[资料{idx} | 来源:{source} | 行业:{doc_industry or '通用'} | 类型:{typ}]\n{content}"
                )
                if idx >= 12:  # 限制上下文规模，避免多步检索导致膨胀
                    break

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
    ) -> Dict[str, Any]:
        elapsed = time.time() - self._start_time
        return {
            "answer": answer,
            "solution_json": parse_markdown_to_chapters(answer),
            "steps": self._step_count,
            "elapsed": round(elapsed, 2),
            "tool_calls": tool_calls,
            "logs": self._logs,
            "success": success,
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
