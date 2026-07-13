import asyncio
import json
import os
import logging
from typing import Optional, Dict, Any, List

from app.models.llm import get_llm_response
from app.services.solution_prompt import (
    build_industry_line,
    build_analysis_line,
    build_anti_hallucination,
    build_audience_tone,
    build_few_shot,
    build_format_block,
    build_playbook_text,
    build_references_section,
    parse_markdown_to_chapters,
)

logger = logging.getLogger(__name__)

# 行业剧本路径：优先 app/resources（随代码部署），回退 data/
_PLAYBOOK_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "industry_playbook.json")
_PLAYBOOK_FALLBACK = os.path.join("data", "industry_playbook.json")


class SolutionMatcherService:
    """华为云解决方案匹配服务（标准模式）"""

    def __init__(self, kb_service=None):
        """
        Args:
            kb_service: 外部传入的知识库服务实例。如果不传，使用全局默认KB。
        """
        if kb_service is not None:
            self.kb_service = kb_service
        else:
            from api.dependencies import get_knowledge_base
            self.kb_service = get_knowledge_base()

        # 加载行业剧本（用于增强行业针对性）
        self._playbook = self._load_playbook()

    # ============================================================
    # 资源加载
    # ============================================================
    def _load_playbook(self) -> dict:
        for path in (_PLAYBOOK_PATH, _PLAYBOOK_FALLBACK):
            try:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
            except Exception as e:
                logger.warning(f"行业剧本加载失败 {path}: {e}")
        return {}

    # ============================================================
    # 上下文来源标注（防幻觉 + 区分华为/竞品）
    # ============================================================
    def _build_context(self, docs, competitor_companies: set) -> str:
        """将检索结果拼成带来源标注的上下文，并限制数量防止上下文膨胀"""
        if not docs:
            return ""
        parts = []
        # 限制 top6，避免上下文过长导致 LLM 混淆引用
        for i, doc in enumerate(docs[:6], 1):
            meta = getattr(doc, "metadata", {}) or {}
            source = meta.get("source", "未知来源")
            industry = meta.get("industry", "")
            # 运行时推断类型：industry 命中竞品公司名 → 竞品，否则华为云方案
            doc_type = "竞品方案" if industry in competitor_companies else "华为云方案"
            parts.append(
                f"[资料{i} | 来源:{source} | 行业:{industry or '通用'} | 类型:{doc_type}]\n"
                f"{doc.page_content}"
            )
        return "\n\n".join(parts)

    # ============================================================
    # 行业剧本注入（复用统一模块）
    # ============================================================
    def _playbook_text(self, industry: str) -> str:
        return build_playbook_text(self._playbook, industry)

    # ============================================================
    # 复用需求结构化（analyze_demand），增强针对性
    # ============================================================
    async def _analyze_demand(self, customer_demand: str) -> Dict[str, Any]:
        """复用 Agent 模式的 analyze_demand 工具，把模糊需求结构化。失败则静默返回空。"""
        try:
            from app.agent.tools import _tool_analyze_demand
            raw = await _tool_analyze_demand(customer_demand)
            try:
                j = raw.find("{")
                k = raw.rfind("}") + 1
                if j >= 0 and k > j:
                    return json.loads(raw[j:k])
            except (json.JSONDecodeError, ValueError):
                pass
        except Exception as e:
            logger.warning(f"需求结构化失败（跳过，降级为通用生成）: {e}")
        return {}

    # ============================================================
    # Prompt 组装（复用统一增强模块，保证与 Agent 模式一致）
    # ============================================================
    def _build_prompt(self, question: str, context: str, industry: str,
                       playbook_text: str, demand_analysis: Dict[str, Any]) -> str:
        industry_line = build_industry_line(industry)
        analysis_line = build_analysis_line(demand_analysis)
        anti_hallucination = build_anti_hallucination()
        audience = build_audience_tone()
        few_shot = build_few_shot()
        format_block = build_format_block()

        prompt = (
            "你是华为云解决方案专家，为售前场景提供方案建议。\n\n"
            f"{industry_line}"
            f"{analysis_line}"
            f"{playbook_text}\n\n"
            f"客户需求：{question}\n\n"
            f"相关资料：\n{context}\n\n"
            f"{anti_hallucination}"
            f"{audience}\n"
            f"{few_shot}\n"
            f"{format_block}"
        )
        return prompt

    # ============================================================
    # 结构化解析（供报告生成器消费）— 复用统一模块
    # ============================================================
    def _parse_markdown_to_chapters(self, markdown: str) -> List[Dict[str, Any]]:
        """把 Markdown 方案解析为章节结构（与 report_generator 的章节格式一致）"""
        return parse_markdown_to_chapters(markdown)

    # ============================================================
    # 统一增强生成入口（供 Agent 模式复用，保证三模式质量一致）
    # ============================================================
    async def generate_enhanced(
        self,
        demand: str,
        context: str,
        industry: Optional[str] = None,
        demand_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """用统一的增强管线生成方案（含来源标注 / 防幻觉 / 话术 / 14章结构）。

        Args:
            demand: 客户需求描述
            context: 已格式化为 [资料N|来源:...] 的参考材料上下文
            industry: 行业（可选，用于剧本注入）
            demand_analysis: 结构化需求（可选）

        Returns:
            {"answer": str, "solution_json": List[Dict]}
        """
        playbook_text = self._playbook_text(industry or "")
        final_prompt = self._build_prompt(
            question=demand,
            context=context,
            industry=industry or "",
            playbook_text=playbook_text,
            demand_analysis=demand_analysis or {},
        )
        answer = await get_llm_response(final_prompt)
        # 追加『参考资料』节：把正文中的 [资料N] 标注映射回真实出处，
        # 避免悬空引用（读者不知 [资料N] 指向哪份资料）。仅当答案未自带时才追加。
        if "参考资料" not in answer:
            refs = build_references_section(context)
            if refs:
                answer = answer.rstrip() + "\n" + refs
        return {
            "answer": answer,
            "solution_json": parse_markdown_to_chapters(answer),
        }

    # ============================================================
    # 主入口
    # ============================================================
    async def match(self, customer_demand, industry: Optional[str] = None):
        """
        标准模式匹配。
        - industry: 可选，由调用方传入（如向导模式采集的行业）；为空则内部复用 analyze_demand 推断。
        """
        # 1. 知识库检索
        try:
            stats = self.kb_service.get_stats()
            kb_empty = (stats.get("total_documents", 0) == 0)
            competitor_companies = set(stats.get("competitor_companies", []) or [])
        except Exception:
            kb_empty = True
            competitor_companies = set()

        if kb_empty:
            docs = []
            context_content = ""
        else:
            try:
                docs = await asyncio.to_thread(self.kb_service.search, customer_demand)
            except Exception as e:
                logger.warning(f"向量检索异常，回退到 LLM 模式: {e}")
                docs = []
            context_content = self._build_context(docs, competitor_companies)

        # 2. 需求结构化（增强针对性）—— 若未显式传入行业
        demand_analysis: Dict[str, Any] = {}
        if not industry:
            demand_analysis = await self._analyze_demand(customer_demand)
            industry = demand_analysis.get("industry")
        playbook_text = self._playbook_text(industry or "")

        # 3. 知识库为空 → 通用兜底（同样注入行业/话术约束）
        if not docs or not context_content.strip():
            fallback_prompt = self._build_fallback_prompt(customer_demand, industry, playbook_text)
            answer_result = await get_llm_response(fallback_prompt)
            # 追加参考资料节（兜底模式 context 可能为空，build_references_section 会安全返回空串）
            if "参考资料" not in answer_result:
                refs = build_references_section(context_content)
                if refs:
                    answer_result = answer_result.rstrip() + "\n" + refs
            return {
                "answer": answer_result,
                "source_documents": [],
                "solution_json": self._parse_markdown_to_chapters(answer_result),
            }

        # 4. 正常生成
        final_prompt = self._build_prompt(
            question=customer_demand,
            context=context_content,
            industry=industry or "",
            playbook_text=playbook_text,
            demand_analysis=demand_analysis,
        )
        answer_result = await get_llm_response(final_prompt)

        # 追加『参考资料』节，让 [资料N] 标注可追溯
        if "参考资料" not in answer_result:
            refs = build_references_section(context_content)
            if refs:
                answer_result = answer_result.rstrip() + "\n" + refs

        return {
            "answer": answer_result,
            "source_documents": docs,
            "solution_json": self._parse_markdown_to_chapters(answer_result),
        }

    def _build_fallback_prompt(self, customer_demand: str, industry: str, playbook_text: str) -> str:
        """知识库为空时的通用生成 prompt（保留行业/话术/防幻觉约束）"""
        industry_line = f"客户所属行业：{industry}\n" if industry else ""
        anti = build_anti_hallucination()
        audience = build_audience_tone()
        return f"""你是华为云资深解决方案专家，拥有15年以上行业解决方案设计经验。客户提出了以下需求：

{customer_demand}

{industry_line}{playbook_text}

虽然当前知识库中暂时没有相关的华为云解决方案文档，但请你基于华为云的产品体系、技术能力和行业最佳实践，给出专业、深入的建议：

## 1. 执行摘要
（200字内：价值主张 + 3个核心要点，量化优先）

## 2. 需求深度分析
- 客户背景理解（从需求描述推断行业、规模）
- 核心需求识别（3-5个核心业务需求点）
- 痛点根因分析

## 3. 方案总体架构
（分层描述：边缘接入 / 网络与连接 / 平台 / AI能力 / 应用；说明各层职责）

## 4. 推荐解决方案方向
- 主推方向（如：工业互联网、智慧园区等）及选择理由
- 技术架构思路、适用性分析

## 5. 可能适用的华为云产品
每个产品说明：名称与定位、在本方案中的角色、关键能力与优势（可用表格：| 产品 | 角色 | 关键能力 | 适用场景 |）

## 6. 关键业务价值
（用业务语言讲降本/增效/合规/控风险，量化，无依据标注『需进一步核实』）

## 7. 实施路径建议
- 第一阶段：基础设施搭建（目标+交付物+周期）
- 第二阶段：核心功能上线（目标+交付物+周期）
- 第三阶段：深化应用推广（目标+交付物+周期）

## 8. 投资回报与成功案例
（测算口径+区间；可引用公开案例，无来源标注『需进一步核实』）

## 9. 服务保障与商务指引
（7x24支持/专家服务/POC；计费模式说明，标注『以华为云官方报价为准』）

## 10. 风险与应对
（3-5个主要风险 + 应对措施）

## 11. 下一步行动建议
（立即可执行 / 短期 / 中长期，含技术交流与POC）

注意：
1. 明确说明当前是基于华为云产品体系和通用知识给出的建议（知识库暂缺文档）
2. 每个部分都要具体、量化，避免泛泛而谈
3. 建议客户联系华为云销售获取针对其行业的详细解决方案
4. 可通过上传更多行业解决方案文档来获得更精准的匹配

{anti}{audience}"""
