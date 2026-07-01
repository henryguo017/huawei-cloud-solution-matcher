"""
工具定义 + 注册中心

每个 Tool 封装一个现有 Service，暴露给 Agent 的 ReAct 循环调用。
设计原则：
- 零改动现有代码，通过 import 对接
- 每个工具自描述（name + description + parameters），供 LLM 理解
- execute() 返回字符串 Observation，直接喂给下一轮 LLM
"""

import json
import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from app.services.knowledge_base import get_kb_user_context

logger = logging.getLogger(__name__)


def _get_kb():
    """根据当前上下文获取知识库实例（用户上下文或全局）"""
    user_id = get_kb_user_context()
    if user_id > 0:
        from api.dependencies import get_user_knowledge_base as _get_user_kb
        return _get_user_kb(user_id)
    from api.dependencies import get_knowledge_base as _get_global_kb
    return _get_global_kb()


class Tool:
    """单个工具定义"""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        func: Callable,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters  # JSON Schema 格式的参数定义
        self.func = func

    def to_prompt_desc(self) -> str:
        """生成给 LLM 看的工具描述"""
        params_str = json.dumps(self.parameters, ensure_ascii=False, indent=2)
        return f"- {self.name}: {self.description}\n  Parameters: {params_str}"

    async def execute(self, **kwargs) -> str:
        """执行工具，返回 Observation 字符串"""
        try:
            result = self.func(**kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            # 统一转为字符串
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"Tool [{self.name}] execution error: {e}")
            return f"Error: {str(e)}"


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def get_tools_prompt(self) -> str:
        """生成所有工具的 Prompt 描述"""
        if not self._tools:
            return "（无可用工具）"
        lines = []
        for tool in self._tools.values():
            lines.append(tool.to_prompt_desc())
        return "\n".join(lines)

    def get_tool_names(self) -> List[str]:
        return list(self._tools.keys())


# ============================================================
# 四个核心工具的具体实现
# ============================================================

async def _tool_analyze_demand(raw_input: str) -> str:
    """
    工具: analyze_demand
    作用: 将模糊的用户输入 → 结构化的需求分析（行业、场景、痛点、关键词）
    实现: 调用 LLM 进行意图分析，不需要现有 Service
    """
    from app.models.llm import get_llm_response

    prompt = f"""你是一位需求分析专家。用户表达了以下需求，但描述可能很模糊。请将这段模糊需求转化为结构化分析。

用户原始输入："{raw_input}"

请严格按以下 JSON 格式输出（不要输出其他内容）：

{{
  "industry": "最匹配的行业（如：制造业、智慧农业、智慧医疗、工业互联网等）",
  "scenarios": ["场景1", "场景2", "场景3"],
  "pain_points": ["痛点1", "痛点2", "痛点3"],
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
  "confidence": "高/中/低"
}}

注意：
1. keywords 要包含可用于向量检索的技术术语和产品名称
2. industry 从常见行业中选择：工业互联网、智慧交通、智慧农业、智慧医疗、智慧园区、智慧城市、智慧教育、智慧文旅、智慧能源、智慧金融、生物医药、零售、游戏、政务、汽车、互联网、制造
3. 如果用户提到了竞品名称（如阿里云、腾讯云、AWS等），在 keywords 中保留"""

    try:
        result = await get_llm_response(prompt)
        # 尝试解析 JSON，失败则返回原始文本
        try:
            # 提取 JSON 部分（LLM 可能在前后加了说明文字）
            json_start = result.find("{")
            json_end = result.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(result[json_start:json_end])
                return json.dumps(parsed, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, ValueError):
            pass
        return result
    except Exception as e:
        return json.dumps({"error": str(e), "raw_input": raw_input}, ensure_ascii=False)


