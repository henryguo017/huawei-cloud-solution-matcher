import asyncio
import json
import os
import logging
from typing import Optional, Dict, Any, List

from app.models.llm import get_llm_response

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
    # 行业剧本注入
    # ============================================================
    def _playbook_text(self, industry: str) -> str:
        if not industry or industry not in self._playbook:
            return ""
        pb = self._playbook.get(industry, {})
        lines = [f"【{industry}行业作战手册（内部参考，用于贴合行业语境，不代表对外承诺）】"]
        if pb.get("pain_points"):
            lines.append("常见痛点：" + "、".join(pb["pain_points"]))
        if pb.get("scenarios"):
            lines.append("典型场景：" + "、".join(pb["scenarios"]))
        if pb.get("regulatory"):
            lines.append("监管/合规要点：" + "、".join(pb["regulatory"]))
        if pb.get("huawei_products"):
            lines.append("常用华为云产品组合：" + "、".join(pb["huawei_products"]))
        if pb.get("roi"):
            lines.append("ROI 量化口径参考：" + "、".join(pb["roi"]))
        return "\n".join(lines)

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
    # Prompt 组装
    # ============================================================
    def _build_prompt(self, question: str, context: str, industry: str,
                       playbook_text: str, demand_analysis: Dict[str, Any]) -> str:
        industry_line = (
            f"客户所属行业：{industry}\n" if industry
            else "客户所属行业：未明确（请基于需求推断，并在『需求分析』中说明你的假设）\n"
        )

        analysis_line = ""
        if demand_analysis:
            ap = demand_analysis.get("pain_points") or []
            asc = demand_analysis.get("scenarios") or []
            ak = demand_analysis.get("keywords") or []
            if ap or asc or ak:
                analysis_line = (
                    "已结构化需求（用于增强针对性，仅作参考）：\n"
                    f"- 痛点：{'、'.join(ap)}\n"
                    f"- 场景：{'、'.join(asc)}\n"
                    f"- 检索关键词：{'、'.join(ak)}\n"
                )

        anti_hallucination = (
            "【防幻觉硬约束】\n"
            "1. 第6节『投资回报』中的任何数字、第7节『成功案例』中的任何案例，"
            "只能来自下方【相关资料】中明确给出的内容。\n"
            "2. 若资料中未提供对应数字或案例，必须明确写明『需进一步核实 / 以实际为准』，"
            "严禁编造具体数值、客户名称或案例细节。\n"
            "3. 引用资料时可在句末标注来源文件名（如：据《xxx》）。\n"
        )

        audience = (
            "【受众与话术】\n"
            "面向客户决策层（非技术人员）：用业务语言讲价值（降本 / 增效 / 合规 / 控风险），"
            "少堆砌技术参数；竞品对比使用『差异化优势』框架，客观、不贬低对手；"
            "整体语气专业、有说服力，像资深售前顾问。\n"
        )

        few_shot = (
            "【输出范例（仅参考风格，数字必须来自资料，无资料则标注『需进一步核实』）】\n"
            "## 3. 核心价值\n"
            "- 运维成本下降约30%：通过预测性维护将非计划停机从年均12次降至4次以内（据《工业互联网预测性维护方案》）。\n"
            "- 质检效率提升5倍：AI视觉替代人工目检，漏检率由2%降至0.3%。\n"
        )

        format_block = (
            "请严格按以下 Markdown 格式回答（章节标题必须带 ## 编号；"
            "不要使用 *** / --- 等装饰分隔符，直接用 ## 分节即可）：\n"
            "## 1. 执行摘要\n"
            "（面向决策层，200字以内：一句话价值主张 + 3个核心要点，尽量量化）\n"
            "## 2. 需求分析\n"
            "（客户业务背景、核心痛点量化、建设目标与可衡量的成功标准）\n"
            "## 3. 方案总体架构\n"
            "（分层描述：边缘接入层 / 网络与连接层 / 平台层 / AI能力层 / 应用层；说明各层职责与协同关系）\n"
            "## 4. 推荐方案与核心能力\n"
            "（主推方案概述 + 3-5项核心能力，每项对应一个痛点）\n"
            "## 5. 产品组合与定位\n"
            "（用 Markdown 表格呈现：| 产品 | 在本方案中的角色 | 关键能力 | 适用场景 |；每个产品说明其定位）\n"
            "## 6. 关键业务价值\n"
            "（用业务语言讲降本/增效/合规/控风险；量化优先，无依据标注『需进一步核实』）\n"
            "## 7. 典型部署与实施路径\n"
            "（分3个阶段，每阶段写：阶段目标 + 关键任务 + 交付物 + 周期）\n"
            "## 8. 投资回报分析\n"
            "（测算口径 + 区间估计 + 投资回收期；数字须来自【相关资料】，否则标注『需进一步核实』）\n"
            "## 9. 成功案例参考\n"
            "（可引用华为云公开案例，注明行业与成效；无确切来源标注『需进一步核实』）\n"
            "## 10. 服务保障与支持\n"
            "（7x24支持、专家服务、POC验证、培训认证等具体保障）\n"
            "## 11. 商务与报价指引\n"
            "（说明常见计费模式[按需/包年/按量]与商务流程，标注『具体以华为云官方报价为准』）\n"
            "## 12. 风险与应对\n"
            "（3-5个主要风险 + 对应的应对措施）\n"
            "## 13. 下一步行动建议\n"
            "（3步具体行动，含技术交流 / POC / 推广计划）\n"
            "每个章节至少3-5个具体要点，避免空泛；能用量化处务必量化；"
            "可在章节内用 ### 细分小标题增强层次。\n"
        )

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
    # 结构化解析（供报告生成器消费）
    # ============================================================
    def _parse_markdown_to_chapters(self, markdown: str) -> List[Dict[str, Any]]:
        """把 Markdown 方案解析为章节结构（与 report_generator 的章节格式一致）"""
        chapters = []
        lines = (markdown or "").split("\n")
        current_chapter = None
        current_content: List[str] = []

        for line in lines:
            if line.startswith("## "):
                if current_chapter:
                    current_chapter["content"] = "\n".join(current_content).strip()
                    chapters.append(current_chapter)
                current_chapter = {"title": line[3:].strip(), "content": "", "sections": []}
                current_content = []
            elif line.startswith("### "):
                if current_content and current_chapter:
                    current_chapter["content"] = "\n".join(current_content).strip()
                    current_content = []
                if current_chapter:
                    current_chapter["sections"].append({"title": line[4:].strip(), "content": ""})
            else:
                if current_chapter and current_chapter.get("sections"):
                    current_chapter["sections"][-1]["content"] += line + "\n"
                else:
                    current_content.append(line)

        if current_chapter:
            current_chapter["content"] = "\n".join(current_content).strip()
            chapters.append(current_chapter)
        return chapters

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

        return {
            "answer": answer_result,
            "source_documents": docs,
            "solution_json": self._parse_markdown_to_chapters(answer_result),
        }

    def _build_fallback_prompt(self, customer_demand: str, industry: str, playbook_text: str) -> str:
        """知识库为空时的通用生成 prompt（保留行业/话术/防幻觉约束）"""
        industry_line = f"客户所属行业：{industry}\n" if industry else ""
        anti = (
            "【防幻觉硬约束】投资回报数字、成功案例只能基于你掌握的华为云公开产品知识；"
            "不确定的具体数值写明『需进一步核实』，严禁编造客户案例。\n"
        )
        audience = (
            "面向客户决策层，用业务语言讲价值（降本/增效/合规/控风险），竞品对比用差异化优势框架、客观不贬低。\n"
        )
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
