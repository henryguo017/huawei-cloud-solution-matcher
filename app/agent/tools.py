"""
工具定义 + 注册中心

每个 Tool 封装一个现有 Service，暴露给 Agent 的 ReAct 循环调用。
设计原则：
- 零改动现有代码，通过 import 对接
- 每个工具自描述（name + description + parameters），供 LLM 理解
- execute() 返回字符串 Observation，直接喂给下一轮 LLM
"""

import os
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
        from app.services.knowledge_base import get_user_knowledge_base as _get_user_kb
        return _get_user_kb(user_id)
    from app.services.knowledge_base import get_knowledge_base as _get_global_kb
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
    实现: 委托共享服务 app/services/demand_analyzer.analyze_demand（2026-08-26 解耦：
         经典匹配链路也调用同一服务，Agent 包内改动不再波及经典链路）
    """
    from app.services.demand_analyzer import analyze_demand
    return await analyze_demand(raw_input)


async def _tool_search_kb(query: str, industry: str = "") -> str:
    """
    工具: search_kb
    作用: 用结构化关键词搜索华为云知识库
    实现: 对接 KnowledgeBaseService.search()
    """
    kb = _get_kb()
    try:
        logger.info(f"[search_kb] 开始查询, query={query[:50]}...")
        t0 = __import__('time').time()
        # A修复：召回 6 篇（与标准模式 4+2 对齐），并按行业过滤收敛到客户行业
        docs = await asyncio.to_thread(kb.search_huawei, query, 6, filter_industry=(industry or None))
        elapsed = round(__import__('time').time() - t0, 1)
        logger.info(f"[search_kb] 查询完成, 耗时={elapsed}s, 结果数={len(docs)}")
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
        for i, doc in enumerate(docs[:6]):  # A修复：最多返回 6 条，提升召回覆盖
            results.append({
                "index": i + 1,
                # A修复：截断到 1000 字（原 300 字丢失过多方案细节），平衡上下文量与信息完整度
                "content": doc.page_content[:1000],
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
        hw_query = "华为云" + (f"在{industry}行业的解决方案 竞争优势" if industry else "解决方案")
        hw_docs = await asyncio.to_thread(kb.search_huawei, hw_query, 6)

        # 再检索竞品方案
        comp_query = f"{competitor}" + (f"在{industry}行业的解决方案 产品 优势" if industry else "解决方案")
        comp_docs = await asyncio.to_thread(kb.search_competitor, comp_query, 6)

        hw_results = []
        for i, doc in enumerate(hw_docs[:6]):  # A修复：6 篇 + 1000 字
            hw_results.append({
                "type": "华为云",
                "content": doc.page_content[:1000],
                "source": doc.metadata.get("source", ""),
            })

        comp_results = []
        for i, doc in enumerate(comp_docs[:6]):  # A修复：6 篇 + 1000 字
            comp_results.append({
                "type": competitor,
                "content": doc.page_content[:1000],
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
# 阶段1 新增：文件交互工具（读取/落盘/列举）
# ============================================================

async def _tool_read_customer_file(path: str) -> str:
    """
    工具: read_customer_file
    作用: 读取客户上传的任意格式文件（docx/xlsx/pdf/pptx/txt/csv/md/图片），
          提取纯文本供需求分析。图片经 OCR 转文字。
    实现: 复用 file_security 白名单校验 + parsers 多格式解析
    """
    from app.services.knowledge_base import get_kb_user_context
    from app.agent.file_security import safe_resolve
    from app.agent.parsers.read_file import extract_text, chunk_text

    user_id = get_kb_user_context()
    if user_id <= 0:
        return "Error: 未登录用户无法读取文件"

    try:
        abs_path = safe_resolve(user_id, path)
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.exists(abs_path):
        return f"Error: 文件不存在: {path}"

    text = extract_text(abs_path)
    if text.startswith("Error:"):
        return text

    # 不盲截断：返回全量；超长文本按重叠窗口分块，确保全部内容进入上下文、零丢弃
    chunks = chunk_text(text)
    if len(chunks) == 1:
        return f"【客户文件内容 {path}】\n{text}"
    return (
        f"【客户文件内容 {path}（共 {len(chunks)} 段，已全量保留）】\n"
        + "\n---\n".join(f"第{i + 1}段:\n{c}" for i, c in enumerate(chunks))
    )




async def _tool_list_dir(dir: str = "") -> str:
    """
    工具: list_dir
    作用: 列出用户白名单目录下的文件，供 Agent 选择/确认
    """
    from app.services.knowledge_base import get_kb_user_context
    from app.agent.file_security import safe_resolve, get_user_root

    user_id = get_kb_user_context()
    if user_id <= 0:
        return "Error: 未登录用户无法列举文件"

    try:
        target = safe_resolve(user_id, dir) if dir else str(get_user_root(user_id))
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.isdir(target):
        return f"Error: 目录不存在: {dir}"

    try:
        entries = []
        for name in sorted(os.listdir(target)):
            full = os.path.join(target, name)
            kind = "目录" if os.path.isdir(full) else "文件"
            entries.append(f"- [{kind}] {name}")
        if not entries:
            return f"（目录为空: {dir or '用户根目录'}）"
        return "用户目录文件列表：\n" + "\n".join(entries)
    except Exception as e:
        return f"Error: 列举失败: {e}"


async def _tool_generate_doc(fmt: str = "word", content: str = "", report_type: str = "solution") -> str:
    """
    工具: generate_doc（P1-2）
    作用: 把当前 Agent 终稿导出为 Word/PDF 方案书（做成 Agent 工具，用户说「导出成 Word」时调用）。
    实现: 复用 ReportGeneratorService.generate_report（统一单例 get_report_generator，下载路由同源可查）。
    注意: content 由 harness._intercept_generate_doc 从 self._last_draft 注入（LLM 没有终稿文本，不靠它传参）。
    """
    from app.services.report_generator import get_report_generator, ReportType, ExportFormat
    rg = get_report_generator()
    if not content or len(content.strip()) < 30:
        return json.dumps({"status": "no_draft", "message": "当前还没有可导出的方案内容，请先生成方案。"}, ensure_ascii=False)
    try:
        ef = ExportFormat.PDF if str(fmt).lower() == "pdf" else (
            ExportFormat.PPTX if str(fmt).lower() == "pptx" else ExportFormat.WORD
        )
        rt = ReportType.COMPETITOR if str(report_type).lower() == "competitor" else ReportType.SOLUTION
        task = await asyncio.to_thread(rg.generate_report, rt, content, ef, {})
        if getattr(task.status, "value", str(task.status)) != "completed":
            return json.dumps({"status": "error", "message": getattr(task, "error_message", "生成失败")}, ensure_ascii=False)
        return json.dumps({
            "status": "ok",
            "download_url": task.download_url,
            "file_name": task.file_name,
            "task_id": task.task_id,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


async def _tool_web_search(query: str) -> str:
    """
    工具: web_search（P1-2）
    作用: 补充知识库之外的联网检索（华为云官网/白皮书/新闻/竞品动态）。
    实现: 可插拔 provider（Tavily 默认），未配置 WEB_SEARCH_PROVIDER 时优雅降级（仅基于知识库作答）。
    """
    from app.config import WEB_SEARCH_PROVIDER, WEB_SEARCH_MAX_PER_SESSION
    provider = (WEB_SEARCH_PROVIDER or "").strip().lower()
    if not provider:
        return json.dumps({
            "status": "disabled",
            "message": "当前未配置联网搜索，仅基于本地知识库作答。",
            "results": [],
        }, ensure_ascii=False)
    # 限流：本会话联网检索次数上限
    if getattr(_tool_web_search, "_count", 0) >= int(WEB_SEARCH_MAX_PER_SESSION or 3):
        return json.dumps({
            "status": "limited",
            "message": f"已达本会话联网检索上限（{WEB_SEARCH_MAX_PER_SESSION} 次）。",
            "results": [],
        }, ensure_ascii=False)
    try:
        from app.agent.tools_search import get_web_search_provider
        p = get_web_search_provider(provider)
        results = await asyncio.to_thread(p.search, query, top_n=5)
        _tool_web_search._count = getattr(_tool_web_search, "_count", 0) + 1
        # URL 脱敏：只留来源域名，不在 observation 暴露完整外链（防幻觉外链；LLM 只引来源名）
        slim = [{"domain": r.get("domain", ""), "title": r.get("title", "")} for r in (results or [])]
        return json.dumps({
            "status": "ok",
            "count": len(slim),
            "results": slim,
        }, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[web_search] 检索失败: {e}")
        return json.dumps({"status": "error", "message": str(e), "results": []}, ensure_ascii=False)


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
        description="搜索华为云知识库，获取解决方案文档。使用从 analyze_demand 提取的关键词进行检索；"
                    "已知行业时传入 industry 可收敛检索到该行业，提升相关性。",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询字符串，建议包含行业+场景+技术关键词，如 '制造业 工业物联网 预测性维护 华为云'"
                },
                "industry": {
                    "type": "string",
                    "description": "行业名称（可选）。传入后检索会收敛到该行业（如：制造业、智慧医疗、工业互联网），不传则全行业检索。"
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

    # 4. read_customer_file — 读取客户上传的任意格式文件（含图片 OCR）
    registry.register(Tool(
        name="read_customer_file",
        description="读取客户上传的需求资料文件，提取纯文本供需求分析。支持 Word/Excel/PDF/PPT/TXT/CSV/MD，以及图片（自动 OCR 识别文字）。当用户提到客户资料、上传文件、招标书、需求文档时使用。输入为相对路径（如 customer_uploads/xxx.docx）。",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件的相对路径，如 customer_uploads/客户需求.docx"
                }
            },
            "required": ["path"]
        },
        func=_tool_read_customer_file,
    ))

    # 5. list_dir — 列举用户目录文件
    registry.register(Tool(
        name="list_dir",
        description="列出用户文件目录下的文件，确认有哪些上传资料可用。",
        parameters={
            "type": "object",
            "properties": {
                "dir": {
                    "type": "string",
                    "description": "相对目录路径，留空表示用户根目录"
                }
            }
        },
        func=_tool_list_dir,
    ))

    # 6. generate_doc — 导出方案书（Word/PDF）
    registry.register(Tool(
        name="generate_doc",
        description="将已生成的方案导出为 Word 或 PDF 文档。当用户明确要求「导出/生成 Word/PDF 方案书」或说「导出成 Word」时调用。format 可选 word/pdf（默认 word）。",
        parameters={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "导出格式：word 或 pdf（默认 word）",
                }
            },
        },
        func=_tool_generate_doc,
    ))

    # 7. web_search — 联网检索（知识库之外的互联网资料）
    registry.register(Tool(
        name="web_search",
        description="检索知识库之外的互联网最新资料（华为云产品页/白皮书/官方新闻/竞品动态）。当用户要求查官网、查最新资讯、或本地知识库覆盖不到时调用。",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "联网检索关键词，建议包含产品名+资料类型，如「华为云 ModelArts 最新特性」「阿里云 2026 发布」",
                }
            },
            "required": ["query"],
        },
        func=_tool_web_search,
    ))

    return registry