async def _tool_search_kb(query: str) -> str:
    """
    工具: search_kb
    作用: 用结构化关键词搜索华为云知识库
    实现: 对接 KnowledgeBaseService.search()
    """
    kb = _get_kb()
    try:
        docs = await asyncio.to_thread(kb.search, query)
        if not docs:
            # 关键优化：空结果时给出明确的换关键词引导，避免 LLM 直接放弃
            return json.dumps({
                "status": "no_match",
                "query": query,
                "message": (
                    "用当前关键词「" + query + "」未检索到匹配的解决方案文档。"
                    "请务必换一组不同的关键词重试。建议：\n"
                    "1. 提取更核心的技术术语（如：工业物联网、预测性维护、数字孪生）\n"
                    "2. 使用更宽泛的行业词（如：制造业→工业互联网）\n"
                    "3. 尝试不同的产品角度（如：IoT平台、边缘计算、AI质检）\n"
                    "不要放弃，用新关键词再调用一次 search_kb！"
                ),
                "results": []
            }, ensure_ascii=False, indent=2)

        results = []
        for i, doc in enumerate(docs[:3]):  # 最多返回 3 条
            results.append({
                "index": i + 1,
                "content": doc.page_content[:300],  # 截断过长内容，避免 context 膨胀
                "source": doc.metadata.get("source", "unknown"),
                "industry": doc.metadata.get("industry", ""),
            })
        return json.dumps({
            "status": "ok",
            "query": query,
            "total_hits": len(docs),
            "results": results
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


async def _tool_search_competitor(competitor: str, industry: str = "") -> str:
    """
    工具: search_competitor
    作用: 搜索竞品在特定行业的方案信息
    实现: 对接 CompetitorAnalyzerService 的检索逻辑
    """
    kb = _get_kb()
    try:
        stats = kb.get_stats()
        if stats.get("total_documents", 0) == 0:
            return json.dumps({
                "status": "empty",
                "message": "知识库为空，无法检索竞品信息。",
                "results": []
            }, ensure_ascii=False)

        # 先检索华为方案
        hw_query = f"华为云" + (f"在{industry}行业的解决方案 竞争优势" if industry else "解决方案")
        hw_docs = await asyncio.to_thread(kb.search, hw_query)

        # 再检索竞品方案
        comp_query = f"{competitor}" + (f"在{industry}行业的解决方案 产品 优势" if industry else "解决方案")
        comp_docs = await asyncio.to_thread(kb.search, comp_query)

        hw_results = []
        for i, doc in enumerate(hw_docs[:3]):
            hw_results.append({
                "type": "华为云",
                "content": doc.page_content[:300],
                "source": doc.metadata.get("source", ""),
            })

        comp_results = []
        for i, doc in enumerate(comp_docs[:3]):
            comp_results.append({
                "type": competitor,
                "content": doc.page_content[:300],
                "source": doc.metadata.get("source", ""),
            })

        if not hw_results and not comp_results:
            return json.dumps({
                "status": "no_match",
                "competitor": competitor,
                "industry": industry,
                "message": (
                    "未检索到「" + competitor + "」在「" + (industry or "全行业") + "」的相关资料。"
                    "请尝试：\n"
                    "1. 去掉行业限制，用更宽的搜索范围\n"
                    "2. 换一个竞品名称（如：阿里云 → AWS）\n"
                    "3. 用不同的技术角度搜索（如：云原生、大数据、AI平台）\n"
                    "不要放弃，调整参数后再试一次！"
                ),
                "results": []
            }, ensure_ascii=False, indent=2)

        return json.dumps({
            "status": "ok",
            "competitor": competitor,
            "industry": industry,
            "huawei_docs_count": len(hw_docs),
            "competitor_docs_count": len(comp_docs),
            "results": hw_results + comp_results
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# ============================================================
# 工厂函数：创建默认工具集
# ============================================================

def create_default_tools() -> ToolRegistry:
    """创建包含 3 个核心工具的注册中心"""
    registry = ToolRegistry()

    # 1. analyze_demand — 需求分析
    registry.register(Tool(
        name="analyze_demand",
        description="分析模糊的用户需求，提取行业、场景、痛点和搜索关键词。当用户输入模糊、不明确时优先使用。",
        parameters={
            "type": "object",
            "properties": {
                "raw_input": {
                    "type": "string",
                    "description": "用户的原始输入文本"
                }
            },
            "required": ["raw_input"]
        },
        func=_tool_analyze_demand,
    ))

    # 2. search_kb — 知识库检索
    registry.register(Tool(
        name="search_kb",
        description="搜索华为云知识库，获取解决方案文档。使用从 analyze_demand 提取的关键词进行检索。",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询字符串，建议包含行业+场景+技术关键词，如 '制造业 工业物联网 预测性维护 华为云'"
                }
            },
            "required": ["query"]
        },
        func=_tool_search_kb,
    ))

    # 3. search_competitor — 竞品检索
    registry.register(Tool(
        name="search_competitor",
        description="搜索指定竞品在特定行业的方案资料。当用户提到竞品名称或需要对比时使用。",
        parameters={
            "type": "object",
            "properties": {
                "competitor": {
                    "type": "string",
                    "description": "竞品厂商名称，如：阿里云、腾讯云、AWS、微软Azure、西门子等"
                },
                "industry": {
                    "type": "string",
                    "description": "行业名称（可选），如：制造业、智慧医疗、工业互联网"
                }
            },
            "required": ["competitor"]
        },
        func=_tool_search_competitor,
    ))

    return registry
