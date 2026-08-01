import asyncio
from app.models.llm import get_llm_response


class CompetitorAnalyzerService:
    """DeepSeek版本 竞品分析服务——支持竞品知识库检索"""

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

        self.prompt_template = """
你是华为云竞争分析专家。请基于提供的华为云资料和{competitor}资料，分析{competitor}在{industry}行业的解决方案，生成华为云差异化优势和销售话术。

【华为云方案资料】
{hw_context}

【{competitor}方案资料】
{competitor_context}

请按以下格式回答：

## 1. {competitor}方案分析
基于竞品资料，列出其核心卖点（3-5个）和主要劣势（3-5个）

## 2. 华为云 vs {competitor} 差异化优势
列出华为云的3-5个差异化优势，尽量含具体数据或技术对比

## 3. 销售话术
针对客户可能提出的价格质疑、功能对比等问题，给出华为云的应对话术（至少3条）

## 4. 成功案例对比
列出华为云在{industry}行业的标杆案例，并与{competitor}的案例进行对比

## 5. 竞争策略建议
给出针对{competitor}的差异化打法建议（至少3条），如：
- 强调华为云的哪些技术/服务优势
- 回避哪些话题
- 适合攻击{competitor}的哪些软肋

要求：客观、具体、有数据支撑。如果某方面信息不足，如实指出。
        """

    async def analyze(self, competitor, industry):
        """竞品分析：同时检索华为方案和竞品资料"""
        import logging
        log = logging.getLogger(__name__)

        # 检查知识库是否为空
        try:
            stats = self.kb_service.get_stats()
            kb_empty = (stats.get("total_documents", 0) == 0)
        except Exception:
            kb_empty = True

        if kb_empty:
            hw_docs = []
            competitor_docs = []
        else:
            # 检索华为云方案
            hw_query = f"华为云在{industry}行业的解决方案 竞争优势 成功案例"
            try:
                hw_docs = await asyncio.to_thread(self.kb_service.search, hw_query)
            except Exception as e:
                log.warning(f"华为云方案检索异常，跳过: {e}")
                hw_docs = []

            # 检索竞品方案
            competitor_query = f"{competitor}在{industry}行业的解决方案 产品 优势 案例"
            try:
                competitor_docs = await asyncio.to_thread(self.kb_service.search, competitor_query)
            except Exception as e:
                log.warning(f"竞品方案检索异常，跳过: {e}")
                competitor_docs = []

        hw_context = "\n---\n".join([doc.page_content for doc in hw_docs]) if hw_docs else "（知识库中暂无华为云该行业方案资料）"
        competitor_context = "\n---\n".join([doc.page_content for doc in competitor_docs]) if competitor_docs else ""

        # 如果竞品资料为空，尝试更宽泛的搜索
        if not competitor_context.strip() and not kb_empty:
            competitor_query2 = f"{competitor} 行业解决方案 {industry}"
            try:
                competitor_docs2 = await asyncio.to_thread(self.kb_service.search, competitor_query2)
            except Exception as e:
                log.warning(f"宽泛竞品检索异常，跳过: {e}")
                competitor_docs2 = []
            competitor_context = "\n---\n".join([doc.page_content for doc in competitor_docs2]) if competitor_docs2 else "（知识库中暂无{competitor}在{industry}行业的详细资料，请基于公开信息和华为云优势进行分析）".format(competitor=competitor, industry=industry)

        # 如果华为方案也为空，使用 fallback
        if (not hw_docs or not hw_context.strip() or hw_context.startswith("（知识库中暂无")) and \
           (not competitor_docs or not competitor_context.strip() or competitor_context.startswith("（知识库中暂无")):
            fallback_prompt = f"""
你是华为云资深竞争分析专家。请分析华为云在{industry}行业与{competitor}的竞争态势。

虽然当前知识库中暂时没有相关的竞争分析文档，但请你基于华为云的核心优势和行业最佳实践，给出以下分析：

## 1. {competitor}在{industry}行业的可能卖点
基于公开信息，列出{competitor}在{industry}行业可能的3-5个宣传卖点

## 2. {competitor}方案可能的劣势
列出{competitor}在{industry}行业可能存在的客观不足

## 3. 华为云的核心优势
列出华为云的3-5个差异化优势：
- 端云协同优势（华为拥有完整的终端和云产品线）
- AI技术优势（盘古大模型、ModelArts等）
- 安全可信优势（自主可控的技术体系）
- 服务网络优势（全国范围的本地化服务）
- 行业深耕优势（在各行业的深厚积累）

## 4. 销售应对建议
给出3-5个针对{competitor}的销售应对建议

## 5. 建议下一步行动
建议联系华为云行业专家获取详细的竞争分析资料

注意：
1. 明确说明当前是基于通用知识给出的分析
2. 建议补充更多行业竞争分析文档以获得更精准的分析
"""
            answer_result = await get_llm_response(fallback_prompt)
            return {
                "answer": answer_result,
                "source_documents": []
            }

        # 拼接提示词
        final_prompt = self.prompt_template.format(
            competitor=competitor,
            industry=industry,
            hw_context=hw_context,
            competitor_context=competitor_context
        )

        # 调用模型
        answer_result = await get_llm_response(final_prompt)

        # 合并源文档
        all_docs = hw_docs + competitor_docs

        return {
            "answer": answer_result,
            "source_documents": all_docs
        }

    async def compare(self, competitor1, competitor2, industry):
        """多竞品三方横评：华为云 vs 竞品1 vs 竞品2，返回 Markdown 分析 + 结构化对比表"""
        import logging
        log = logging.getLogger(__name__)

        # 检索华为云 + 两家竞品资料
        try:
            stats = self.kb_service.get_stats()
            kb_empty = (stats.get("total_documents", 0) == 0)
        except Exception:
            kb_empty = True

        hw_docs, c1_docs, c2_docs = [], [], []
        if not kb_empty:
            hw_query = f"华为云在{industry}行业的解决方案 竞争优势 成功案例"
            try:
                hw_docs = await asyncio.to_thread(self.kb_service.search, hw_query)
            except Exception as e:
                log.warning(f"华为云方案检索异常，跳过: {e}")

            for name, container in ((competitor1, "c1"), (competitor2, "c2")):
                try:
                    docs = await asyncio.to_thread(self.kb_service.search, f"{name}在{industry}行业的解决方案 产品 优势 案例")
                    if container == "c1":
                        c1_docs = docs
                    else:
                        c2_docs = docs
                except Exception as e:
                    log.warning(f"竞品 {name} 检索异常，跳过: {e}")

        hw_context = "\n---\n".join([d.page_content for d in hw_docs]) if hw_docs else "（知识库中暂无华为云该行业方案资料）"
        c1_context = "\n---\n".join([d.page_content for d in c1_docs]) if c1_docs else f"（知识库中暂无{competitor1}在{industry}行业的详细资料，请基于公开信息分析）"
        c2_context = "\n---\n".join([d.page_content for d in c2_docs]) if c2_docs else f"（知识库中暂无{competitor2}在{industry}行业的详细资料，请基于公开信息分析）"

        compare_prompt = f"""你是华为云资深竞争分析专家。请对华为云、{competitor1}、{competitor2}三家在{industry}行业进行三方横向对比分析。

【华为云方案资料】
{hw_context}

【{competitor1}方案资料】
{c1_context}

【{competitor2}方案资料】
{c2_context}

请按以下格式输出：

## 一、三方横向对比表（必须用 Markdown 表格，格式如下）
| 对比维度 | 华为云 | {competitor1} | {competitor2} |
| --- | --- | --- | --- |
| 产品能力 | ... | ... | ... |
| 价格策略 | ... | ... | ... |
| 生态建设 | ... | ... | ... |
| 安全合规 | ... | ... | ... |
| 行业案例 | ... | ... | ... |
| 服务支持 | ... | ... | ... |
（对比维度至少 6 个，可自行补充；每格内容要具体，避免空泛套话）

## 二、华为云 vs {competitor1} 差异化优势
列出 2-3 个华为云相对{competitor1}的差异化优势

## 三、华为云 vs {competitor2} 差异化优势
列出 2-3 个华为云相对{competitor2}的差异化优势

## 四、三方竞争格局判断
说明在当前行业下，华为云与两家竞品各自的竞争位置和应对策略

## 五、销售话术
针对客户"三家怎么选"的疑问，给出华为云的推荐话术（至少 3 条）

要求：客观、具体、有数据支撑。如果某方面信息不足，如实指出。"""

        answer_result = await get_llm_response(compare_prompt)

        # 结构化对比表：请求模型额外输出 JSON（供前端渲染真表格）
        import json as _json
        table_prompt = f"""你是数据整理专家。根据下面的三方对比分析，提取成结构化对比表格 JSON。

【三方对比分析】
{answer_result}

要求：
1. 输出严格 JSON（不要任何其他文字），格式：{{"headers": ["对比维度", "华为云", "{competitor1}", "{competitor2}"], "rows": [["产品能力", "内容", "内容", "内容"], ...]}}
2. 每格内容精简到 40 字以内，可直接展示
3. 至少 6 行对比维度（产品能力/价格策略/生态建设/安全合规/行业案例/服务支持等）
4. 单元格内不要用竖线 | 和换行符"""
        table_text = ""
        try:
            table_text = await get_llm_response(table_prompt)
            # 提取 JSON（可能被 ```json 包裹）
            import re as _re
            m = _re.search(r"\{.*\}", table_text, _re.DOTALL)
            comparison = _json.loads(m.group(0)) if m else {}
            if not comparison.get("headers") or not comparison.get("rows"):
                comparison = None
        except Exception as e:
            log.warning(f"对比表 JSON 提取失败: {e}")
            comparison = None

        all_docs = hw_docs + c1_docs + c2_docs
        return {
            "answer": answer_result,
            "source_documents": all_docs,
            "comparison": comparison,
        }
