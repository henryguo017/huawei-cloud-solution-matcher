"""
单一 Agent 入口

将所有组件（Tools + Memory + Harness）串联成一个可用的 Agent。
对外暴露简单的 async run() 接口，方便 API 路由直接调用。

用法:
    from app.agent import SolutionAgent

    agent = SolutionAgent()
    result = await agent.run("我想让工厂更智能", session_id="user_123")
    print(result["answer"])
"""

import logging
import json
from typing import Any, Awaitable, Callable, Dict, Optional

from app.agent.tools import ToolRegistry, create_default_tools
from app.agent.memory import ConversationMemory
from app.agent.harness import AgentHarness
from app.models.llm import get_llm_response

logger = logging.getLogger(__name__)


class SolutionAgent:
    """
    华为云解决方案智能匹配 Agent

    核心能力：
    1. 接收模糊需求 → 自动分析结构化
    2. 多步检索知识库 + 竞品资料
    3. 生成完整方案报告

    零改动现有代码，通过 import 对接现有 Service
    """

    def __init__(
        self,
        max_steps: int = 8,
        timeout: float = 120.0,
        verbose: bool = False,
    ):
        self.max_steps = max_steps
        self.timeout = timeout
        self.verbose = verbose

        # 创建工具注册中心（4 个核心工具）
        self.tools: ToolRegistry = create_default_tools()

        # 创建记忆管理器（阶段2 持久记忆，保留最近 15 轮对话）
        self.memory: ConversationMemory = ConversationMemory(max_history_turns=15)

        # 创建执行引擎
        self.harness: AgentHarness = AgentHarness(
            tools=self.tools,
            memory=self.memory,
            max_steps=max_steps,
            timeout=timeout,
            verbose=verbose,
        )

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
        运行 Agent

        参数:
            user_input:     用户输入的原始需求（可以是模糊的）
            session_id:     会话 ID，用于记忆隔离（默认 "default"）
            extra_context:  额外上下文，如产品页面传递的行业信息
            event_callback: 可选异步回调，用于 SSE 流式推送进度事件
            clarify_id:     澄清会话 ID（续跑时传入，从 ClarifySessionStore 恢复上下文）
            answers:        用户对澄清问题的回答列表（续跑时传入）
            user_id:        当前登录用户 ID（账户类查询据此从后端真实取数）
            user_info:      当前登录用户基本信息（路由传入，用于「账户信息」子类型）
            rerun_plan_index: P2-D5 Plan 单步重跑索引（命中时从 _step_results 重跑该步并重新汇总）

        返回:
            {
                "answer": str,       # 最终方案报告
                "steps": int,        # ReAct 执行步数
                "elapsed": float,    # 耗时（秒）
                "tool_calls": list,  # 工具调用记录
                "success": bool,     # 是否成功完成
            }
        """
        logger.info(f"Agent.run() session={session_id} input={user_input[:100]}...")
        return await self.harness.run(
            user_input=user_input,
            session_id=session_id,
            extra_context=extra_context,
            event_callback=event_callback,
            clarify_id=clarify_id,
            answers=answers,
            user_id=user_id,
            user_info=user_info,
            model=model,
            thinking=thinking,
            rerun_plan_index=rerun_plan_index,
            tool_permissions=tool_permissions,
            disable_web_search=disable_web_search,
        )

    async def run_with_competitor(
        self,
        user_input: str,
        competitor: str,
        industry: str = "",
        session_id: str = "default",
    ) -> Dict[str, Any]:
        """
        运行 Agent（带竞品分析）

        参数:
            user_input:   用户需求
            competitor:   竞品名称
            industry:     行业（可选）
            session_id:   会话 ID

        返回: 同上，但包含竞品对比内容
        """
        context = f"\n注意：用户关注的竞品是 {competitor}" + (f"，行业是 {industry}" if industry else "")
        return await self.run(
            user_input=user_input,
            session_id=session_id,
            extra_context=context,
        )

    def clear_session(self, session_id: str) -> None:
        """清除指定会话的记忆"""
        self.memory.clear_session(session_id)

    def get_stats(self, session_id: str = "default") -> Dict[str, Any]:
        """获取会话统计"""
        mem_stats = self.memory.get_stats(session_id)
        return {
            "session_id": session_id,
            "memory": mem_stats,
            "tools": self.tools.get_tool_names(),
            "max_steps": self.max_steps,
            "timeout": self.timeout,
        }

    # ---- 阶段2：用户画像提炼（FR-2.4） ----

    async def update_user_profile(self, user_id: int, session_id: str = "default", n: int = 4) -> None:
        """
        基于最近 n 轮对话，用 LLM 提炼/更新用户偏好画像，落库 user_profile 表。
        best-effort：任何异常仅记日志，不影响主流程。
        """
        if not user_id or user_id <= 0:
            return
        try:
            recent = self.memory.get_recent_conversation_for_profile(session_id, n=n)
            if not recent.strip():
                return
            existing = self._load_profile(user_id)
            prompt = _PROFILE_PROMPT.format(existing=existing or "（暂无已有画像）", recent=recent)
            raw = await get_llm_response(prompt)
            new_profile = self._extract_json(raw)
            if new_profile:
                self._save_profile(user_id, new_profile)
                logger.info(f"[agent] 用户画像已更新 user={user_id}")
        except Exception as e:
            logger.warning(f"[agent] 用户画像更新失败 user={user_id}: {e}")

    def _load_profile(self, user_id: int) -> Optional[dict]:
        try:
            from app.utils import db_init
            conn = db_init.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT profile_json FROM user_profile WHERE user_id=?", (user_id,))
            row = cur.fetchone()
            conn.close()
            if row and row["profile_json"]:
                return json.loads(row["profile_json"])
        except Exception as e:
            logger.warning(f"[agent] 读取用户画像失败 user={user_id}: {e}")
        return None

    def _save_profile(self, user_id: int, profile: dict) -> None:
        try:
            from app.utils import db_init
            conn = db_init.get_db_connection()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO user_profile (user_id, profile_json, updated_at)
                   VALUES (?, ?, datetime('now', 'localtime'))
                   ON CONFLICT(user_id) DO UPDATE SET
                       profile_json=excluded.profile_json,
                       updated_at=datetime('now', 'localtime')""",
                (user_id, json.dumps(profile, ensure_ascii=False)),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"[agent] 保存用户画像失败 user={user_id}: {e}")

    @staticmethod
    def _extract_json(raw: str) -> Optional[dict]:
        if not raw:
            return None
        text = raw.strip()
        # 去掉 ```json ... ``` 围栏
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.lower().startswith("json"):
                text = text[4:]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试截取第一个 { 到最后一个 }
            s, e = text.find("{"), text.rfind("}")
            if s != -1 and e != -1 and e > s:
                try:
                    data = json.loads(text[s:e + 1])
                except json.JSONDecodeError:
                    return None
            else:
                return None
        if not isinstance(data, dict):
            return None
        # 规范化为固定结构
        return {
            "industries": data.get("industries", []) or [],
            "tone_preferences": data.get("tone_preferences", []) or [],
            "summary": data.get("summary", "") or "",
        }


_PROFILE_PROMPT = """你是一个用户画像提取器。根据销售与华为云解决方案 AI 助手的最近对话，提炼该销售用户的偏好画像。
已有画像（可在此基础上增量更新，保留仍有价值的旧信息）：
{existing}

最近对话：
{recent}

请输出严格的 JSON（不要包含任何解释文字，不要使用 markdown 围栏），结构如下：
{{
  "industries": ["该用户常做的行业，如 制造/政务/金融，最多5个"],
  "tone_preferences": ["偏好的话术/表达风格倾向，如 政企正式/技术细节多/简洁直接，最多5个"],
  "summary": "一句话总体画像描述"
}}
"""


# ============================================================
# 单例工厂（复用 Agent 实例，节省资源）
# ============================================================

_agent_instance: Optional[SolutionAgent] = None


def get_agent(
    max_steps: int = 8,
    timeout: float = 120.0,
) -> SolutionAgent:
    """获取 Agent 单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SolutionAgent(
            max_steps=max_steps,
            timeout=timeout,
        )
    return _agent_instance


def reset_agent() -> None:
    """重置 Agent 单例（测试用）"""
    global _agent_instance
    _agent_instance = None
