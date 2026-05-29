from app.models.llm import get_llm_response
from app.services.knowledge_base import KnowledgeBaseService

class CompetitorAnalyzerService:
    """DeepSeek版本 竞品分析服务——支持竞品知识库检索"""
    
    def __init__(self):
        self.kb_service = KnowledgeBaseService()

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

    def analyze(self, competitor, industry):
        """竞品分析：同时检索华为方案和竞品资料"""
        # 检索华为云方案
        hw_query = f"华为云在{industry}行业的解决方案 竞争优势 成功案例"
        hw_docs = self.kb_service.search(hw_query)
        hw_context = "\n---\n".join([doc.page_content for doc in hw_docs]) if hw_docs else "（知识库中暂无华为云该行业方案资料）"
        
        # 检索竞品方案
        competitor_query = f"{competitor}在{industry}行业的解决方案 产品 优势 案例"
        competitor_docs = self.kb_service.search(competitor_query)
        competitor_context = "\n---\n".join([doc.page_content for doc in competitor_docs]) if competitor_docs else ""
        
        # 如果竞品资料为空，尝试更宽泛的搜索
        if not competitor_context.strip():
            competitor_query2 = f"{competitor} 行业解决方案 {industry}"
            competitor_docs2 = self.kb_service.search(competitor_query2)
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
            answer_result = get_llm_response(fallback_prompt)
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
        answer_result = get_llm_response(final_prompt)

        # 合并源文档
        all_docs = hw_docs + competitor_docs

        return {
            "answer": answer_result,
            "source_documents": all_docs
        }

# 测试运行
if __name__ == "__main__":
    try:
        analyzer = CompetitorAnalyzerService()
        res = analyzer.analyze("阿里云", "智慧农业")
        print("[OK] 竞品分析服务测试成功")
        print("分析结果：\n", res["answer"][:500])
    except Exception as e:
        print("[ERR] 竞品分析测试失败")
        print("错误：", str(e))